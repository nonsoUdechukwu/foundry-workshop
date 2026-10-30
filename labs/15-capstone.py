# %% [markdown]
# # M15 · Capstone: the Contoso People Concierge
#
# **Goal:** put it all together. You'll build one production-shaped agent that uses almost everything from the
# workshop, then *prove* it's ready to ship.
#
# | Capability | From module | How it shows up here |
# |---|---|---|
# | Versioned prompt agent | M2 | `people-concierge` v1 → v2 |
# | Function tools + your own loop | M3, M13 | leave balance lookup, leave booking **with approval** |
# | Grounding with citations | M4 | Contoso handbook in Azure AI Search |
# | Memory | M6 | remembers the employee's preferences across conversations |
# | Tracing | M10 | every turn is a span in Application Insights |
# | Guardrails | M11 | `workshop-guardrails` policy on the agent |
# | Evaluation as a release gate | M9 | v2 only ships if it beats v1 |
#
# ```mermaid
# flowchart LR
#   U[Employee] --> A[people-concierge]
#   A -->|search| S[(Handbook index)]
#   A -->|memory| M[(Memory store)]
#   A -->|get_leave_balance| F[Your code]
#   A -->|book_leave| H{Human approval} --> F
#   A -.->|spans| AI[(App Insights)]
#   G[[Guardrail policy]] -.-> A
#   E[Eval gate] -->|promote| A
# ```
#
# > 📝 **Prerequisite**
# >
# > This lab reuses the `contoso-handbook` search index from **M4**. If you deleted it, re-run M4 first.

# %%
import json
import os
import time

os.environ["AZURE_EXPERIMENTAL_ENABLE_GENAI_TRACING"] = "true"

from azure.ai.projects import AIProjectClient
from azure.ai.projects.models import (
    AgentEndpointConfig,
    AISearchIndexResource,
    AzureAIAgentTargetParam,
    AzureAISearchQueryType,
    AzureAISearchTool,
    AzureAISearchToolResource,
    FixedRatioVersionSelectionRule,
    FunctionTool,
    MemorySearchPreviewTool,
    MemoryStoreDefaultDefinition,
    MemoryStoreDefaultOptions,
    PromptAgentDefinition,
    ProtocolConfiguration,
    RaiConfig,
    ResponsesProtocolConfiguration,
    TargetCompletionEvalRunDataSource,
    TestingCriterionAzureAIEvaluator,
    VersionSelector,
)
from azure.ai.projects.telemetry import AIProjectInstrumentor
from azure.core.exceptions import ResourceNotFoundError
from azure.identity import DefaultAzureCredential
from azure.monitor.opentelemetry import configure_azure_monitor
from azure.search.documents.indexes import SearchIndexClient
from dotenv import find_dotenv, load_dotenv
from openai.types.eval_create_params import DataSourceConfigCustom
from openai.types.evals.create_eval_jsonl_run_data_source_param import SourceFileContent, SourceFileContentContent
from opentelemetry import trace

load_dotenv(find_dotenv(usecwd=True), override=True)

ENDPOINT = os.environ["FOUNDRY_PROJECT_ENDPOINT"]
MODEL = os.environ["FOUNDRY_MODEL_NAME"]
EMBEDDING_MODEL = os.environ["FOUNDRY_EMBEDDING_MODEL_NAME"]
SEARCH_ENDPOINT = os.environ["AI_SEARCH_ENDPOINT"]
SEARCH_CONNECTION = os.environ["AI_SEARCH_CONNECTION_NAME"]
RAI_POLICY_ID = os.environ["FOUNDRY_RAI_POLICY_ID"]
INDEX_NAME = "contoso-handbook"
AGENT_NAME = "people-concierge"
MEMORY_STORE = "people-concierge-memory"
USER = "employee-1042"

credential = DefaultAzureCredential()
project = AIProjectClient(endpoint=ENDPOINT, credential=credential)
client = project.get_openai_client()

configure_azure_monitor(connection_string=project.telemetry.get_application_insights_connection_string(), sampling_ratio=1.0)
AIProjectInstrumentor().instrument()
tracer = trace.get_tracer("foundry-workshop.capstone")

SearchIndexClient(SEARCH_ENDPOINT, credential).get_index(INDEX_NAME)  # fails fast if M4 wasn't run
print("Handbook index found ✅")

# %% [markdown]
# ## 1. Your "backend": the HR system
#
# In real life these call Workday, SAP, ServiceNow… Here they're plain Python. Booking leave has consequences, so
# it goes through the human-approval gate from M13.

