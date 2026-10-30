# %% [markdown]
# # M4 · Grounding with RAG
#
# **Goal:** stop the model from guessing. Index your own documents in **Azure AI Search**, then give an agent the
# **Azure AI Search tool** so every answer is grounded in — and cites — your data.
#
# ```mermaid
# flowchart LR
#   D[contoso-handbook.jsonl] -->|embed| E[text-embedding-3-small]
#   E --> I[(AI Search index<br/>text + vectors)]
#   U[User question] --> A[Agent]
#   A -- AzureAISearchTool --> I
#   I -- top passages --> A
#   A -- answer + citations --> U
# ```
#
# We use a small, fictional **Contoso employee handbook** (travel, expenses, leave, IT…). The model has never seen
# it, so any correct answer must come from retrieval.

# %%
import json
import os
from pathlib import Path
from urllib.request import urlopen

from azure.ai.projects import AIProjectClient
from azure.ai.projects.models import (
    AgentEndpointConfig,
    AISearchIndexResource,
    AzureAISearchQueryType,
    AzureAISearchTool,
    AzureAISearchToolResource,
    FixedRatioVersionSelectionRule,
    PromptAgentDefinition,
    ProtocolConfiguration,
    ResponsesProtocolConfiguration,
    VersionSelector,
)
from azure.identity import DefaultAzureCredential, get_bearer_token_provider
from dotenv import find_dotenv, load_dotenv

load_dotenv(find_dotenv(usecwd=True), override=True)

ENDPOINT = os.environ["FOUNDRY_PROJECT_ENDPOINT"]
MODEL = os.environ["FOUNDRY_MODEL_NAME"]
EMBEDDING_MODEL = os.environ["FOUNDRY_EMBEDDING_MODEL_NAME"]
SEARCH_ENDPOINT = os.environ["AI_SEARCH_ENDPOINT"]
SEARCH_CONNECTION = os.environ["AI_SEARCH_CONNECTION_NAME"]
INDEX_NAME = "contoso-handbook"

credential = DefaultAzureCredential()
project = AIProjectClient(endpoint=ENDPOINT, credential=credential)

# Embeddings are served from the account-level endpoint (see M1 §7).
from openai import OpenAI

embedder = OpenAI(
    base_url=ENDPOINT.split("/api/projects/")[0] + "/openai/v1/",
    api_key=get_bearer_token_provider(credential, "https://ai.azure.com/.default"),
)

# %% [markdown]
# ## 1. Load the documents
#
# The notebook looks for `docs/data/contoso-handbook.jsonl` in the repo and falls back to GitHub if you
# downloaded the notebook on its own.

# %%
DATA_URL = "https://raw.githubusercontent.com/nonsoUdechukwu/foundry-workshop/main/docs/data/contoso-handbook.jsonl"
local = next((p for p in [Path("docs/data/contoso-handbook.jsonl"), Path("../data/contoso-handbook.jsonl")] if p.exists()), None)
raw = local.read_text(encoding="utf-8") if local else urlopen(DATA_URL).read().decode("utf-8")
docs = [json.loads(line) for line in raw.splitlines() if line.strip()]
print(f"Loaded {len(docs)} documents, e.g. → {docs[0]['title']}")

# %% [markdown]
# ## 2. Create a hybrid index
#
# The index stores both the **text** (for keyword + semantic ranking) and a **vector** (for similarity search).
# You authenticate to AI Search with Entra ID — the template gave you *Search Index Data Contributor*.

# %%
from azure.search.documents import SearchClient
from azure.search.documents.indexes import SearchIndexClient
from azure.search.documents.indexes.models import (
    HnswAlgorithmConfiguration,
    SearchableField,
    SearchField,
    SearchFieldDataType,
    SearchIndex,
    SemanticConfiguration,
    SemanticField,
    SemanticPrioritizedFields,
    SemanticSearch,
    SimpleField,
    VectorSearch,
    VectorSearchProfile,
)

DIMENSIONS = 1536

index = SearchIndex(
    name=INDEX_NAME,
    fields=[
        SimpleField(name="id", type=SearchFieldDataType.String, key=True),
        SearchableField(name="title", type=SearchFieldDataType.String),
        SearchableField(name="content", type=SearchFieldDataType.String),
        SimpleField(name="url", type=SearchFieldDataType.String),
        SearchField(
            name="content_vector",
            type=SearchFieldDataType.Collection(SearchFieldDataType.Single),
            searchable=True,
            vector_search_dimensions=DIMENSIONS,
            vector_search_profile_name="default",
        ),
    ],
    vector_search=VectorSearch(
        algorithms=[HnswAlgorithmConfiguration(name="hnsw")],
        profiles=[VectorSearchProfile(name="default", algorithm_configuration_name="hnsw")],
    ),
    semantic_search=SemanticSearch(
        default_configuration_name="default",
        configurations=[
            SemanticConfiguration(
                name="default",
                prioritized_fields=SemanticPrioritizedFields(
                    title_field=SemanticField(field_name="title"),
                    content_fields=[SemanticField(field_name="content")],
                ),
            )
        ],
    ),
)

