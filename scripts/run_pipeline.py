"""
Run the pipeline steps in order.

    python scripts/run_pipeline.py              # every step, 01 to 20
    python scripts/run_pipeline.py 16 20        # steps 16 to 20
    python scripts/run_pipeline.py 7            # only step 07

Each step is an ordinary script, run here as if started on its own. The
run stops at the first step that fails, so later steps never work on
incomplete data.
"""

import runpy
import sys
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parent


def find_steps():
    """{step number: script path} for every NN_*.py file in this folder."""
    return {
        int(path.name[:2]): path
        for path in sorted(SCRIPTS_DIR.glob("[0-9][0-9]_*.py"))
    }


def main(argv):
    steps = find_steps()
    first = int(argv[0]) if argv else min(steps)
    last = int(argv[1]) if len(argv) > 1 else (first if argv else max(steps))

    for number in range(first, last + 1):
        if number not in steps:
            continue

        print(f"\n>>> Step {number:02d}: {steps[number].name}\n")
        runpy.run_path(str(steps[number]), run_name="__main__")

    print(f"\nPipeline finished: steps {first:02d}-{last:02d}.")


if __name__ == "__main__":
    # Steps import common.py from this folder.
    sys.path.insert(0, str(SCRIPTS_DIR))
    main(sys.argv[1:])
