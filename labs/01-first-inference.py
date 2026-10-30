# %% [markdown]
# # M1 · First inference
#
# **Goal:** make your first calls to a model deployed in your Foundry project — plain responses,
# multi-turn, streaming, structured output and embeddings — all through **one authenticated client**.
#
# | You'll use | Why |
# | --- | --- |
# | `AIProjectClient` | The single entry point to a Foundry project (agents, evals, connections, deployments…). |
# | `project.get_openai_client()` | An OpenAI-compatible client, already authenticated with Entra ID and pointed at your project. |
# | **Responses API** | The unified API Foundry agents are built on — it replaces "chat completions + threads + runs". |
#
# > ℹ️ **Before you start**
# >
# > Complete [Setup](../../setup/) so that a `.env` file with `FOUNDRY_PROJECT_ENDPOINT` and
# > `FOUNDRY_MODEL_NAME` sits in the repo root, and you are signed in with `az login`.

# %% [markdown]
# ## 1. Bootstrap the project client
#
# Every lab starts with the same cell. `DefaultAzureCredential` picks up your `az login` session locally,
# a managed identity in Azure, or a service principal in CI — no keys in code.

# %%
import os

from azure.ai.projects import AIProjectClient
from azure.identity import DefaultAzureCredential
from dotenv import find_dotenv, load_dotenv

load_dotenv(find_dotenv(usecwd=True), override=True)

ENDPOINT = os.environ["FOUNDRY_PROJECT_ENDPOINT"]
MODEL = os.environ["FOUNDRY_MODEL_NAME"]
EMBEDDING_MODEL = os.environ.get("FOUNDRY_EMBEDDING_MODEL_NAME", "text-embedding-3-small")

credential = DefaultAzureCredential()
project = AIProjectClient(endpoint=ENDPOINT, credential=credential)
client = project.get_openai_client()

print("Project :", ENDPOINT)
print("Model   :", MODEL)

# %% [markdown]
# ## 2. What's deployed in this project?
#
# `project.deployments` lists the model deployments your project can use. The **deployment name** (not the
# model name) is what you pass as `model=` in every call.

# %%
for d in project.deployments.list():
    print(f"{d.name:<28} {d.model_publisher:<10} {d.model_name} ({d.model_version}) sku={d.sku.name}")

# %% [markdown]
# **Expected output** — at least two rows: your chat model (e.g. `gpt-5.4-mini`) and `text-embedding-3-small`.

# %% [markdown]
# ## 3. Your first response
#
# `responses.create` takes an `input` (a string or a list of messages) and optional `instructions`
# (the system prompt). `output_text` concatenates all text parts of the answer.

# %%
response = client.responses.create(
    model=MODEL,
    instructions="You are a concise Azure architect. Answer in at most three sentences.",
    input="What is Microsoft Foundry, in plain English?",
)
print(response.output_text)
print("\nTokens:", response.usage.input_tokens, "in /", response.usage.output_tokens, "out")

# %% [markdown]
# ## 4. Multi-turn without resending history
#
# Responses are **stored server-side** by default. Pass `previous_response_id` and the service stitches the
# conversation together for you — no need to resend earlier turns.

# %%
follow_up = client.responses.create(
    model=MODEL,
    input="Name two things it gives me that I'd otherwise build myself.",
    previous_response_id=response.id,
)
print(follow_up.output_text)

# %% [markdown]
# For longer-lived chats, create a **conversation** object and attach responses to it. Agents (M2 onward)
# use the same mechanism.

# %%
conversation = client.conversations.create(
    items=[{"type": "message", "role": "user", "content": "My name is Ada and I run a bakery."}]
)
r1 = client.responses.create(model=MODEL, conversation=conversation.id, input="Suggest a tagline for my shop.")
r2 = client.responses.create(model=MODEL, conversation=conversation.id, input="What's my name again?")
print(r1.output_text, "\n---\n", r2.output_text)
client.conversations.delete(conversation_id=conversation.id)

# %% [markdown]
# ## 5. Streaming
#
# Set `stream=True` and iterate over server-sent events. Print text deltas as they arrive — this is what
# gives chat UIs their "typing" feel.

