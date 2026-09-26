"""Build examples/quickstart.ipynb from examples/quickstart.py, so the two cannot drift.

    python examples/make_notebook.py            # write the notebook (no outputs)
    python examples/make_notebook.py --execute  # also run it; needs BANKPANEL_CALL_ROOT / BANKPANEL_Y9C_ROOT

The script's ``# ---- N. title`` markers become section headings; the module docstring is the
introduction; ``args`` is replaced by a small namespace read from the environment.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

import nbformat

HERE = Path(__file__).resolve().parent
SRC = HERE / "quickstart.py"
NB = HERE / "quickstart.ipynb"

SETUP = '''import os
from pathlib import Path
from types import SimpleNamespace

import pandas as pd

import bankpanel as bp

pd.set_option("display.width", 160)
pd.set_option("display.max_columns", 20)

# Point these at the --out of `bankpanel build` (and `bankpanel expectations build`).
args = SimpleNamespace(
    call_root=os.environ.get("BANKPANEL_CALL_ROOT", "panel_root"),
    y9c_root=os.environ.get("BANKPANEL_Y9C_ROOT", "y9c_root"),
    out=Path("output"),
)
call, y9c = Path(args.call_root), Path(args.y9c_root)
print("bankpanel", bp.__version__, "| Call panel:", call, "| Y-9C panel:", y9c)

COLS = ["assets", "ll_tot", "ll_res", "equity", "dom_deposit_nib", "dom_deposit_ib", "foreign_dep",
        "ytd_int_inc", "ytd_int_exp", "q_int_inc", "q_int_exp"]


def section(title):
    print(title)
'''


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--execute", action="store_true")
    a = ap.parse_args()

    src = SRC.read_text(encoding="utf-8")
    doc = re.match(r'"""(.*?)"""', src, re.S).group(1).strip()
    body = src.split("def main() -> None:", 1)[1].split('if __name__ == "__main__":', 1)[0]
    # drop the argparse preamble: keep from the first section marker
    body = body[body.index("    # ---- 1."):]
    parts = re.split(r"\n    # ---- (\d+)\. (.*?) -+\n", "\n" + body)
    cells = [nbformat.v4.new_markdown_cell("# bankpanel quickstart\n\n" + doc.split("\n", 1)[1].strip()),
             nbformat.v4.new_code_cell(SETUP)]
    for i in range(1, len(parts), 3):
        num, title, code = parts[i], parts[i + 1], parts[i + 2]
        lines = [line[4:] if line.startswith("    ") else line for line in code.rstrip().splitlines()]
        lines = [line for line in lines if not line.startswith("section(")]
        # the notebook shows the figure inline instead of forcing the Agg backend
        lines = [line for line in lines if line not in ("import matplotlib", 'matplotlib.use("Agg")')]
        if "fig.savefig" in code:
            lines.append("fig")
        cells.append(nbformat.v4.new_markdown_cell(f"## {num}. {title}"))
        cells.append(nbformat.v4.new_code_cell("\n".join(lines).strip()))
    nb = nbformat.v4.new_notebook(cells=cells, metadata={"kernelspec": {"name": "python3", "display_name": "Python 3", "language": "python"}})
    if a.execute:
        from nbconvert.preprocessors import ExecutePreprocessor

        ExecutePreprocessor(timeout=1800, kernel_name="python3").preprocess(nb, {"metadata": {"path": str(HERE)}})
    nbformat.write(nb, NB)
    print("wrote", NB, "(executed)" if a.execute else "(not executed)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
