# %% [markdown]
# # M7 · Multi-agent orchestration
#
# **Goal:** make several specialised agents work together. You'll build the classic patterns with
# **Microsoft Agent Framework** in your own process, then publish a **declarative workflow agent** that runs
# entirely inside Foundry.
#
# | Pattern | Shape | Good for |
# |---|---|---|
# | **Sequential** | A → B → C | Draft → review → polish pipelines |
# | **Concurrent** | A, B, C in parallel → merge | Multiple perspectives, fan-out research |
# | **Handoff** | Triage routes to a specialist | Customer support, routing |
# | **Workflow agent** (Foundry) | YAML graph of actions | Governed, portal-visible orchestration |
#
# ```mermaid
# flowchart LR
#   subgraph Sequential
#     W[writer] --> R[reviewer]
#   end
#   subgraph Concurrent
#     Q((question)) --> L[legal] & F[finance] & T[tech]
#     L & F & T --> M[merge]
#   end
#   subgraph Handoff
#     TR[triage] -.-> B[billing]
#     TR -.-> S[support]
#   end
# ```

# %%
import os

from agent_framework import Agent
from agent_framework.foundry import FoundryChatClient
from agent_framework.orchestrations import ConcurrentBuilder, HandoffBuilder, SequentialBuilder
from azure.identity.aio import DefaultAzureCredential as AsyncDefaultAzureCredential
from dotenv import find_dotenv, load_dotenv

load_dotenv(find_dotenv(usecwd=True), override=True)

ENDPOINT = os.environ["FOUNDRY_PROJECT_ENDPOINT"]
MODEL = os.environ["FOUNDRY_MODEL_NAME"]

async_credential = AsyncDefaultAzureCredential()
chat_client = FoundryChatClient(project_endpoint=ENDPOINT, model=MODEL, credential=async_credential)


def make_agent(name: str, instructions: str, **kwargs) -> Agent:
    return Agent(client=chat_client, name=name, instructions=instructions, **kwargs)


def show(result) -> None:
    """Print every assistant message in a workflow result, labelled with the agent that wrote it."""
    for output in result.get_outputs():
        for m in output.messages:
            if m.role == "assistant" and m.text:
                print(f"── {m.author_name or 'assistant'} ──\n{m.text}\n")


# %% [markdown]
# ## 1. Sequential: writer → reviewer
#
# Each agent sees the full conversation so far and adds its turn. By default only the **last** agent's response
# is a workflow output; `output_from="all"` surfaces every participant so we can see the draft too.

# %%
writer = make_agent("writer", "You write punchy LinkedIn posts (max 80 words) about the topic you're given.")
reviewer = make_agent(
    "reviewer",
    "You are an editor. Review the previous post for clarity and hype. Return an improved version and one line on what you changed.",
)

sequential = SequentialBuilder(participants=[writer, reviewer], output_from="all").build()
result = await sequential.run("Announce our community's hands-on Microsoft Foundry workshop.")
show(result)

# %% [markdown]
# ## 2. Concurrent: three experts in parallel
#
# The same input fans out to every participant at once; the default aggregator collects their replies into one
# response.

# %%
experts = [
    make_agent("legal", "You are a legal advisor. Give the top legal risk in one sentence."),
    make_agent("finance", "You are a CFO. Give the top financial consideration in one sentence."),
    make_agent("tech", "You are a CTO. Give the top technical consideration in one sentence."),
]
concurrent = ConcurrentBuilder(participants=experts).build()
result = await concurrent.run("We want to let customers chat with an AI agent about their insurance claims.")
show(result)

# %% [markdown]
# ## 3. Handoff: triage routes to a specialist
#
# Agents receive auto-generated `handoff_to_<agent>` tools. The triage agent decides who should own the
# conversation; the specialist answers. The workflow then **pauses** and waits for the user's next message —
# that's a pending request you'd answer with `workflow.run(responses={...})` in an interactive app.
#
# Handoff agents must keep their history in sync with the service, so they're created with
# `require_per_service_call_history_persistence=True`.

# %%
handoff_opts = {"require_per_service_call_history_persistence": True}
triage = make_agent(
    "triage",
    "You route customer messages. Hand off billing/refund questions to billing and technical problems to support. Never answer yourself.",
    **handoff_opts,
)
billing = make_agent("billing", "You handle billing and refunds for Contoso Cloud. Be concise and friendly.", **handoff_opts)
support = make_agent("support", "You fix technical problems with Contoso Cloud. Give numbered steps.", **handoff_opts)

handoff = (
    HandoffBuilder(participants=[triage, billing, support])
    .with_start_agent(triage)
    .add_handoff(triage, [billing, support])
    .add_handoff(billing, [triage])
    .add_handoff(support, [triage])
    .build()
)