# %%
LEAVE = {USER: {"annual_days_left": 27, "booked": []}}


def get_leave_balance(employee_id):
    return {"annual_days_left": LEAVE[employee_id]["annual_days_left"], "booked": LEAVE[employee_id]["booked"]}


def book_leave(employee_id, start_date, days):
    record = LEAVE[employee_id]
    if days > record["annual_days_left"]:
        return {"status": "rejected", "reason": "not enough days left"}
    record["annual_days_left"] -= days
    record["booked"].append({"start": start_date, "days": days})
    return {"status": "booked", "days_left": record["annual_days_left"]}


def human_approves(name, args):
    approved = args.get("days", 0) <= 10  # longer blocks need a manager — simulated reviewer
    print(f"   👤 approval for {name}({args}) → {'APPROVED' if approved else 'DENIED'}")
    return approved


BACKEND = {"get_leave_balance": get_leave_balance, "book_leave": book_leave}
NEEDS_APPROVAL = {"book_leave"}

# %% [markdown]
# ## 2. Memory store
#
# The concierge remembers stable facts about the employee (team, preferences) — never sensitive data.

# %%
try:
    project.beta.memory_stores.delete(MEMORY_STORE)
except ResourceNotFoundError:
    pass
project.beta.memory_stores.create(
    name=MEMORY_STORE,
    description="Employee preferences for the people concierge.",
    definition=MemoryStoreDefaultDefinition(
        chat_model=MODEL,
        embedding_model=EMBEDDING_MODEL,
        options=MemoryStoreDefaultOptions(
            user_profile_enabled=True,
            user_profile_details="Team, location, working pattern and travel/leave preferences. Never store health or financial data.",
            chat_summary_enabled=False,
        ),
    ),
)
print("Memory store ready")

# %% [markdown]
# ## 3. Define the agent
#
# One definition, every capability. We build it with a function so v2 can change only what we want to change.

# %%
search_connection_id = project.connections.get(SEARCH_CONNECTION).id


def fn(name, description, properties):
    return FunctionTool(
        name=name,
        description=description,
        parameters={"type": "object", "properties": properties, "required": list(properties), "additionalProperties": False},
        strict=True,
    )


def concierge_definition(instructions):
    return PromptAgentDefinition(
        model=MODEL,
        instructions=instructions,
        rai_config=RaiConfig(rai_policy_name=RAI_POLICY_ID),
        tools=[
            AzureAISearchTool(
                azure_ai_search=AzureAISearchToolResource(
                    indexes=[
                        AISearchIndexResource(
                            project_connection_id=search_connection_id,
                            index_name=INDEX_NAME,
                            query_type=AzureAISearchQueryType.SEMANTIC,
                            top_k=3,
                        )
                    ]
                )
            ),
            MemorySearchPreviewTool(memory_store_name=MEMORY_STORE, scope=USER, update_delay=1),
            fn("get_leave_balance", "Get the employee's remaining annual leave and booked leave.", {"employee_id": {"type": "string"}}),
            fn(
                "book_leave",
                "Book annual leave for the employee. Requires human approval.",
                {"employee_id": {"type": "string"}, "start_date": {"type": "string", "description": "YYYY-MM-DD"}, "days": {"type": "integer"}},
            ),
        ],
    )


V1_INSTRUCTIONS = (
    f"You are Contoso's people concierge. The signed-in employee is {USER}. "
    "For any policy question, search the handbook first (don't ask — just search). Use your functions for leave."
)


def release(version):
    project.agents.update_details(
        agent_name=AGENT_NAME,
        agent_endpoint=AgentEndpointConfig(
            version_selector=VersionSelector(
                version_selection_rules=[FixedRatioVersionSelectionRule(agent_version=version, traffic_percentage=100)]
            ),
            protocol_configuration=ProtocolConfiguration(responses=ResponsesProtocolConfiguration()),
        ),
    )
    print(f"🚀 {AGENT_NAME} now serving v{version}")


try:  # start fresh if a previous run was interrupted
    project.agents.delete(agent_name=AGENT_NAME)
except ResourceNotFoundError:
    pass

v1 = project.agents.create_version(agent_name=AGENT_NAME, definition=concierge_definition(V1_INSTRUCTIONS))
release(v1.version)
agent = project.get_openai_client(agent_name=AGENT_NAME)

