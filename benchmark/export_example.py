"""Export the public 3B9F worked example as a standalone HTML report."""

import argparse
import json
import subprocess
import sys
from pathlib import Path
from tempfile import TemporaryDirectory

from residuetrace.audit import evaluate
from residuetrace.render import render


def worked_example():
    with TemporaryDirectory() as directory:
        root = Path(directory) / "bench"
        subprocess.run([sys.executable, "-I", str(Path(__file__).with_name("evaluate.py")),
                        "prepare", str(root)], check=True)
        index = json.loads((root / "index.json").read_text(encoding="utf-8"))
        for case in index:
            if case["entry"] != "3b9f":
                continue
            report, png, _ = evaluate(root / case["manifest"])
            region, = report["regions"]
            if region["row_key"] == "r17" and region["status"] == "conflict":
                return render(report, png)
    raise ValueError("The documented 3B9F conflict is missing from the benchmark")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path, help="New HTML file (will not overwrite)")
    args = parser.parse_args()
    html = worked_example()
    with args.output.open("x", encoding="utf-8", newline="\n") as f:
        f.write(html)