result = await handoff.run("I was charged twice for my subscription this month.")
show(result)
print("Waiting for user input:", len(result.get_request_info_events()) > 0)

# %% [markdown]
# > **Expected output:** no answer from `triage` itself — just a handoff — followed by a `billing` reply about the
# > duplicate charge.

# %% [markdown]
# ## 4. Wrap a workflow as an agent
#
# Any workflow can be exposed with `.as_agent()` — callers don't need to know there are several agents inside.

# %%
pipeline_agent = SequentialBuilder(participants=[writer, reviewer]).build().as_agent(name="post-pipeline")
response = await pipeline_agent.run("Write a post about agent memory in Foundry.")
print(response.text)

# %% [markdown]
# ## 5. Declarative workflow agents in Foundry
#
# Everything above runs **in your process**. Foundry can also host the orchestration: you describe it in YAML,
# publish it as a **workflow agent** and invoke it like any other agent. It shows up in the portal's visual
# workflow designer.
#
# > 📝 **Preview**
# >
# > Workflow agents are in preview, so create the client with `allow_preview=True`.

# %%
from azure.ai.projects import AIProjectClient
from azure.ai.projects.models import PromptAgentDefinition, WorkflowAgentDefinition
from azure.identity import DefaultAzureCredential

project = AIProjectClient(endpoint=ENDPOINT, credential=DefaultAzureCredential(), allow_preview=True)
client = project.get_openai_client()

drafter = project.agents.create_version(
    agent_name="m7-drafter",
    definition=PromptAgentDefinition(model=MODEL, instructions="Write a 3-sentence product blurb for the idea you're given."),
)
critic = project.agents.create_version(
    agent_name="m7-critic",
    definition=PromptAgentDefinition(
        model=MODEL,
        instructions="Critique the blurb. If it is clear and under 60 words reply with exactly APPROVED. Otherwise rewrite it.",
    ),
)

workflow_yaml = f"""
kind: workflow
trigger:
  kind: OnConversationStart
  id: blurb_workflow
  actions:
    - kind: SetVariable
      id: capture_input
      variable: Local.Messages
      value: "=UserMessage(System.LastMessageText)"
    - kind: CreateConversation
      id: new_conversation
      conversationId: Local.ConversationId
    - kind: InvokeAzureAgent
      id: draft
      conversationId: "=Local.ConversationId"
      agent:
        name: {drafter.name}
      input:
        messages: "=Local.Messages"
      output:
        messages: Local.Messages
    - kind: InvokeAzureAgent
      id: critique
      conversationId: "=Local.ConversationId"
      agent:
        name: {critic.name}
      input:
        messages: "=Local.Messages"
      output:
        messages: Local.Messages
"""

workflow = project.agents.create_version(
    agent_name="m7-blurb-workflow", definition=WorkflowAgentDefinition(workflow=workflow_yaml)
)
print("Published workflow agent:", workflow.name, "v" + workflow.version)

# %%
conversation = client.conversations.create()
stream = client.responses.create(
    conversation=conversation.id,
    input="A reusable water bottle that tracks how much you drink.",
    extra_body={"agent_reference": {"name": workflow.name, "type": "agent_reference"}},
    stream=True,
)
final = None
for event in stream:
    if event.type == "response.output_item.done" and event.item.type == "workflow_action":
        print(f"✔ action {event.item.action_id}: {event.item.status}")
    elif event.type == "response.completed":
        final = event.response
for item in final.output if final else []:
    if item.type == "message":
        print("\n💬", "".join(part.text for part in item.content if part.type == "output_text"))

# %% [markdown]
# Open the portal → **Agents** → `m7-blurb-workflow` to see the YAML rendered as a visual graph.
#
# ## 6. Clean up

# %%
client.conversations.delete(conversation_id=conversation.id)
for name in ("m7-blurb-workflow", "m7-drafter", "m7-critic"):
    project.agents.delete(agent_name=name)
    print("Deleted", name)
await async_credential.close()

# %% [markdown]
# ## 🧪 Your turn
#
# 1. Add a third participant (`fact-checker`) to the sequential workflow.
# 2. Use `ConcurrentBuilder(...).with_aggregator(fn)` to merge the expert opinions into a single summary.
# 3. Extend the YAML with a `ConditionGroup` that loops back to `draft` until the critic says `APPROVED`
#    (hint: `GotoAction`, and cap the number of loops with a counter variable).
# 4. Try `MagenticBuilder` for a manager-led, plan-and-execute team.
#
# ## Recap
#
# * Agent Framework gives you **sequential**, **concurrent**, **handoff**, **group chat** and **Magentic**
#   orchestrations as builders; any workflow can become an agent with `.as_agent()`.
# * **Workflow agents** move orchestration into Foundry as versioned, portal-visible YAML.
#
# Next: **[M8 · Deep research](../08-deep-research/)**.
