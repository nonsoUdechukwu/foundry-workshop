# Microsoft Foundry Hands-on Workshop

[![Validate](https://github.com/nonsoUdechukwu/foundry-workshop/actions/workflows/validate.yml/badge.svg)](https://github.com/nonsoUdechukwu/foundry-workshop/actions/workflows/validate.yml)
[![Docs](https://github.com/nonsoUdechukwu/foundry-workshop/actions/workflows/deploy-docs.yml/badge.svg)](https://nonsoudechukwu.github.io/foundry-workshop/)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)

A hands-on workshop for building, evaluating, securing and shipping AI agents with **Microsoft Foundry**: 15 labs
written against the current Foundry SDKs (`azure-ai-projects` 2.x, the Responses API, versioned agents and
Microsoft Agent Framework).

📖 **Workshop site:** <https://nonsoudechukwu.github.io/foundry-workshop/>

## What you'll build

| # | Lab | # | Lab |
|---|---|---|---|
| 1 | First inference | 9 | Evaluation |
| 2 | Your first agent | 10 | Observability & tracing |
| 3 | Tools & function calling | 11 | Guardrails |
| 4 | Grounding with Azure AI Search | 12 | Red teaming |
| 5 | MCP tools | 13 | Human-in-the-loop & REST |
| 6 | Agent memory | 14 | Fine-tuning & distillation |
| 7 | Multi-agent orchestration | 15 | Capstone: ship a governed agent |
| 8 | Deep research | | |

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
