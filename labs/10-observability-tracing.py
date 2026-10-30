# %% [markdown]
# # M10 · Observability & tracing
#
# **Goal:** see *inside* your agents. Send OpenTelemetry traces to **Application Insights**, read them in the
# Foundry portal, query them with KQL, and set up **continuous evaluation** so production traffic is scored
# automatically.
#
# ```mermaid
# flowchart LR
#   A[Your app<br/>+ agents] -- OpenTelemetry spans --> AI[(Application Insights)]
#   AI --> P[Foundry portal<br/>Tracing tab]
#   AI --> K[KQL queries]
#   F[Agent responses] -- rule: response.completed --> E[Continuous eval]
#   E --> M[Monitoring dashboard]
# ```
#
# The template already connected an Application Insights resource to your project (connection
# `workshop-appinsights`), so there is nothing to set up in the portal.

# %%
import os

# Opt in to GenAI tracing and capture prompts/responses. Only do this where content may be stored.
os.environ["AZURE_EXPERIMENTAL_ENABLE_GENAI_TRACING"] = "true"
os.environ["OTEL_INSTRUMENTATION_GENAI_CAPTURE_MESSAGE_CONTENT"] = "true"

from azure.ai.projects import AIProjectClient
from azure.ai.projects.models import (
    AgentEndpointConfig,
    FixedRatioVersionSelectionRule,
    FunctionTool,
    PromptAgentDefinition,
    ProtocolConfiguration,
    ResponsesProtocolConfiguration,
    VersionSelector,
)
from azure.ai.projects.telemetry import AIProjectInstrumentor
from azure.identity import DefaultAzureCredential
from azure.monitor.opentelemetry import configure_azure_monitor
from dotenv import find_dotenv, load_dotenv
from opentelemetry import trace

load_dotenv(find_dotenv(usecwd=True), override=True)

ENDPOINT = os.environ["FOUNDRY_PROJECT_ENDPOINT"]
MODEL = os.environ["FOUNDRY_MODEL_NAME"]

credential = DefaultAzureCredential()
project = AIProjectClient(endpoint=ENDPOINT, credential=credential)

# %% [markdown]
# ## 1. Wire up OpenTelemetry → Application Insights
#
# The project tells you which App Insights resource it's connected to. `configure_azure_monitor` installs an
# exporter, and `AIProjectInstrumentor` emits **GenAI semantic-convention** spans for agent and response calls.

# %%
connection_string = project.telemetry.get_application_insights_connection_string()
# sampling_ratio=1.0 keeps every trace. The default rate-limits spans, which is fine in production but not here.
configure_azure_monitor(connection_string=connection_string, sampling_ratio=1.0)
AIProjectInstrumentor().instrument(enable_content_recording=True)

tracer = trace.get_tracer("foundry-workshop.m10")
print("Tracing to Application Insights ✅")

# %% [markdown]
# ## 2. Generate a trace worth looking at
#
# We wrap a small multi-step scenario — an agent with a function tool — in our own parent span, and add
# attributes (user, scenario) you can filter on later.

# %%
import json

AGENT_NAME = "m10-traced-agent"
version = project.agents.create_version(
    agent_name=AGENT_NAME,
    definition=PromptAgentDefinition(
        model=MODEL,
        instructions="You help with Contoso stock levels. Use the tool. Be brief.",
        tools=[
            FunctionTool(
                name="get_stock",
                description="Get units in stock for a product SKU.",
                parameters={
                    "type": "object",
                    "properties": {"sku": {"type": "string"}},
                    "required": ["sku"],
                    "additionalProperties": False,
                },
                strict=True,
            )
        ],
    ),
)
project.agents.update_details(
    agent_name=AGENT_NAME,
    agent_endpoint=AgentEndpointConfig(
        version_selector=VersionSelector(
            version_selection_rules=[FixedRatioVersionSelectionRule(agent_version=version.version, traffic_percentage=100)]
        ),
        protocol_configuration=ProtocolConfiguration(responses=ResponsesProtocolConfiguration()),
    ),
)
agent = project.get_openai_client(agent_name=AGENT_NAME)

STOCK = {"SKU-42": 17, "SKU-7": 0}

