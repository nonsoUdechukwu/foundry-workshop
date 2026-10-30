# %% [markdown]
# # M6 · Agent memory
#
# **Goal:** give agents **long-term memory** that survives across conversations, scoped per user — so the agent
# remembers that you're vegetarian without you repeating it every chat.
#
# | Kind of state | Lifetime | Where |
# |---|---|---|
# | Conversation (M1/M2) | One thread | `conversations` API |
# | **Memory store** (this lab) | Across threads, per *scope* (e.g. user) | `project.beta.memory_stores` |
#
# ```mermaid
# flowchart LR
#   C1[Conversation 1<br/>“I'm vegetarian”] -- extract --> M[(Memory store<br/>scope = user)]
#   M -- search --> C2[Conversation 2<br/>“Suggest dinner”]
# ```
#
# > 📝 **Preview**
# >
# > Memory stores are in **preview** (the `beta` sub-client). APIs may change.

# %%
import os
import time

from azure.ai.projects import AIProjectClient
from azure.ai.projects.models import (
    AgentEndpointConfig,
    FixedRatioVersionSelectionRule,
    MemorySearchOptions,
    MemorySearchPreviewTool,
    MemoryStoreDefaultDefinition,
    MemoryStoreDefaultOptions,
    PromptAgentDefinition,
    ProtocolConfiguration,
    ResponsesProtocolConfiguration,
    VersionSelector,
)
from azure.core.exceptions import ResourceNotFoundError
from azure.identity import DefaultAzureCredential
from dotenv import find_dotenv, load_dotenv

load_dotenv(find_dotenv(usecwd=True), override=True)

ENDPOINT = os.environ["FOUNDRY_PROJECT_ENDPOINT"]
MODEL = os.environ["FOUNDRY_MODEL_NAME"]
EMBEDDING_MODEL = os.environ["FOUNDRY_EMBEDDING_MODEL_NAME"]

credential = DefaultAzureCredential()
project = AIProjectClient(endpoint=ENDPOINT, credential=credential)

STORE = "m6-workshop-memory"

# %% [markdown]
# ## 1. Create a memory store
#
# A memory store uses a **chat model** to extract and consolidate facts and an **embedding model** to search them.
# We enable two memory types:
#
# * **User profile** — stable facts and preferences ("is vegetarian", "lives in Lagos").
# * **Chat summary** — condensed summaries of past conversations.

# %%
try:
    project.beta.memory_stores.delete(STORE)
except ResourceNotFoundError:
    pass

store = project.beta.memory_stores.create(
    name=STORE,
    description="Food and travel preferences for the workshop concierge.",
    definition=MemoryStoreDefaultDefinition(
        chat_model=MODEL,
        embedding_model=EMBEDDING_MODEL,
        options=MemoryStoreDefaultOptions(
            user_profile_enabled=True,
            user_profile_details="Dietary needs, food likes/dislikes, home city and travel preferences. Ignore anything sensitive.",
            chat_summary_enabled=True,
        ),
    ),
)
print("Created memory store:", store.name)

# %% [markdown]
# ## 2. Write and search memories directly
#
# You don't need an agent to use memory. `begin_update_memories` extracts facts from any text or message list;
# `search_memories` retrieves the ones relevant to a query. **Scope** isolates users from each other.

# %%
poller = project.beta.memory_stores.begin_update_memories(
    name=STORE,
    scope="ada",
    items="I'm Ada. I'm vegetarian, I can't stand coriander, and I'm based in Lagos.",
    update_delay=0,  # process now instead of waiting for inactivity
)
result = poller.result()
for op in result.memory_operations:
    print(f"{op.kind:>7}: {op.memory_item.content}")

# %%
hits = project.beta.memory_stores.search_memories(
    name=STORE, scope="ada", items="What should I cook for Ada?", options=MemorySearchOptions(max_memories=5)
)
print("ada →", [m.memory_item.content for m in hits.memories])

other = project.beta.memory_stores.search_memories(name=STORE, scope="grace", items="What should I cook for Grace?")
print("grace →", [m.memory_item.content for m in other.memories], "(different scope, nothing leaks)")

# %% [markdown]
# ## 3. An agent with memory
#
# Attach `MemorySearchPreviewTool` and the agent will **read** relevant memories before answering and **write** new
# ones after the conversation goes idle for `update_delay` seconds.
#
# > 💡 **Per-user scope in production**
# >
# > Set `scope="{{$userId}}"` and Foundry uses the caller's Entra object ID automatically, so every signed-in
# > user gets private memory with no extra code.

# %%
AGENT_NAME = "m6-concierge"
version = project.agents.create_version(
    agent_name=AGENT_NAME,
    definition=PromptAgentDefinition(
        model=MODEL,
        instructions="You are a personal food & travel concierge. Use what you remember about the user. Be brief.",
        tools=[MemorySearchPreviewTool(memory_store_name=STORE, scope="ada", update_delay=1)],
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

# %% [markdown]
# **Conversation 1** — tell the agent something new.

# %%
conv1 = agent.conversations.create()
r = agent.responses.create(
    conversation=conv1.id,
    input="Next month I'm going to Lisbon for a conference. I always prefer window seats and boutique hotels.",
)
print(r.output_text)

# %% [markdown]
# Memory extraction runs asynchronously after the conversation goes quiet. Give it a minute.

# %%
print("Waiting for memories to be extracted…")
time.sleep(60)

# %% [markdown]
# **Conversation 2** — a brand-new thread. The agent has no conversation history, only memory.

# %%
conv2 = agent.conversations.create()
r = agent.responses.create(conversation=conv2.id, input="Recommend a dinner spot and a hotel for my next trip.")
print(r.output_text)

# %% [markdown]
# > **Expected output:** suggestions **in Lisbon** with a **boutique** hotel — facts the agent only knows from memory
# > of conversation 1. Memory extraction is model-driven, so wording (and which facts are consolidated) varies
# > between runs.

# %%
everything = project.beta.memory_stores.search_memories(name=STORE, scope="ada", items="Everything about Ada")
for m in everything.memories:
    print("•", m.memory_item.content)

# %% [markdown]
# ## 4. Forget (right to erasure)
#
# Delete everything stored for a scope — e.g. when a user asks to be forgotten — then clean up.

# %%
project.beta.memory_stores.delete_scope(name=STORE, scope="ada")
print("Memories for 'ada' deleted")

for c in (conv1, conv2):
    agent.conversations.delete(conversation_id=c.id)
project.agents.delete(agent_name=AGENT_NAME)
project.beta.memory_stores.delete(STORE)
print("Cleaned up")

# %% [markdown]
# ## 🧪 Your turn
#
# 1. Change `scope` to `"{{$userId}}"` and confirm your memories are stored under your Entra object ID.
# 2. Turn off `chat_summary_enabled` and compare what gets stored.
# 3. Use Agent Framework's `FoundryMemoryProvider` (`agent_framework.foundry`) to add the same memory store to an
#    in-process `Agent` from M3.
#
# ## Recap
#
# * Memory stores persist **user profile** facts and **chat summaries** across conversations.
# * **Scope** isolates memory per user; `{{$userId}}` maps it to the caller's identity.
# * Use the API directly (`update_memories` / `search_memories`) or attach `MemorySearchPreviewTool` to an agent.
#
# Next: **[M7 · Multi-agent orchestration](../07-multi-agent-orchestration/)**.