# %%
stream = client.responses.create(
    model=MODEL,
    input="Explain retrieval-augmented generation to a 10-year-old in 4 short bullet points.",
    stream=True,
)
for event in stream:
    if event.type == "response.output_text.delta":
        print(event.delta, end="", flush=True)
    elif event.type == "response.completed":
        print(f"\n\n[done — {event.response.usage.output_tokens} output tokens]")

# %% [markdown]
# ## 6. Structured output
#
# Ask the model to return JSON that conforms to a schema. With the OpenAI SDK you can pass a Pydantic model
# directly to `responses.parse` and get a typed object back.

# %%
from pydantic import BaseModel, Field


class SupportTicket(BaseModel):
    summary: str = Field(description="One-line summary of the issue")
    product: str
    severity: str = Field(description="One of: low, medium, high, critical")
    customer_sentiment: str = Field(description="One of: positive, neutral, negative")


email = """Hi team — since this morning our checkout page on the Contoso Shop app throws a 500 error
for every customer. We're losing sales by the minute. Please help ASAP! — Priya"""

parsed = client.responses.parse(
    model=MODEL,
    instructions="Extract a support ticket from the email.",
    input=email,
    text_format=SupportTicket,
)
ticket = parsed.output_parsed
print(ticket.model_dump_json(indent=2))

# %% [markdown]
# **Expected output** — something like `"severity": "critical"`, `"customer_sentiment": "negative"`.

# %% [markdown]
# ## 7. Embeddings
#
# Embeddings turn text into vectors so you can compare meaning. M4 uses them to build a search index; here
# we just compute cosine similarity between a few sentences.
#
# > 📝 **Embeddings use the account endpoint**
# >
# > The project-scoped client covers responses, conversations and agents. Embeddings are served from the
# > Foundry **account's** OpenAI-compatible endpoint (`https://<account>.services.ai.azure.com/openai/v1/`),
# > which we derive from the project endpoint. It uses the same Entra ID token — no keys.

# %%
import math

from azure.identity import get_bearer_token_provider
from openai import OpenAI

account_client = OpenAI(
    base_url=ENDPOINT.split("/api/projects/")[0] + "/openai/v1/",
    api_key=get_bearer_token_provider(credential, "https://ai.azure.com/.default"),
)

sentences = [
    "How do I reset my password?",
    "I forgot my login credentials.",
    "What's the weather in Lagos today?",
]
emb = account_client.embeddings.create(model=EMBEDDING_MODEL, input=sentences)
vectors = [item.embedding for item in emb.data]


def cosine(a, b):
    dot = sum(x * y for x, y in zip(a, b))
    return dot / (math.sqrt(sum(x * x for x in a)) * math.sqrt(sum(y * y for y in b)))


print(f"dimensions: {len(vectors[0])}")
print(f"password vs credentials : {cosine(vectors[0], vectors[1]):.3f}")
print(f"password vs weather     : {cosine(vectors[0], vectors[2]):.3f}")

# %% [markdown]
# **Expected output** — the first pair scores clearly higher than the second.

# %% [markdown]
# ## 🧪 Your turn
#
# 1. Add a `next_action` field (one of `escalate`, `reply`, `close`) to `SupportTicket` and re-run section 6.
# 2. Stream a response **and** count how many `response.output_text.delta` events you received.
# 3. Try `input=[{"role": "user", "content": [{"type": "input_text", "text": "Describe this"}, {"type": "input_image", "image_url": "https://upload.wikimedia.org/wikipedia/commons/3/3f/Fronalpstock_big.jpg"}]}]` — your chat model is multimodal.
#
# ## Recap
#
# * One `AIProjectClient` + `DefaultAzureCredential` is all you need — no keys.
# * The **Responses API** handles single-turn, multi-turn (`previous_response_id` / conversations), streaming and structured output.
# * Deployment **names** are what you pass as `model=`.
#
# Next: **[M2 · Your first agent](../02-your-first-agent/)** — turn these instructions into a versioned, reusable agent.