with tracer.start_as_current_span("m10.stock-check") as span:
    span.set_attribute("enduser.id", "workshop-attendee")
    span.set_attribute("scenario", "stock-check")

    response = agent.responses.create(input="Do we have SKU-42 and SKU-7 in stock?")
    outputs = []
    for call in (o for o in response.output if o.type == "function_call"):
        sku = json.loads(call.arguments)["sku"]
        with tracer.start_as_current_span("tool.get_stock") as tool_span:
            tool_span.set_attribute("sku", sku)
            outputs.append({"type": "function_call_output", "call_id": call.call_id, "output": json.dumps({"units": STOCK.get(sku, 0)})})
    response = agent.responses.create(input=outputs, previous_response_id=response.id)
    print(response.output_text)
    trace_id = format(span.get_span_context().trace_id, "032x")

print("Trace ID:", trace_id)

# %% [markdown]
# ## 3. Turn on continuous evaluation
#
# Offline evals (M9) tell you if a version is good *before* release. **Continuous evaluation** samples live
# responses and scores them *after* release. You define an eval with the `responses` scenario and a rule that
# triggers it whenever the agent completes a response.
#
# We create the rule **now**, because scoring runs in the background and results take a while to appear.
# Rules filter by agent name; we point this one at a simple Q&A agent, `m10-live-agent`.

# %%
from azure.ai.projects.models import (
    AzureAIDataSourceConfig,
    ContinuousEvaluationRuleAction,
    EvaluationRule,
    EvaluationRuleEventType,
    EvaluationRuleFilter,
    TestingCriterionAzureAIEvaluator,
)

client = project.get_openai_client()
LIVE_AGENT = "m10-live-agent"
project.agents.create_version(
    agent_name=LIVE_AGENT,
    definition=PromptAgentDefinition(model=MODEL, instructions="You answer questions about Contoso's return policy: 30 days with receipt. Be brief."),
)

live_eval = client.evals.create(
    name="m10-live-quality",
    data_source_config=AzureAIDataSourceConfig(type="azure_ai_source", scenario="responses"),
    testing_criteria=[
        TestingCriterionAzureAIEvaluator(type="azure_ai_evaluator", name="violence", evaluator_name="builtin.violence"),
        TestingCriterionAzureAIEvaluator(
            type="azure_ai_evaluator",
            name="task_adherence",
            evaluator_name="builtin.task_adherence",
            initialization_parameters={"model": MODEL},
        ),
    ],
)

RULE_ID = "m10-live-quality-rule"
rule = project.evaluation_rules.create_or_update(
    id=RULE_ID,
    evaluation_rule=EvaluationRule(
        display_name="M10 live quality",
        description="Score every m10-live-agent response",
        action=ContinuousEvaluationRuleAction(eval_id=live_eval.id, max_hourly_runs=50),
        event_type=EvaluationRuleEventType.RESPONSE_COMPLETED,
        filter=EvaluationRuleFilter(agent_name=LIVE_AGENT),
        enabled=True,
    ),
)
print("Rule created:", rule.display_name)

# Some traffic for the rule to score while we look at traces.
for question in ("Can I return shoes after 3 weeks?", "What if I lost the receipt?", "Write me a poem about pirates."):
    client.responses.create(input=question, extra_body={"agent_reference": {"type": "agent_reference", "name": LIVE_AGENT}})
print("Sent 3 scored requests")

# %% [markdown]
# ## 4. Agent Framework spans go to the same place
#
# Agent Framework emits its own spans (agent invoke, chat, tool execution). Turn them on and they flow through the
# exporter you already configured.

# %%
from typing import Annotated

from agent_framework import Agent, tool
from agent_framework.foundry import FoundryChatClient
from agent_framework.observability import enable_instrumentation
from azure.identity.aio import DefaultAzureCredential as AsyncDefaultAzureCredential

enable_instrumentation(enable_sensitive_data=True)


@tool(approval_mode="never_require")
def get_stock(sku: Annotated[str, "Product SKU"]) -> int:
    """Get units in stock for a product SKU."""
    return STOCK.get(sku, 0)