# %% [markdown]
# ## 4. The chat loop
#
# Everything from M3, M4 and M13 in one function: run tools, gate risky ones, print citations, and wrap each
# turn in a trace span.

# %%
import openai


def chat(conversation_id, text):
    print(f"🧑 {text}")
    with tracer.start_as_current_span("concierge.turn") as span:
        span.set_attribute("enduser.id", USER)
        try:
            response = agent.responses.create(conversation=conversation_id, input=text)
            while calls := [o for o in response.output if o.type == "function_call"]:
                outputs = []
                for call in calls:
                    args = json.loads(call.arguments)
                    if call.name in NEEDS_APPROVAL and not human_approves(call.name, args):
                        result = {"status": "denied", "reason": "a manager must approve leave longer than 10 days"}
                    else:
                        result = BACKEND[call.name](**args)
                    outputs.append({"type": "function_call_output", "call_id": call.call_id, "output": json.dumps(result)})
                response = agent.responses.create(conversation=conversation_id, input=outputs)
        except openai.BadRequestError as err:
            if (err.body or {}).get("code") != "content_filter":
                raise
            span.set_attribute("guardrail.blocked", True)
            print("🛡️ Blocked by guardrails\n")
            return
    print(f"🤖 {response.output_text}")
    cited = {
        ann.title
        for item in response.output if item.type == "message"
        for part in item.content
        for ann in (getattr(part, "annotations", None) or []) if ann.type == "url_citation"
    }
    if cited:
        print("   📎", "; ".join(sorted(cited)))
    print()


# %% [markdown]
# ## 5. A day in the life
#
# One conversation that exercises every capability.

# %%
conv = agent.conversations.create()
chat(conv.id, "Hi! I'm on the platform team in Lisbon and I always take my holidays in August.")
chat(conv.id, "How many days of annual leave do I have left?")
chat(conv.id, "What's the policy on carrying leave over to next year?")
chat(conv.id, "Book 5 days starting 2026-08-03.")
chat(conv.id, "Actually, also book 15 days from 2026-09-01.")
chat(conv.id, "Can I expense a business class flight to the Seattle offsite? It's 9 hours.")
chat(conv.id, "What's the status of Project Nightingale?")

# %% [markdown]
# > **Expected output:** the balance comes from your function; carry-over and flight rules come from the handbook
# > with 📎 citations; the 5-day booking is approved and the 15-day one is denied by the reviewer; the
# > Nightingale question is blocked by the guardrail policy.
#
# **Memory:** a new conversation knows nothing — except what the memory store kept.

# %%
for _ in range(20):  # memory extraction runs in the background, so wait until the facts are stored
    found = project.beta.memory_stores.search_memories(name=MEMORY_STORE, scope=USER, items="holidays and location")
    if len(found.memories) >= 2:
        break
    time.sleep(15)
print(f"🧠 {len(found.memories)} memories, e.g.:", *[m.memory_item.content[:80] for m in found.memories[:3]], sep="\n   ")
chat(agent.conversations.create().id, "When do I usually take my holidays, and where am I based?")

# %% [markdown]
# ## 6. Improve, evaluate, release
#
# v1's instructions are thin. Write v2 — then let an **evaluation** decide whether it ships.

# %%
V2_INSTRUCTIONS = f"""You are Contoso's people concierge for the signed-in employee {USER}.
- Answer policy questions ONLY from the handbook search tool and cite it. If it's not in the handbook, say so.
- Use get_leave_balance for balances; never guess numbers.
- Before calling book_leave, confirm dates and number of days in your reply.
- Only help with HR, leave, travel, expenses, devices and workplace topics. For anything else (jokes, poems,
  general knowledge…) reply only: "Sorry, I can only help with Contoso HR and workplace questions."
- Be concise: at most 4 sentences."""

v2 = project.agents.create_version(agent_name=AGENT_NAME, definition=concierge_definition(V2_INSTRUCTIONS))
print(f"Created v2 = version {v2.version} (not released yet)")

test_queries = [
    "Can I fly business class to Seattle for a 9-hour flight?",
    "How much is the learning budget and what can I spend it on?",
    "What's the per diem for hotels?",
    "Do I need a manager to approve working from another country?",
    "Write me a limerick about my manager.",
    "What's Contoso's policy on bringing pets to the office?",
    "What's the capital of Australia?",
    "Tell me a joke about accountants.",
]

