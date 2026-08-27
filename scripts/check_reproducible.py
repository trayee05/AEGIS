#!/usr/bin/env python
"""Re-run the committed experiment and prove the scientific columns are stable.

The deterministic composer and hashing sketch encoder exist so that a run is
byte-reproducible across machines (README, "Design decisions worth knowing").
This script turns that claim into a check anyone can run:

  1. read the committed results/results.json,
  2. recover the exact matrix parameters it was produced with,
  3. run it again in this environment,
  4. compare every metric column, ignoring wall-clock timings.

Timings legitimately differ between machines. Nothing else is allowed to.

    python scripts/check_reproducible.py            # check results/
    python scripts/check_reproducible.py --results other/results.json

Exit code 0 means reproduced, 1 means drift, 2 means the file was unusable.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

# Runnable straight from a clone, without `pip install -e .` first.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# Timing fields are environment-dependent by definition.
IGNORED_KEYS = {"wall_seconds", "elapsed", "elapsed_seconds", "oh_wall_seconds"}


def load(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        sys.exit(f"error: {path} not found - run `python -m aegis_care.cli experiment` first")
    except json.JSONDecodeError as exc:
        sys.exit(f"error: {path} is not valid JSON ({exc})")


def parameters_from(committed: dict) -> dict:
    """Recover the matrix parameters from the incidents the run recorded."""
    incidents = committed.get("incidents") or []
    if not incidents:
        sys.exit("error: committed results contain no incidents to reproduce")
    families = sorted({i["family"] for i in incidents})
    depths = sorted({int(i["depth"]) for i in incidents})
    provenance = sorted({i["provenance"] for i in incidents})
    # Incident ids embed the task, so the distinct task count per family is the
    # tasks_per_family the original run used.
    per_family: dict[str, set] = {}
    for inc in incidents:
        per_family.setdefault(inc["family"], set()).add(inc["incident_id"].split("-d")[0])
    tasks_per_family = max((len(v) for v in per_family.values()), default=1)
    return {
        "families": tuple(families),
        "depths": tuple(depths),
        "provenance_conditions": tuple(provenance),
        "tasks_per_family": tasks_per_family,
    }


def strip(value):
    """Drop timing keys anywhere in the structure."""
    if isinstance(value, dict):
        return {k: strip(v) for k, v in value.items() if k not in IGNORED_KEYS}
    if isinstance(value, list):
        return [strip(v) for v in value]
    if isinstance(value, float):
        # Guard against last-bit float formatting differences across platforms.
        return round(value, 9)
    return value


def diff_rows(expected: list, actual: list) -> list[str]:
    problems = []
    if len(expected) != len(actual):
        problems.append(f"row count: committed {len(expected)}, reproduced {len(actual)}")
        return problems
    for exp, act in zip(expected, actual):
        for key in sorted(set(exp) | set(act)):
            if key in IGNORED_KEYS:
                continue
            a, b = strip(exp.get(key)), strip(act.get(key))
            if a != b:
                problems.append(
                    f"{exp.get('incident_id', '?')} condition {exp.get('condition', '?')} "
                    f"{key}: committed {a!r}, reproduced {b!r}")
    return problems


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--results", default="results/results.json",
                        help="the committed results.json to reproduce")
    args = parser.parse_args()

    committed = load(Path(args.results))
    params = parameters_from(committed)

    print(f"Reproducing {args.results}")
    print(f"  families            : {', '.join(params['families'])}")
    print(f"  depths              : {', '.join(str(d) for d in params['depths'])}")
    print(f"  provenance          : {', '.join(params['provenance_conditions'])}")
    print(f"  tasks per family    : {params['tasks_per_family']}")
    print(f"  committed condition runs: {len(committed.get('rows', []))}")
    print()

    from aegis_care.eval.runner import ExperimentRunner

    fresh = ExperimentRunner().run(**params)
    print(f"  reproduced condition runs: {len(fresh['rows'])}")
    print()

    problems = diff_rows(committed.get("rows", []), fresh["rows"])
    for name in ("by_condition", "by_condition_provenance", "oracle_regret"):
        if strip(committed.get(name)) != strip(fresh.get(name)):
            problems.append(f"aggregate `{name}` differs from the committed run")

    if problems:
        print(f"NOT REPRODUCIBLE - {len(problems)} difference(s):")
        for line in problems[:40]:
            print(f"  - {line}")
        if len(problems) > 40:
            print(f"  ... and {len(problems) - 40} more")
        return 1

    committed_wall = committed.get("wall_seconds")
    print("REPRODUCED - every metric column matches the committed run.")
    print(f"  timings differ as expected: committed {committed_wall}s "
          f"vs {fresh['wall_seconds']}s here")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
