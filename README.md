# Microsoft Foundry Hands-on Workshop

[![Validate](https://github.com/nonsoUdechukwu/foundry-workshop/actions/workflows/validate.yml/badge.svg)](https://github.com/nonsoUdechukwu/foundry-workshop/actions/workflows/validate.yml)
[![Docs](https://github.com/nonsoUdechukwu/foundry-workshop/actions/workflows/deploy-docs.yml/badge.svg)](https://nonsoudechukwu.github.io/foundry-workshop/)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)

A hands-on workshop for building, evaluating, securing and shipping AI agents with **Microsoft Foundry**: 15 labs
written against the current Foundry SDKs (`azure-ai-projects` 2.x, the Responses API, versioned agents and
Microsoft Agent Framework).

📖 **Workshop site:** <https://nonsoudechukwu.github.io/foundry-workshop/>

## What you'll build

Run it at your own pace, or as an **8-week course** with two labs per session:

| Week | Theme | Labs |
|---|---|---|
| 1 | Foundations | 1 · First inference, 2 · Your first agent |
| 2 | Tools & knowledge | 3 · Tools & function calling, 4 · Grounding with Azure AI Search |
| 3 | Connect & remember | 5 · MCP tools, 6 · Agent memory |
| 4 | Multi-agent | 7 · Multi-agent orchestration, 8 · Deep research |
| 5 | Measure | 9 · Evaluation, 10 · Observability & tracing |
| 6 | Protect | 11 · Guardrails, 12 · Red teaming |
| 7 | Production | 13 · Human-in-the-loop & REST, 14 · Fine-tuning & distillation |
| 8 | Capstone | 15 · Capstone: ship a governed agent |

See the [8-week course plan](https://nonsoudechukwu.github.io/foundry-workshop/eight-week-course/) for pre-reads,
homework and tips on keeping environments between sessions.

## Quick start

[![Open in GitHub Codespaces](https://github.com/codespaces/badge.svg)](https://codespaces.new/nonsoUdechukwu/foundry-workshop)

```bash
az login
azd auth login
azd up                       # deploys Foundry, models, Search, App Insights and writes .env
```

Then open `docs/modules/01-first-inference.ipynb`. Full instructions are on the
[Setup page](https://nonsoudechukwu.github.io/foundry-workshop/setup/).

When you're done: `azd down --purge`.

## Running it with a group?

See the [Facilitator guide](https://nonsoudechukwu.github.io/foundry-workshop/facilitator-guide/).

## Credits

The structure of this workshop was inspired by
[monuminu/foundry-workshop](https://github.com/monuminu/foundry-workshop). This is an independent rewrite: all
content and code here are new, updated for the current Foundry platform.

## Contributing

Issues and PRs welcome. See [CONTRIBUTING.md](CONTRIBUTING.md).

## License

[MIT](LICENSE)