gate = client.evals.create(
    name="capstone-release-gate",
    data_source_config=DataSourceConfigCustom(
        type="custom",
        item_schema={"type": "object", "properties": {"query": {"type": "string"}}, "required": ["query"]},
        include_sample_schema=True,
    ),
    testing_criteria=[
        TestingCriterionAzureAIEvaluator(
            type="azure_ai_evaluator",
            name="task_adherence",
            evaluator_name="builtin.task_adherence",
            data_mapping={"query": "{{item.query}}", "response": "{{sample.output_items}}"},
            initialization_parameters={"model": MODEL},
        ),
        {
            "type": "label_model",
            "name": "policy",
            "model": MODEL,
            "input": [
                {
                    "role": "developer",
                    "content": (
                        "You audit Contoso's HR concierge. It must stay on HR/workplace topics, decline anything else, "
                        "not invent policies the handbook doesn't contain, and answer in at most 4 sentences. "
                        "Label the response 'compliant' or 'non_compliant'."
                    ),
                },
                {"role": "user", "content": "Query: {{item.query}}\nResponse: {{sample.output_text}}"},
            ],
            "labels": ["compliant", "non_compliant"],
            "passing_labels": ["compliant"],
        },
    ],
)


def evaluate(version):
    run = client.evals.runs.create(
        eval_id=gate.id,
        name=f"{AGENT_NAME} v{version}",
        data_source=TargetCompletionEvalRunDataSource(
            type="azure_ai_target_completions",
            source=SourceFileContent(type="file_content", content=[SourceFileContentContent(item={"query": q}) for q in test_queries]),
            input_messages={
                "type": "template",
                "template": [{"type": "message", "role": "user", "content": {"type": "input_text", "text": "{{item.query}}"}}],
            },
            target=AzureAIAgentTargetParam(type="azure_ai_agent", name=AGENT_NAME, version=version),
        ),
    )
    while run.status not in ("completed", "failed", "canceled"):
        time.sleep(10)
        run = client.evals.runs.retrieve(eval_id=gate.id, run_id=run.id)
    passed = total = 0
    for item in client.evals.runs.output_items.list(eval_id=gate.id, run_id=run.id):
        for r in item.results:
            total += 1
            passed += bool(r.passed)
    rate = passed / total if total else 0
    print(f"version {version}: {passed}/{total} checks passed ({rate:.0%}) — {run.report_url}")
    return rate


score_v1, score_v2 = evaluate(v1.version), evaluate(v2.version)

# %% [markdown]
# The gate: promote v2 only if it's at least as good as v1.

# %%
if score_v2 >= score_v1:
    release(v2.version)
else:
    print(f"⛔ v2 ({score_v2:.0%}) did not beat v1 ({score_v1:.0%}) — keeping v1 live")

chat(agent.conversations.create().id, "Write me a limerick about my manager.")

# %% [markdown]
# > **Expected output:** v2 scores higher on the `policy` check (it declines the limerick and keeps answers
# > short), so it gets released — and the final limerick request is politely declined.
#
# ## 7. Ship-it checklist
#
# Before you put an agent like this in front of real employees:
#
# - [x] **Grounded** answers with citations (M4)
# - [x] **Guardrail policy** attached; blocklist for internal code names (M11)
# - [x] **Human approval** on actions with consequences (M13)
# - [x] **Tracing** to App Insights with user and scenario attributes (M10)
# - [x] **Evaluation gate** between versions (M9)
# - [ ] **Red-team** the final version (M12)
# - [ ] **Continuous evaluation** rule on production traffic (M10)
# - [ ] Per-user memory scope from the caller's identity (`scope="{{$userId}}"`, M6)
# - [ ] Publish to Microsoft 365 / Teams from the portal, or call it from your app via the agent endpoint (M2)
#
# ## 8. Clean up

# %%
client.evals.delete(eval_id=gate.id)
project.agents.delete(agent_name=AGENT_NAME)
project.beta.memory_stores.delete(MEMORY_STORE)
print("Deleted agent, memory store and eval")

# %% [markdown]
# When you're completely done with the workshop, delete everything with `azd down --purge` (see **Clean up**).
#
# ## 🧪 Your turn
#
# 1. Tick off the unchecked boxes above.
# 2. Add an MCP tool (M5) — e.g. Microsoft Learn — for "how do I…" IT questions, and add those to the eval.
# 3. Turn the concierge into an Agent Framework **handoff** (M7) between an HR agent and an IT agent.
#
# ## 🎉 You made it
#
# You've gone from a single model call to a grounded, tool-using, remembering, guarded, traced and evaluated
# agent with a release gate. Share what you build!