index_client = SearchIndexClient(SEARCH_ENDPOINT, credential)
index_client.create_or_update_index(index)
print("Index ready:", INDEX_NAME)

# %% [markdown]
# ## 3. Embed and upload
#
# One call to the embeddings API vectorises every document.

# %%
embeddings = embedder.embeddings.create(model=EMBEDDING_MODEL, input=[f"{d['title']}\n{d['content']}" for d in docs])
for doc, emb in zip(docs, embeddings.data):
    doc["content_vector"] = emb.embedding

search_client = SearchClient(SEARCH_ENDPOINT, INDEX_NAME, credential)
results = search_client.upload_documents(docs)
print(f"Uploaded {sum(r.succeeded for r in results)}/{len(docs)} documents")

# %% [markdown]
# ## 4. Try retrieval on its own
#
# Before involving an agent, check that retrieval works. This is a **hybrid** query: keywords + vector,
# merged with Reciprocal Rank Fusion.

# %%
import time

from azure.search.documents.models import VectorizedQuery

time.sleep(2)  # give the index a moment to make new documents searchable

question = "Can I fly business class to Seattle?"
q_vector = embedder.embeddings.create(model=EMBEDDING_MODEL, input=question).data[0].embedding

for hit in search_client.search(
    search_text=question,
    vector_queries=[VectorizedQuery(vector=q_vector, k_nearest_neighbors=3, fields="content_vector")],
    select=["title"],
    top=3,
):
    print(f"{hit['@search.score']:.3f}  {hit['title']}")

# %% [markdown]
# ## 5. A grounded agent
#
# The agent reaches AI Search through the **project connection** created by the template. The tool needs the
# connection's resource ID, which we look up by name.

# %%
connection_id = project.connections.get(SEARCH_CONNECTION).id

AGENT_NAME = "m4-handbook-agent"
version = project.agents.create_version(
    agent_name=AGENT_NAME,
    definition=PromptAgentDefinition(
        model=MODEL,
        instructions=(
            "You answer Contoso employee questions using ONLY the handbook search tool. "
            "If the handbook doesn't cover it, say so. Keep answers short and always cite your sources."
        ),
        tools=[
            AzureAISearchTool(
                azure_ai_search=AzureAISearchToolResource(
                    indexes=[
                        AISearchIndexResource(
                            project_connection_id=connection_id,
                            index_name=INDEX_NAME,
                            query_type=AzureAISearchQueryType.SEMANTIC,
                            top_k=3,
                        )
                    ]
                )
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


def ask(q: str) -> None:
    response = agent.responses.create(input=q, tool_choice="required")
    print(f"Q: {q}\nA: {response.output_text}")
    for item in response.output:
        if item.type == "message":
            for part in item.content:
                for ann in getattr(part, "annotations", []) or []:
                    if ann.type == "url_citation":
                        print(f"   📎 cited: {ann.title}")
    print()


ask("Can I fly business class to Seattle?")
ask("How many days of parental leave do I get, and can I split them?")
ask("What's the policy on bringing my dog to the office?")

# %% [markdown]
# > **Expected output:** the first two answers quote the handbook (10-hour rule, 20 weeks in up to three blocks)
# > with 📎 citations. The dog question should be answered with "the handbook doesn't cover that" — the
# > instructions forbid guessing.

# %% [markdown]
# ## 6. Clean up
#
# Keep the index if you plan to do the capstone (M15) — it reuses it. Otherwise delete it too.

# %%
project.agents.delete(agent_name=AGENT_NAME)
print("Deleted agent", AGENT_NAME)
# index_client.delete_index(INDEX_NAME)

# %% [markdown]
# ## 🧪 Your turn
#
# 1. Switch `query_type` to `AzureAISearchQueryType.SIMPLE` and compare answers for a vague question such as
#    *"how much can I spend on a hotel?"*.
# 2. Add a document about a new policy to the JSONL, re-run sections 1–3, and ask about it — no agent change needed.
# 3. Try the **File Search** tool instead: upload files to a vector store with `client.vector_stores` and attach
#    `FileSearchTool(vector_store_ids=[...])`. When would you choose that over AI Search?
#
# ## Recap
#
# * RAG = retrieve relevant passages, then generate an answer grounded in them.
# * Azure AI Search gives you hybrid (keyword + vector) and semantic ranking with Entra ID auth.
# * The **AzureAISearchTool** connects an agent to an index through a **project connection** and returns citations.
#
# Next: **[M5 · MCP tools](../05-mcp-tools/)**.
