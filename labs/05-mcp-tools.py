# %% [markdown]
# # M5 · MCP tools
#
# **Goal:** plug agents into the growing ecosystem of **Model Context Protocol (MCP)** servers — and keep a human
# in control of what they're allowed to call.
#
# MCP is an open protocol that lets any server expose tools (search, tickets, databases, …) in a standard way. A
# Foundry agent can call a remote MCP server directly; you only provide its URL.
#
# ```mermaid
# sequenceDiagram
#   participant You
#   participant Agent as Foundry agent
#   participant MCP as MCP server (Microsoft Learn)
#   You->>Agent: question
#   Agent->>MCP: tools/list
#   Agent-->>You: mcp_approval_request (if approval required)
#   You->>Agent: mcp_approval_response approve=true
#   Agent->>MCP: tools/call microsoft_docs_search
#   MCP-->>Agent: results
#   Agent-->>You: grounded answer
# ```
#
# We use the public **Microsoft Learn MCP server** (`https://learn.microsoft.com/api/mcp`) — no key required.

# %%
import os

from azure.ai.projects import AIProjectClient
from azure.ai.projects.models import (
    AgentEndpointConfig,
    FixedRatioVersionSelectionRule,
    MCPTool,
    PromptAgentDefinition,
    ProtocolConfiguration,
    ResponsesProtocolConfiguration,
    VersionSelector,
)
from azure.identity import DefaultAzureCredential
from dotenv import find_dotenv, load_dotenv
from openai.types.responses.response_input_param import McpApprovalResponse

load_dotenv(find_dotenv(usecwd=True), override=True)

ENDPOINT = os.environ["FOUNDRY_PROJECT_ENDPOINT"]
MODEL = os.environ["FOUNDRY_MODEL_NAME"]

credential = DefaultAzureCredential()
project = AIProjectClient(endpoint=ENDPOINT, credential=credential)

LEARN_MCP = "https://learn.microsoft.com/api/mcp"


def deploy_agent(name: str, definition: PromptAgentDefinition):
    version = project.agents.create_version(agent_name=name, definition=definition)
    project.agents.update_details(
        agent_name=name,
        agent_endpoint=AgentEndpointConfig(
            version_selector=VersionSelector(
                version_selection_rules=[FixedRatioVersionSelectionRule(agent_version=version.version, traffic_percentage=100)]
            ),
            protocol_configuration=ProtocolConfiguration(responses=ResponsesProtocolConfiguration()),
        ),
    )
    print(f"Deployed {name} v{version.version}")
    return project.get_openai_client(agent_name=name)


# %% [markdown]
# ## 1. A trusted, read-only server: no approval
#
# For read-only tools you trust, set `require_approval="never"` and restrict the agent to an explicit
# `allowed_tools` list. Least privilege applies to agents too.

# %%
DOCS_AGENT = "m5-learn-docs"
docs_agent = deploy_agent(
    DOCS_AGENT,
    PromptAgentDefinition(
        model=MODEL,
        instructions="Answer Microsoft technology questions using the Microsoft Learn tools. Cite the Learn URLs you used.",
        tools=[
            MCPTool(
                server_label="mslearn",
                server_url=LEARN_MCP,
                require_approval="never",
                allowed_tools=["microsoft_docs_search"],
            )
        ],
    ),
)

response = docs_agent.responses.create(input="In Microsoft Foundry, what is the difference between a hub-based project and a Foundry project?")

for item in response.output:
    if item.type == "mcp_list_tools":
        print("🔌 tools offered by server:", [t.name for t in item.tools])
    elif item.type == "mcp_call":
        print(f"🔧 {item.name}({item.arguments[:80]}…)")
print("\n" + response.output_text)

# %% [markdown]
# > **Expected output:** an `mcp_list_tools` item (only `microsoft_docs_search` is allowed even though the server
# > offers more), one or more `mcp_call` items, then an answer with learn.microsoft.com links.

