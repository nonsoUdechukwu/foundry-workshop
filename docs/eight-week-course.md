# 8-week course

A guide for running the workshop over eight weekends: two labs per session, finishing with the capstone in
week 8. Use it as it is or adapt it for your group. Lab numbers (M1–M15) match the rest of the site.

| Week | Theme | Labs | Start this first (runs in the background) |
|---|---|---|---|
| 1 | Foundations | Setup, [platform primer](platform/01-what-is-foundry.md), [M1](modules/01-first-inference.ipynb), [M2](modules/02-your-first-agent.ipynb) | `azd up` |
| 2 | Tools & knowledge | [M3](modules/03-tools-and-function-calling.ipynb), [M4](modules/04-grounding-rag.ipynb) | — |
| 3 | Connect & remember | [M5](modules/05-mcp-tools.ipynb), [M6](modules/06-agent-memory.ipynb) | — |
| 4 | Multi-agent | [M7](modules/07-multi-agent-orchestration.ipynb), [M8](modules/08-deep-research.ipynb) | M8 research run |
| 5 | Measure | [M9](modules/09-evaluation.ipynb), [M10](modules/10-observability-tracing.ipynb) | M9 evaluation runs |
| 6 | Protect | [M11](modules/11-guardrails.ipynb), [M12](modules/12-red-teaming.ipynb) | M12 red-team run |
| 7 | Production | [M13](modules/13-human-in-the-loop-and-rest.ipynb), [M14](modules/14-fine-tuning-distillation.ipynb) | M14 fine-tuning job |
| 8 | Capstone | [M15](modules/15-capstone.ipynb) and show-and-tell | — |

## Week by week

### Week 1 · Foundations

- **Pre-read:** [Concepts](concepts.md) and [What is Foundry](platform/01-what-is-foundry.md).
- **In session:** everyone runs `azd up` (or receives a pre-provisioned `.env`), then works through **M1** and **M2**.
  Most first-week problems are with roles, quota and region, so keep [Troubleshooting](troubleshooting.md) open.
- **Homework:** the 🧪 *Your turn* exercises in M1 and M2.

### Week 2 · Tools & knowledge

- **Pre-read:** [Architecture & projects](platform/02-architecture-and-projects.md).
- **In session:** **M3** (code interpreter and function calling), then **M4** (Azure AI Search grounding).
- **Keep:** the `contoso-handbook` index from M4, because the week 8 capstone reuses it.
- **Homework:** add a new policy document to the M4 data and ask the agent about it.

### Week 3 · Connect & remember

- **In session:** **M5** (remote MCP servers and approvals) and **M6** (long-term memory).
- **Homework:** connect an MCP server you use at work (M5 *Your turn* #2).

### Week 4 · Multi-agent

- **In session:** start the **M8** deep-research run first, then teach **M7** while it runs. Come back to M8's
  report at the end of the session.
- **Homework:** M7 *Your turn* #3, a critic loop in a declarative workflow.

### Week 5 · Measure

- **In session:** start the **M9** evaluation runs, explain graders while they score, then move on to **M10**
  tracing.
- **Between sessions:** M10's continuous-evaluation results lag. Ask attendees to check them during the week.
- **Homework:** the M10 KQL cost query (*Your turn* #2).

### Week 6 · Protect

- **Pre-read:** [Control plane & governance](platform/03-control-plane-and-governance.md).
- **In session:** start the **M12** red-team scan first (it runs hundreds of attack conversations), then teach
  **M11** guardrails. Review the red-team scorecard together at the end.
- **Homework:** M12 *Your turn* #1. Re-scan with the M11 guardrail attached and compare the results.

### Week 7 · Production

- **In session:** submit the **M14** fine-tuning job first, then teach **M13** human-in-the-loop and the REST API.
- **Between sessions:** the M14 job queues and trains for a while. Ask attendees to finish M14's deploy and compare
  cells during the week, or show results from a job you ran in advance.
- **Optional:** M14 needs fine-tuning quota. If your attendees don't have it, demo it instead.

### Week 8 · Capstone

- **In session:** **M15** brings together grounding, tools, approvals, guardrails, memory and an evaluation gate
  in a single agent. Finish with show-and-tell: each attendee presents one change they made and its eval score.
- **Afterwards:** everyone runs [cleanup](cleanup.md).

## Keeping environments between weekends

Model deployments bill per token, but **Azure AI Search** and any **fine-tuned deployment** bill for as long as
they exist. Choose one approach:

| Approach | How | Trade-off |
|---|---|---|
| **Keep it running** | Deploy in week 1 and run `azd down --purge` after week 8 | Simplest. Search bills for all eight weeks |
| **Tear down weekly** | Run `azd down --purge` after each session and `azd up` before the next | Cheapest. Re-run M4 sections 1–3 before week 8 so the capstone finds its index |

Whichever you choose, delete the M14 fine-tuned deployment once week 7's homework is done.

## Tips for a multi-week cohort

- **Recap first.** Open each session by asking someone to show their homework.
- **Labs are independent after M1.** Anyone who misses a week can catch up alone. Only M15 depends on an
  earlier lab (M4).
- **Rendered notebooks show expected output.** Attendees can review a missed week before the next session.
- See the [facilitator guide](facilitator-guide.md) for environment options and pre-requisites.
