# Contributing

Thanks for helping keep this workshop current! Foundry moves fast, so fixes for changed APIs are especially welcome.

## How the repo is organised

| Path | What |
|---|---|
| `labs/*.py` | **Source of truth** for each lab, in [Jupytext](https://jupytext.readthedocs.io/) percent format |
| `docs/modules/*.ipynb` | Notebooks generated from `labs/` and rendered on the site. Don't edit by hand |
| `docs/*.md` | Site pages |
| `infra/` | Bicep for `azd up` |
| `scripts/build_notebooks.py` | Builds (and optionally executes) the notebooks |

## Making a change

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements-dev.txt

# edit labs/NN-*.py, then:
python scripts/build_notebooks.py            # regenerate notebooks
python scripts/build_notebooks.py --execute NN   # run the lab against your own deployment
ruff check labs scripts
mkdocs serve                                 # preview the site
```

CI fails if `docs/modules/` is out of date with `labs/`, if ruff fails, if Bicep doesn't compile or if
`mkdocs build --strict` fails.

## Style

* Each lab: intro → numbered sections → **Expected output** notes → **🧪 Your turn** → **Recap** → **Next**.
* Labs create **and delete** their own resources. Keep it that way.
* Keyless auth only (`DefaultAzureCredential`), no API keys.
* Prefer the stable SDK surface. If you need a preview API, say so in the lab.
* Please run the lab end-to-end before opening a PR and mention the package versions you used.