# %% [markdown]
# ## 2. Human approval for every call
#
# With `require_approval="always"`, the agent **pauses** and returns an `mcp_approval_request` describing exactly
# which tool and arguments it wants to use. Your app decides, then resumes the response with an
# `mcp_approval_response`.

# %%
GATED_AGENT = "m5-gated-learn"
gated = deploy_agent(
    GATED_AGENT,
    PromptAgentDefinition(
        model=MODEL,
        instructions="Use the Microsoft Learn tools to answer. Prefer fetching the full page when a search result looks relevant.",
        tools=[MCPTool(server_label="mslearn", server_url=LEARN_MCP, require_approval="always")],
    ),
)


def approve_interactively(request) -> bool:
    """Replace with input(...) for a real prompt. Here we approve searches and deny everything else."""
    decision = request.name == "microsoft_docs_search"
    print(f"   ❓ {request.name}({request.arguments[:70]}…) → {'APPROVED' if decision else 'DENIED'}")
    return decision


response = gated.responses.create(input="How do I enable tracing for agents in Microsoft Foundry? Give me the key steps.")

for _ in range(6):
    requests = [item for item in response.output if item.type == "mcp_approval_request"]
    if not requests:
        break
    decisions = [
        McpApprovalResponse(type="mcp_approval_response", approval_request_id=r.id, approve=approve_interactively(r))
        for r in requests
    ]
    response = gated.responses.create(input=decisions, previous_response_id=response.id)

print("\n" + response.output_text)

# %% [markdown]
# > ⚠️ **Treat MCP servers like any third-party dependency**
# >
# > An MCP server sees whatever arguments the agent sends it, and its responses flow back into the model's
# > context. Only connect servers you trust, prefer `allowed_tools`, and require approval for anything that
# > writes or spends money. For servers that need credentials, store them in a **project connection** and pass
# > `project_connection_id=` instead of putting secrets in `headers`.

# %% [markdown]
# ## 3. A second server in the same agent
#
# Agents can mix MCP servers with other tools. Here we add [gitmcp.io](https://gitmcp.io), which exposes any public
# GitHub repo's docs over MCP.

# %%
MULTI_AGENT = "m5-multi-mcp"
multi = deploy_agent(
    MULTI_AGENT,
    PromptAgentDefinition(
        model=MODEL,
        instructions="You help developers. Use mslearn for Microsoft docs and af-repo for Agent Framework source/docs.",
        tools=[
            MCPTool(server_label="mslearn", server_url=LEARN_MCP, require_approval="never", allowed_tools=["microsoft_docs_search"]),
            MCPTool(server_label="af-repo", server_url="https://gitmcp.io/microsoft/agent-framework", require_approval="never"),
        ],
    ),
)
response = multi.responses.create(input="What orchestration patterns does Microsoft Agent Framework support? One line each.")
print({item.server_label for item in response.output if item.type == "mcp_call"})
print(response.output_text)

# %% [markdown]
# ## 4. Clean up

# %%
for name in (DOCS_AGENT, GATED_AGENT, MULTI_AGENT):
    project.agents.delete(agent_name=name)
    print("Deleted", name)

# %% [markdown]
# ## 🧪 Your turn
#
# 1. Change `approve_interactively` to call `input()` so *you* approve each call.
# 2. Connect an MCP server you use at work (e.g. the GitHub MCP server). Create a **Custom keys** connection in
#    the portal holding the token, and pass its name as `project_connection_id`.
# 3. Browse the tool catalogue in the Foundry portal (**Build → Tools**) and add a server from there.
#
# ## Recap
#
# * `MCPTool` connects an agent to any remote MCP server by URL.
# * `allowed_tools` + `require_approval` give you least-privilege and human-in-the-loop control.
# * Approval requests come back as `mcp_approval_request`; resume with `mcp_approval_response` + `previous_response_id`.
#
# Next: **[M6 · Agent memory](../06-agent-memory/)**.