async with AsyncDefaultAzureCredential() as async_credential:
    af_agent = Agent(
        client=FoundryChatClient(project_endpoint=ENDPOINT, model=MODEL, credential=async_credential),
        name="stock-helper",
        instructions="Answer stock questions using the tool. Be brief.",
        tools=[get_stock],
    )
    with tracer.start_as_current_span("m10.agent-framework"):
        print((await af_agent.run("Is SKU-7 available?")).text)

# %% [markdown]
# ## 5. Look at the traces
#
# **In the portal:** open your project → **Tracing** (or **Agents → m10-traced-agent → Traces**). Find the
# `m10.stock-check` trace: you'll see the two `responses` calls, the `tool.get_stock` spans in between, token
# counts and — because content recording is on — the actual messages.
#
# **With KQL:** telemetry takes a few minutes to arrive. This cell polls App Insights for the spans of our trace.

# %%
import time
from datetime import timedelta

from azure.monitor.query import LogsQueryClient

trace.get_tracer_provider().force_flush()
app_insights_id = project.connections.get("workshop-appinsights").target
logs = LogsQueryClient(credential)

query = f"""
union dependencies, requests
| where operation_Id == '{trace_id}'
| project timestamp, name, duration, gen_ai_operation = tostring(customDimensions['gen_ai.operation.name']),
          input_tokens = toint(customDimensions['gen_ai.usage.input_tokens']),
          output_tokens = toint(customDimensions['gen_ai.usage.output_tokens'])
| order by timestamp asc
"""

rows = []
for _ in range(20):  # client and service spans arrive separately
    result = logs.query_resource(app_insights_id, query, timespan=timedelta(hours=1))
    rows = result.tables[0].rows if result.tables else []
    names = {r[1] for r in rows}
    if {"m10.stock-check", "tool.get_stock"} <= names:
        break
    time.sleep(30)

for r in rows:
    print(f"{str(r[1])[:45]:<45} {r[2]:>8.0f} ms  {r[3] or '':<16} in={r[4]} out={r[5]}")
if not rows:
    print("No rows yet — ingestion can take a few minutes. Re-run this cell.")

# %% [markdown]
# > **Expected output:** one row per span in the trace — the parent `m10.stock-check`, two `responses` /
# > agent spans with token counts, and the `tool.get_stock` spans.

# %% [markdown]
# ## 6. Check the continuous-evaluation results
#
# By now the rule has probably scored the requests from section 3. This cell polls for up to 15 minutes; if
# your facilitator is moving on, leave it running and come back. Each scored response becomes its own run.

# %%
print("Waiting for continuous evaluation runs…")
runs = []
for _ in range(60):
    runs = list(client.evals.runs.list(eval_id=live_eval.id, order="desc", limit=10))
    if len(runs) >= 3 and all(r.status in ("completed", "failed") for r in runs):
        break
    time.sleep(15)
if runs and runs[0].report_url:
    print("Portal:", "/".join(runs[0].report_url.split("/")[:-2]))
for r in runs:
    print(f"{r.name or r.id}: {r.status} {r.result_counts}")
if not runs:
    print("No runs yet — continuous evaluation can lag. Check the portal later (the rule is deleted in section 7).")

# %% [markdown]
# Open **Monitoring** (or **Agents → m10-live-agent → Monitor**) in the portal to see these scores over time.
#
# ## 7. Clean up

# %%
project.evaluation_rules.delete(id=RULE_ID)
client.evals.delete(eval_id=live_eval.id)
project.agents.delete(agent_name=AGENT_NAME)
project.agents.delete(agent_name=LIVE_AGENT)
print("Cleaned up")

# %% [markdown]
# ## 🧪 Your turn
#
# 1. Turn content recording **off** (`enable_content_recording=False`) and compare what you see in the trace.
# 2. Write a KQL query that sums `gen_ai.usage.output_tokens` per agent over the last day — that's a cost dashboard.
# 3. Add `builtin.intent_resolution` to the continuous-eval criteria.
#
# ## Recap
#
# * One call wires your app to App Insights; GenAI spans follow OpenTelemetry semantic conventions.
# * Custom spans + attributes let you group agent calls into business operations.
# * **Continuous evaluation** rules score live traffic automatically — offline evals (M9) + online evals = full
#   coverage.
#
# Next: **[M11 · Guardrails & content safety](../11-guardrails/)**.
