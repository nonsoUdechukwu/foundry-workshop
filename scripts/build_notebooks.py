"""Build docs/modules/*.ipynb from the Jupytext sources in labs/.

Usage:
    python scripts/build_notebooks.py           # (re)generate notebooks
    python scripts/build_notebooks.py --check   # fail if notebooks are out of date (used in CI)
    python scripts/build_notebooks.py --execute 01 02   # also run the selected labs against your project
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

import jupytext
import nbformat

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "labs"
OUT = ROOT / "docs" / "modules"

KERNEL = {
    "kernelspec": {"display_name": "Python 3", "language": "python", "name": "python3"},
    "language_info": {"name": "python"},
}


def build(path: Path) -> nbformat.NotebookNode:
    nb = jupytext.read(path, fmt="py:percent")
    nb.metadata = dict(KERNEL)
    for index, cell in enumerate(nb.cells):
        cell.id = f"cell-{index:03d}"  # stable ids keep `--check` deterministic
        cell.metadata = {}
        if cell.cell_type == "code":
            cell.outputs = []
            cell.execution_count = None
    return nb


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--execute", nargs="*", metavar="PREFIX", help="lab number prefixes to execute")
    args = parser.parse_args()

    OUT.mkdir(parents=True, exist_ok=True)
    stale: list[str] = []
    for src in sorted(SRC.glob("*.py")):
        target = OUT / f"{src.stem}.ipynb"
        rendered = nbformat.writes(build(src)) + "\n"
        if args.check:
            if not target.exists() or target.read_text(encoding="utf-8") != rendered:
                stale.append(target.name)
            continue
        target.write_text(rendered, encoding="utf-8")
        print(f"built {target.relative_to(ROOT)}")

    if args.check and stale:
        print("Out of date — run `python scripts/build_notebooks.py`:", *stale, sep="\n  ")
        return 1

    if args.execute is not None:
        from nbclient import NotebookClient

        prefixes = args.execute or [p.stem[:2] for p in sorted(SRC.glob("*.py"))]
        failed = []
        for src in sorted(SRC.glob("*.py")):
            if src.stem[:2] not in prefixes:
                continue
            print(f"\n=== executing {src.stem}", flush=True)
            nb = build(src)
            try:
                NotebookClient(nb, timeout=int(os.getenv("NB_CELL_TIMEOUT", "1800")), kernel_name="python3", resources={"metadata": {"path": str(ROOT)}}).execute()
                print(f"=== {src.stem}: OK")
            except Exception as exc:  # noqa: BLE001
                failed.append(src.stem)
                print(f"=== {src.stem}: FAILED\n{exc}")
            finally:
                executed_dir = ROOT / ".executed"
                executed_dir.mkdir(exist_ok=True)
                nbformat.write(nb, executed_dir / f"{src.stem}.ipynb")
        if failed:
            print("\nFailed labs:", ", ".join(failed))
            return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
