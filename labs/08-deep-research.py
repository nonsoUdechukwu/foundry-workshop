# %% [markdown]
# # M8 · Deep research
#
# **Goal:** build a small **deep-research agent** — one that plans, searches the web many times, checks its own
# gaps and writes a cited report — from the building blocks you already know.
#
# ```mermaid
# flowchart LR
#   Q[Research question] --> P[Planner<br/>structured output]
#   P -->|sub-questions| S1[Web researcher] & S2[Web researcher] & S3[Web researcher]
#   S1 & S2 & S3 --> N[Notes + sources]
#   N --> G{Gap check}
#   G -- gaps --> S1
#   G -- enough --> W[Writer<br/>cited report]
# ```
#
# The pattern is what matters: **plan → gather in parallel → reflect → synthesise**. The same loop works with
# AI Search (M4), MCP servers (M5) or any other tool in place of web search.

# %%
import os
from concurrent.futures import ThreadPoolExecutor

from azure.ai.projects import AIProjectClient
from azure.ai.projects.models import (
    AgentEndpointConfig,
    FixedRatioVersionSelectionRule,
    PromptAgentDefinition,
    ProtocolConfiguration,
    ResponsesProtocolConfiguration,
    VersionSelector,
    WebSearchTool,
)
from azure.identity import DefaultAzureCredential
from dotenv import find_dotenv, load_dotenv
from pydantic import BaseModel, Field

load_dotenv(find_dotenv(usecwd=True), override=True)

ENDPOINT = os.environ["FOUNDRY_PROJECT_ENDPOINT"]
MODEL = os.environ["FOUNDRY_MODEL_NAME"]

credential = DefaultAzureCredential()
project = AIProjectClient(endpoint=ENDPOINT, credential=credential)
client = project.get_openai_client()

QUESTION = "How are European cities using AI agents in public services today, and what risks are regulators flagging?"

# %% [markdown]
# ## 1. The researcher agent
#
# A Foundry agent with the **web search** tool. It researches *one* sub-question and returns concise notes. The
# web search tool is built in — no extra resource to deploy.

# %%
RESEARCHER = "m8-web-researcher"
version = project.agents.create_version(
    agent_name=RESEARCHER,
    definition=PromptAgentDefinition(
        model=MODEL,
        instructions=(
            "You are a meticulous research assistant. Search the web for the sub-question you are given and return "
            "5-8 factual bullet points with concrete names, dates and numbers. Cite every bullet."
        ),
        tools=[WebSearchTool()],
    ),
)
project.agents.update_details(
    agent_name=RESEARCHER,
    agent_endpoint=AgentEndpointConfig(
        version_selector=VersionSelector(
            version_selection_rules=[FixedRatioVersionSelectionRule(agent_version=version.version, traffic_percentage=100)]
        ),
        protocol_configuration=ProtocolConfiguration(responses=ResponsesProtocolConfiguration()),
    ),
)
researcher = project.get_openai_client(agent_name=RESEARCHER)

# %% [markdown]
# ## 2. Plan
#
# The planner breaks the question into focused sub-questions using **structured output** (M1), so the rest of the
# pipeline can loop over them safely.

# %%
class ResearchPlan(BaseModel):
    sub_questions: list[str] = Field(description="3-4 specific, independently searchable questions")


plan = client.responses.parse(
    model=MODEL,
    instructions="You are a research lead. Break the question into 3-4 non-overlapping, searchable sub-questions.",
    input=QUESTION,
    text_format=ResearchPlan,
).output_parsed

for i, q in enumerate(plan.sub_questions, 1):
    print(f"{i}. {q}")

# %% [markdown]
# ## 3. Gather — in parallel
#
# Each sub-question is researched independently, so we run them concurrently. We keep the notes **and** the
# `url_citation` annotations so the final report can cite real sources.

# %%
def research(sub_question: str) -> dict:
    response = researcher.responses.create(input=sub_question, tool_choice="required")
    sources = {}
    for item in response.output:
        if item.type == "message":
            for part in item.content:
                for ann in getattr(part, "annotations", []) or []:
                    if ann.type == "url_citation":
                        sources[ann.url] = ann.title or ann.url
    return {"question": sub_question, "notes": response.output_text, "sources": sources}


with ThreadPoolExecutor(max_workers=4) as pool:
    findings = list(pool.map(research, plan.sub_questions))

for f in findings:
    print(f"\n### {f['question']}  ({len(f['sources'])} sources)\n{f['notes'][:400]}…")

# %% [markdown]
# ## 4. Reflect — find the gaps
#
# A good researcher checks what's missing before writing. We ask the model to judge the notes and propose at most
# two follow-up searches.

# %%
class GapCheck(BaseModel):
    sufficient: bool
    follow_up_questions: list[str] = Field(default_factory=list, description="0-2 extra searches if needed")


notes_blob = "\n\n".join(f"## {f['question']}\n{f['notes']}" for f in findings)
gaps = client.responses.parse(
    model=MODEL,
    instructions="Judge whether these notes fully answer the research question. If not, propose up to 2 follow-up searches.",
    input=f"Research question: {QUESTION}\n\nNotes:\n{notes_blob}",
    text_format=GapCheck,
).output_parsed
print("Sufficient:", gaps.sufficient, "| follow-ups:", gaps.follow_up_questions)

if gaps.follow_up_questions:
    with ThreadPoolExecutor(max_workers=2) as pool:
        findings += list(pool.map(research, gaps.follow_up_questions[:2]))

# %% [markdown]
# ## 5. Synthesise a cited report

# %%
all_sources = {url: title for f in findings for url, title in f["sources"].items()}
source_list = "\n".join(f"[{i}] {title} — {url}" for i, (url, title) in enumerate(all_sources.items(), 1))
notes_blob = "\n\n".join(f"## {f['question']}\n{f['notes']}" for f in findings)

report = client.responses.create(
    model=MODEL,
    instructions=(
        "Write a crisp research brief in Markdown: an executive summary (3 bullets), sections per theme, and a "
        "'Risks & open questions' section. Cite claims with [n] using ONLY the numbered sources provided. "
        "Do not invent sources."
    ),
    input=f"Question: {QUESTION}\n\nSources:\n{source_list}\n\nNotes:\n{notes_blob}",
)
print(report.output_text)
print("\n---\n" + source_list)

# %% [markdown]
# > 💡 **Going further**
# >
# > For production deep research, consider the **Deep Research** model/tool in the Foundry catalogue (when
# > available in your region) or wrap this pipeline in an Agent Framework **workflow** (M7) so each stage is a
# > checkpointed executor you can trace (M10) and evaluate (M9).
#
# ## 6. Clean up

# %%
project.agents.delete(agent_name=RESEARCHER)
print("Deleted", RESEARCHER)

# %% [markdown]
# ## 🧪 Your turn
#
# 1. Change `QUESTION` to something from your own field and re-run.
# 2. Add a **fact-check** stage: for each executive-summary bullet, ask the researcher to verify it and flag
#    anything unsupported.
# 3. Replace web search with the handbook index from M4 to build an *internal* deep-research assistant.
#
# ## Recap
#
# * Deep research = **plan → parallel gather → reflect → synthesise**.
# * Structured output keeps each stage machine-readable; `url_citation` annotations keep the report honest.
# * The web search tool needs no extra Azure resource.
#
# Next: **[M9 · Evaluation](../09-evaluation/)**.
