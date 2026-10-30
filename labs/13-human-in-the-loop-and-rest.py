# %% [markdown]
# # M13 · Human-in-the-loop & the REST API
#
# **Goal:** keep a human in charge of risky actions, and see that everything you've done with the SDK is just
# HTTPS underneath — so you can call Foundry from *any* language.
#
# ```mermaid
# flowchart LR
#   U[User] --> A[Agent]
#   A -- wants to call<br/>risky tool --> H{Human approves?}
#   H -- yes --> T[Tool runs]
#   H -- no --> D[Agent told 'denied']
#   T --> A
#   D --> A
# ```
#
# You've already seen one approval flow: **MCP `require_approval="always"`** in M5. Here we do the same for
# your *own* function tools, using three patterns:
#
# 1. **Agent Framework** — mark a tool `approval_mode="always_require"`.
# 2. **Foundry agent + your own loop** — the function-calling loop is your code, so approval is just an `if`.
# 3. **REST** — the same agent APIs with `requests` and a bearer token.

# %%
import json
import os
from typing import Annotated

from azure.ai.projects import AIProjectClient
from azure.ai.projects.models import FunctionTool, PromptAgentDefinition
from azure.identity import DefaultAzureCredential
from dotenv import find_dotenv, load_dotenv

load_dotenv(find_dotenv(usecwd=True), override=True)

ENDPOINT = os.environ["FOUNDRY_PROJECT_ENDPOINT"]
MODEL = os.environ["FOUNDRY_MODEL_NAME"]

credential = DefaultAzureCredential()
project = AIProjectClient(endpoint=ENDPOINT, credential=credential)
client = project.get_openai_client()

# Notebooks can't pop up a real approval UI, so we simulate the human with a policy function.
# Swap this for input(), a Teams card, a ticket queue — whatever your process is.
APPROVAL_LIMIT = 100


def human_approves(tool_name, args):
    decision = not (tool_name == "issue_refund" and float(args.get("amount", 0)) > APPROVAL_LIMIT)
    print(f"   👤 approval requested: {tool_name}({args}) → {'APPROVED' if decision else 'DENIED'}")
    return decision


# %% [markdown]
# ## 1. Agent Framework: tools that require approval
#
# When a tool is marked `approval_mode="always_require"`, the agent **stops** and returns
# `user_input_requests` instead of running it. You answer each request and call `run` again on the same session.

# %%
from agent_framework import Agent, Message, tool
from agent_framework.foundry import FoundryChatClient
from azure.identity.aio import DefaultAzureCredential as AsyncDefaultAzureCredential


@tool(approval_mode="never_require")
def get_claim(claim_id: Annotated[str, "Expense claim ID"]) -> str:
    """Look up an expense claim."""
    claims = {"EXP-1": {"amount": 42.50, "item": "taxi"}, "EXP-2": {"amount": 860.00, "item": "conference ticket"}}
    return json.dumps(claims.get(claim_id, {"error": "not found"}))


@tool(approval_mode="always_require")
def issue_refund(claim_id: Annotated[str, "Expense claim ID"], amount: Annotated[float, "Amount in USD"]) -> str:
    """Refund an expense claim to the employee."""
    return f"Refunded ${amount:.2f} for {claim_id}."


async def run_with_approvals(agent, prompt):
    session = agent.create_session()
    response = await agent.run(prompt, session=session)
    while response.user_input_requests:
        answers = []
        for request in response.user_input_requests:
            call = request.function_call
            args = call.parse_arguments()
            answers.append(request.to_function_approval_response(human_approves(call.name, args)))
        response = await agent.run(Message(role="user", contents=answers), session=session)
    return response.text


async with AsyncDefaultAzureCredential() as async_credential:
    refunds = Agent(
        client=FoundryChatClient(project_endpoint=ENDPOINT, model=MODEL, credential=async_credential),
        name="refund-agent",
        instructions="You process expense refunds. Look up the claim, then refund the full amount. Report the outcome.",
        tools=[get_claim, issue_refund],
    )
    for claim in ("EXP-1", "EXP-2"):
        print(f"▶ Refund {claim}")
        print("  ", await run_with_approvals(refunds, f"Please refund claim {claim}."), "\n")

# %% [markdown]
# > **Expected output:** EXP-1 ($42.50) is approved and refunded. EXP-2 ($860) is denied, and the agent explains
# > that the refund wasn't processed.
#
# ## 2. Foundry agent: approval in your own tool loop
#
# With a Foundry prompt agent and function tools, the model only *proposes* calls; your code executes them. So
# a human gate is just a check before you run the function — and you report the denial back as the tool output.

# %%
AGENT_NAME = "m13-refunds"
project.agents.create_version(
    agent_name=AGENT_NAME,
    definition=PromptAgentDefinition(
        model=MODEL,
        instructions="You process expense refunds. Look up the claim, then refund the full amount. Report the outcome.",
        tools=[
            FunctionTool(
                name="get_claim",
                description="Look up an expense claim.",
                parameters={"type": "object", "properties": {"claim_id": {"type": "string"}}, "required": ["claim_id"], "additionalProperties": False},
                strict=True,
            ),
            FunctionTool(
                name="issue_refund",
                description="Refund an expense claim to the employee.",
                parameters={
                    "type": "object",
                    "properties": {"claim_id": {"type": "string"}, "amount": {"type": "number"}},
                    "required": ["claim_id", "amount"],
                    "additionalProperties": False,
                },
                strict=True,
            ),
        ],
    ),
)
agent_ref = {"agent_reference": {"type": "agent_reference", "name": AGENT_NAME}}
local_tools = {"get_claim": get_claim.func, "issue_refund": issue_refund.func}


