# %% [markdown]
# # M3 · Tools & function calling
#
# **Goal:** give agents abilities beyond text generation — run Python in a sandbox, and call *your own* code.
#
# | Tool type | Where it runs | You write |
# |---|---|---|
# | **Code interpreter** | A Foundry-managed sandbox | Nothing — just enable it |
# | **Function tool** | Your process | A JSON schema + the function + a small loop |
# | **Agent Framework `@tool`** | Your process | A typed Python function — the framework runs the loop |
#
# ```mermaid
# sequenceDiagram
#   participant You
#   participant Agent as Foundry agent
#   You->>Agent: "What's the weather in Oslo, in °F?"
#   Agent-->>You: function_call get_weather(city="Oslo")
#   You->>You: run get_weather()
#   You->>Agent: function_call_output {...}
#   Agent-->>You: "It's 41 °F and cloudy in Oslo."
# ```

# %%
import json
import os

from azure.ai.projects import AIProjectClient
from azure.ai.projects.models import (
    AgentEndpointConfig,
    CodeInterpreterTool,
    FixedRatioVersionSelectionRule,
    FunctionTool,
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


def deploy_agent(name: str, definition: PromptAgentDefinition, description: str = ""):
    """Create a new agent version and route 100% of the agent endpoint to it (see M2)."""
    version = project.agents.create_version(agent_name=name, definition=definition, description=description)
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
    return version


# %% [markdown]
# ## 1. Code interpreter
#
# The model writes Python, Foundry runs it in an isolated container, and the model reads the results. Great for
# maths, data wrangling and charts — anything where "guessing" would be wrong.

# %%
ANALYST = "m3-data-analyst"
deploy_agent(
    ANALYST,
    PromptAgentDefinition(
        model=MODEL,
        instructions="You are a precise data analyst. Always use the code interpreter for calculations.",
        tools=[CodeInterpreterTool()],
    ),
)
analyst = project.get_openai_client(agent_name=ANALYST)

sales_csv = """month,region,units,unit_price
2025-01,North,120,19.5
2025-01,South,80,21.0
2025-02,North,135,19.5
2025-02,South,95,20.0
2025-03,North,150,18.9
2025-03,South,70,22.5"""

response = analyst.responses.create(
    input=f"Here is a CSV:\n{sales_csv}\n\nCompute revenue per region per month, the month-over-month growth for "
    "each region, and tell me which region is trending better.",
    tool_choice="required",
)

for item in response.output:
    if item.type == "code_interpreter_call":
        print("── code the agent ran ──\n" + (item.code or ""))
print("\n── answer ──\n" + response.output_text)

# %% [markdown]
# > **Expected output:** a short pandas script followed by a table of revenue figures and a conclusion
# > (North grows steadily; South dips in March).

# %% [markdown]
# ## 2. Function tools — call your own code
#
# A function tool is a **contract**: you describe the function with JSON Schema, the agent decides when to call it
# and with which arguments, and *you* execute it and send back the result. Foundry never sees your code.
#
# We'll build a tiny "order desk" with two functions.

# %%
ORDERS = {
    "A1001": {"status": "shipped", "carrier": "DHL", "eta": "2025-06-12", "items": ["Surface Laptop 7"]},
    "A1002": {"status": "processing", "carrier": None, "eta": None, "items": ["Xbox controller", "USB-C hub"]},
}


def get_order_status(order_id: str) -> dict:
    return ORDERS.get(order_id.upper(), {"error": f"Order {order_id} not found"})


def request_refund(order_id: str, reason: str) -> dict:
    order = ORDERS.get(order_id.upper())
    if not order:
        return {"error": f"Order {order_id} not found"}
    if order["status"] == "shipped":
        return {"accepted": False, "message": "Shipped orders must be returned before a refund."}
    return {"accepted": True, "refund_id": f"R-{order_id[-4:]}", "reason": reason}


LOCAL_FUNCTIONS = {"get_order_status": get_order_status, "request_refund": request_refund}

tools = [
    FunctionTool(
        name="get_order_status",
        description="Look up the shipping status of an order by its ID (e.g. A1001).",
        parameters={
            "type": "object",
            "properties": {"order_id": {"type": "string", "description": "Order ID such as A1001"}},
            "required": ["order_id"],
            "additionalProperties": False,
        },
        strict=True,
    ),
    FunctionTool(
        name="request_refund",
        description="Request a refund for an order. Only call after confirming the order exists.",
        parameters={
            "type": "object",
            "properties": {
                "order_id": {"type": "string"},
                "reason": {"type": "string", "description": "Short reason given by the customer"},
            },
            "required": ["order_id", "reason"],
            "additionalProperties": False,
        },
        strict=True,
    ),
]

DESK = "m3-order-desk"
deploy_agent(
    DESK,
    PromptAgentDefinition(
        model=MODEL,
        instructions="You are a helpful order desk assistant. Use the tools; never invent order data.",
        tools=tools,
    ),
)
desk = project.get_openai_client(agent_name=DESK)

# %% [markdown]
# ### The tool loop
#
# The agent may ask for **several** function calls in one turn, and may need more than one round. This small loop
# keeps going until the agent stops asking for tools.

# %%
from openai.types.responses.response_input_param import FunctionCallOutput


def run_with_tools(client, user_input: str, max_rounds: int = 5) -> str:
    response = client.responses.create(input=user_input)
    for _ in range(max_rounds):
        calls = [item for item in response.output if item.type == "function_call"]
        if not calls:
            return response.output_text
        outputs = []
        for call in calls:
            args = json.loads(call.arguments)
            result = LOCAL_FUNCTIONS[call.name](**args)
            print(f"  🔧 {call.name}({args}) → {result}")
            outputs.append(FunctionCallOutput(type="function_call_output", call_id=call.call_id, output=json.dumps(result)))
        response = client.responses.create(input=outputs, previous_response_id=response.id)
    return response.output_text


print(run_with_tools(desk, "Where are my orders A1001 and A1002?"))

# %%
print(run_with_tools(desk, "Order A1002 is taking too long — I'd like a refund please."))

# %% [markdown]
# > **Expected output:** the first question triggers **two parallel** `get_order_status` calls; the second
# > triggers `get_order_status` and then `request_refund` with a reason extracted from your message.

# %% [markdown]
# ## 3. The same thing with Microsoft Agent Framework
#
# Writing the loop yourself is educational, but [Microsoft Agent Framework](https://aka.ms/agent-framework)
# does it for you: decorate a typed Python function with `@tool` and the framework generates the schema,
# executes calls and feeds results back.

# %%
from typing import Annotated

from agent_framework import Agent, tool
from agent_framework.foundry import FoundryChatClient
from azure.identity.aio import DefaultAzureCredential as AsyncDefaultAzureCredential
from pydantic import Field


@tool(approval_mode="never_require")
def convert_temperature(
    celsius: Annotated[float, Field(description="Temperature in °C")],
) -> str:
    """Convert a Celsius temperature to Fahrenheit."""
    return f"{celsius * 9 / 5 + 32:.1f} °F"


@tool(approval_mode="never_require")
def get_weather(city: Annotated[str, Field(description="City name")]) -> str:
    """Get the current weather for a city (fake data for the workshop)."""
    fake = {"oslo": (5, "cloudy"), "lagos": (31, "sunny"), "seattle": (12, "rain")}
    temp, sky = fake.get(city.lower(), (20, "clear"))
    return f"{temp} °C and {sky}"


async with AsyncDefaultAzureCredential() as async_credential:
    weather_agent = Agent(
        client=FoundryChatClient(project_endpoint=ENDPOINT, model=MODEL, credential=async_credential),
        name="weather-buddy",
        instructions="Answer weather questions using the tools. Reply in one sentence.",
        tools=[get_weather, convert_temperature],
    )
    result = await weather_agent.run("What's the weather in Oslo and Lagos? Give me Fahrenheit please.")
    print(result.text)

# %% [markdown]
# > 💡 **Which should I use?**
# >
# > Use **server-side agents** (`create_version`) when you want a versioned, governed asset that others can call
# > and that shows up in the portal. Use **Agent Framework** when the orchestration lives in your app — you'll
# > combine both in M7.

# %% [markdown]
# ## 4. Clean up

# %%
for name in (ANALYST, DESK):
    project.agents.delete(agent_name=name)
    print("Deleted", name)

# %% [markdown]
# ## 🧪 Your turn
#
# 1. Add a `cancel_order(order_id)` function tool and a rule in the instructions that the agent must confirm
#    with the user before cancelling.
# 2. Ask the analyst to *plot* the revenue trend. Look for a `container_file_citation` annotation in
#    `response.output` — that's the generated PNG.
# 3. Pass `tool_choice="none"` to the desk and see how the agent responds without tools.
#
# ## Recap
#
# * **Code interpreter** = safe, server-side Python for exact answers.
# * **Function tools** = JSON-schema contracts; you run the code and return `function_call_output`.
# * **Agent Framework `@tool`** turns typed Python functions into tools and runs the loop for you.
#
# Next: **[M4 · Grounding with RAG](../04-grounding-rag/)**.
