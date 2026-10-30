# %% [markdown]
# # M2 · Your first agent
#
# **Goal:** promote a prompt into a **versioned agent** that lives in your Foundry project, then talk to it
# with conversations — exactly like M1, but now the instructions, model and tools are managed server-side.
#
# ```mermaid
# flowchart LR
#   A[Your code] -- create_version --> B[(Agent: name + versions)]
#   A -- responses.create --> E[Agent endpoint]
#   E -- routes 100% --> V2[version 2]
#   B --- V1[version 1]
#   B --- V2
# ```
#
# Key ideas:
#
# * An **agent** has a stable *name* and immutable *versions*. Each `create_version` call snapshots the
#   definition (model, instructions, tools, guardrails).
# * The **agent endpoint** decides which version receives traffic — you can pin, roll forward or roll back.
# * You invoke an agent with the **same Responses API** you used in M1.

# %%
import os

from azure.ai.projects import AIProjectClient
from azure.ai.projects.models import (
    AgentEndpointConfig,
    FixedRatioVersionSelectionRule,
    PromptAgentDefinition,
    ProtocolConfiguration,
    ResponsesProtocolConfiguration,
    VersionSelector,
)
from azure.identity import DefaultAzureCredential
from dotenv import find_dotenv, load_dotenv

load_dotenv(find_dotenv(usecwd=True), override=True)

ENDPOINT = os.environ["FOUNDRY_PROJECT_ENDPOINT"]
MODEL = os.environ["FOUNDRY_MODEL_NAME"]

credential = DefaultAzureCredential()
project = AIProjectClient(endpoint=ENDPOINT, credential=credential)

AGENT_NAME = "m2-trip-planner"

# %% [markdown]
# ## 1. Create version 1

# %%
v1 = project.agents.create_version(
    agent_name=AGENT_NAME,
    description="Plans short city breaks.",
    definition=PromptAgentDefinition(
        model=MODEL,
        instructions=(
            "You are a friendly travel planner. Given a city and a number of days, "
            "propose a day-by-day plan with at most 3 activities per day. Keep it brief."
        ),
    ),
)
print(f"Created {v1.name} version {v1.version} (id {v1.id})")

# %% [markdown]
# ## 2. Route the agent endpoint to that version
#
# The endpoint is what callers hit. We send 100% of traffic to v1. Later you'll see how to roll forward.

# %%
def route_traffic(agent_name: str, *weights: tuple[str, int]) -> None:
    """Point the agent endpoint at a version, e.g. route_traffic(name, ("2", 100))."""
    project.agents.update_details(
        agent_name=agent_name,
        agent_endpoint=AgentEndpointConfig(
            version_selector=VersionSelector(
                version_selection_rules=[
                    FixedRatioVersionSelectionRule(agent_version=v, traffic_percentage=p) for v, p in weights
                ]
            ),
            protocol_configuration=ProtocolConfiguration(responses=ResponsesProtocolConfiguration()),
        ),
    )


route_traffic(AGENT_NAME, (v1.version, 100))
agent_client = project.get_openai_client(agent_name=AGENT_NAME)
print("Endpoint routed to v" + v1.version)

# %% [markdown]
# ## 3. Talk to the agent
#
# `project.get_openai_client(agent_name=...)` returns an OpenAI client bound to the agent endpoint, so you
# don't pass `model` or `instructions` — the agent supplies them.

# %%
conversation = agent_client.conversations.create()

reply = agent_client.responses.create(conversation=conversation.id, input="2 days in Lisbon, please.")
print(reply.output_text)

# %%
reply = agent_client.responses.create(
    conversation=conversation.id, input="Swap day 2 for something rainy-day friendly."
)
print(reply.output_text)

# %% [markdown]
# The conversation keeps state server-side. Inspect the items it holds:

# %%
for item in agent_client.conversations.items.list(conversation_id=conversation.id, order="asc"):
    if item.type == "message":
        text = item.content[0].text if item.content else ""
        print(f"{item.role:>9}: {text[:80]}{'…' if len(text) > 80 else ''}")

# %% [markdown]
# ## 4. Ship version 2, roll forward — and roll back
#
# Versions are immutable, so "editing" an agent means creating a new version. Let's add a budget-conscious
# persona, point the endpoint at it, and then show how a rollback is just another routing change.

# %%
v2 = project.agents.create_version(
    agent_name=AGENT_NAME,
    description="Budget-aware city break planner.",
    definition=PromptAgentDefinition(
        model=MODEL,
        instructions=(
            "You are a budget-conscious travel planner. For each activity add an approximate cost in EUR "
            "and finish with a total. Max 3 activities per day. Keep it brief."
        ),
    ),
)
route_traffic(AGENT_NAME, (v2.version, 100))
r = agent_client.responses.create(input="1 day in Porto.")
print(f"v{v2.version} →", r.output_text[:300], "…")

# %%
route_traffic(AGENT_NAME, (v1.version, 100))
r = agent_client.responses.create(input="1 day in Porto.")
print(f"rolled back to v{v1.version} →", r.output_text[:300], "…")

route_traffic(AGENT_NAME, (v2.version, 100))
details = project.agents.get(agent_name=AGENT_NAME)
print("Latest version:", details.versions.latest.version)

# %% [markdown]
# Callers never changed their code — they always talk to `m2-trip-planner`. Only the routing moved.
#
# > ℹ️ **Traffic splitting**
# >
# > The endpoint routes 100% of traffic to one version. Splitting traffic between versions (A/B tests) is done
# > through Foundry **experiments**, which attach an experiment ID to the selector.

# %% [markdown]
# ## 5. Calling a specific version directly
#
# You can bypass endpoint routing and target a version explicitly with an `agent_reference`. This is handy
# for evaluations and tests (M9) where you must know exactly which version answered.

# %%
client = project.get_openai_client()
pinned = client.responses.create(
    input="1 day in Porto.",
    extra_body={"agent_reference": {"type": "agent_reference", "name": AGENT_NAME, "version": v1.version}},
)
print(pinned.output_text)

# %% [markdown]
# ## 6. See it in the portal
#
# Open [ai.azure.com](https://ai.azure.com), pick your project and go to **Agents**. You'll find
# `m2-trip-planner` with both versions — you can chat with each in the playground.
#
# ## 7. Clean up

# %%
agent_client.conversations.delete(conversation_id=conversation.id)
project.agents.delete(agent_name=AGENT_NAME)
print("Deleted", AGENT_NAME)

# %% [markdown]
# ## 🧪 Your turn
#
# 1. Create a v3 with a different `instructions` tone, route traffic to it, then roll back to v2.
# 2. Add `text=PromptAgentDefinitionTextOptions(format=TextResponseFormatJsonSchema(...))` to make the agent always
#    return a JSON itinerary (see M1 §6 for the schema idea).
# 3. List all agents in your project with `project.agents.list()`.
#
# ## Recap
#
# * `create_version` → immutable, auditable snapshots of an agent.
# * The **agent endpoint** controls which version serves traffic (roll forward, roll back).
# * Conversations hold state server-side; the agent supplies model + instructions.
#
# Next: **[M3 · Tools & function calling](../03-tools-and-function-calling/)**.