def run_foundry_agent(prompt):
    response = client.responses.create(input=prompt, extra_body=agent_ref)
    while calls := [o for o in response.output if o.type == "function_call"]:
        outputs = []
        for call in calls:
            args = json.loads(call.arguments)
            if call.name == "issue_refund" and not human_approves(call.name, args):
                result = "DENIED by a human reviewer: refunds over $100 need manager sign-off."
            else:
                result = local_tools[call.name](**args)
            outputs.append({"type": "function_call_output", "call_id": call.call_id, "output": str(result)})
        response = client.responses.create(input=outputs, previous_response_id=response.id, extra_body=agent_ref)
    return response.output_text


for claim in ("EXP-1", "EXP-2"):
    print(f"▶ Refund {claim}")
    print("  ", run_foundry_agent(f"Please refund claim {claim}."), "\n")

# %% [markdown]
# > 💡 **Long waits**
# >
# > Real approvals can take hours. Store `response.id` (or use a **conversation**) and resume with
# > `previous_response_id` / `conversation` when the human answers — nothing needs to stay in memory.
#
# ## 3. The same thing over REST
#
# Every SDK call above is an HTTPS request. Get a Microsoft Entra token for `https://ai.azure.com` and call the
# project endpoint directly — handy for languages without an SDK, low-code tools or quick `curl` tests.

# %%
import requests

token = credential.get_token("https://ai.azure.com/.default").token
headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
API = {"api-version": "v1"}

# List agents (agent management APIs take ?api-version=v1)
agents = requests.get(f"{ENDPOINT}/agents", params=API, headers=headers).json()["data"]
print("Agents:", [a["name"] for a in agents])

# Create an agent version
r = requests.post(
    f"{ENDPOINT}/agents/m13-rest-agent/versions",
    params=API,
    headers=headers,
    json={"definition": {"kind": "prompt", "model": MODEL, "instructions": "Answer in exactly one sentence."}},
)
r.raise_for_status()
print("Created:", r.json()["id"])

# Start a conversation and invoke the agent (OpenAI-compatible routes live under /openai/v1)
conversation = requests.post(f"{ENDPOINT}/openai/v1/conversations", headers=headers, json={}).json()
r = requests.post(
    f"{ENDPOINT}/openai/v1/responses",
    headers=headers,
    json={
        "conversation": conversation["id"],
        "input": "What does Microsoft Foundry do?",
        "agent_reference": {"type": "agent_reference", "name": "m13-rest-agent"},
    },
)
r.raise_for_status()
text = [c["text"] for o in r.json()["output"] if o["type"] == "message" for c in o["content"]]
print("Agent:", " ".join(text))

# %% [markdown]
# Streaming uses **server-sent events** — each `data:` line is a JSON event.

# %%
with requests.post(
    f"{ENDPOINT}/openai/v1/responses",
    headers=headers,
    json={"model": MODEL, "input": "Name three Azure regions, comma-separated.", "stream": True},
    stream=True,
) as stream:
    for line in stream.iter_lines():
        if line.startswith(b"data:"):
            event = json.loads(line[5:])
            if event["type"] == "response.output_text.delta":
                print(event["delta"], end="", flush=True)
print()

# %% [markdown]
# The equivalent `curl`:
#
# ```bash
# TOKEN=$(az account get-access-token --resource https://ai.azure.com --query accessToken -o tsv)
# curl -s "$FOUNDRY_PROJECT_ENDPOINT/openai/v1/responses" \
#   -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
#   -d '{"model": "'$FOUNDRY_MODEL_NAME'", "input": "Hello from curl"}'
# ```
#
# ## 4. Clean up

# %%
requests.delete(f"{ENDPOINT}/agents/m13-rest-agent", params=API, headers=headers).raise_for_status()
project.agents.delete(agent_name=AGENT_NAME)
print("Cleaned up")

# %% [markdown]
# ## 🧪 Your turn
#
# 1. Replace `human_approves` with `input()` and approve the refunds yourself.
# 2. Persist the pending `response.id` to a file, restart the kernel, and resume the approval.
# 3. Port the REST cell to another language you use (C#, TypeScript, PowerShell).
#
# ## Recap
#
# * Put a human gate on **actions with consequences**: payments, emails, deletes, production changes.
# * Agent Framework: `approval_mode="always_require"` → handle `user_input_requests`.
# * Foundry function tools: your loop runs the tool, so approval is just code. MCP: `require_approval`.
# * The REST API is plain HTTPS + an Entra token: `/agents?api-version=v1` for management, `/openai/v1/...` for
#   responses and conversations.
#
# Next: **[M14 · Fine-tuning & distillation](../14-fine-tuning-distillation/)**.
