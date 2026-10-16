"""Post-review exploratory sensitivity sweep; never overwrites committed results."""
from __future__ import annotations

import argparse
import csv
import json
import sys
from dataclasses import replace
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from aegis_care.config import CONFIG
from aegis_care.eval.runner import ExperimentRunner


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", default="results/revision_sensitivity")
    parser.add_argument("--seeds", type=int, nargs="+", default=[0, 1],
                        help="task-selection seeds; these do not control model sampling")
    parser.add_argument("--provenance", nargs="+", default=["random40", "targeted"])
    args = parser.parse_args()
    output = Path(args.output)
    output.mkdir(parents=True, exist_ok=True)
    c, i, r = CONFIG.candidate, CONFIG.influence, CONFIG.repair
    variants = {
        "default": CONFIG,
        "candidate_similarity_high": replace(CONFIG, candidate=replace(c, b_similarity=0.54, c_patient=0.26)),
        "candidate_patient_high": replace(CONFIG, candidate=replace(c, b_similarity=0.14, c_patient=0.66)),
        "candidate_resource_high": replace(CONFIG, candidate=replace(c, b_similarity=0.24, c_patient=0.36, d_resource=0.40)),
        "candidate_threshold_low": replace(CONFIG, candidate=replace(c, tau_c=0.30)),
        "candidate_threshold_high": replace(CONFIG, candidate=replace(c, tau_c=0.55)),
        "candidate_cap_8": replace(CONFIG, candidate=replace(c, max_candidates=8)),
        "attribution_semantic_high": replace(CONFIG, influence=replace(i, w1_semantic=0.54, w2_patient=0.26)),
        "attribution_threshold_high": replace(CONFIG, influence=replace(i, tau_i=0.45)),
        "repair_cutoff_high": replace(CONFIG, repair=replace(r, tau_r=0.90)),
    }
    planned_cells = len(ExperimentRunner.plan(
        depths=(3, 4), provenance_conditions=tuple(args.provenance),
        tasks_per_family=1, seeds=tuple(args.seeds)))
    summary = []
    for name, config in variants.items():
        result = ExperimentRunner(config).run(
            depths=(3, 4),
            provenance_conditions=tuple(args.provenance),
            conditions=("I",),
            tasks_per_family=1,
            seeds=tuple(args.seeds),
        )
        rows = result["rows"]
        aggregate = result["by_condition"][0] if result["by_condition"] else {}
        summary.append({
            "variant": name,
            "planned_cells": planned_cells,
            "completed_incidents": len(result["incidents"]),
            "condition_rows": len(rows),
            "verification_failures": len(result["verification_failures"]),
            "wall_seconds": result["wall_seconds"],
            "recall": aggregate.get("descendant_recall"),
            "precision": aggregate.get("descendant_precision"),
            "bsr": aggregate.get("bsr"),
            "rwh": aggregate.get("rwh"),
            "uer": aggregate.get("uer"),
            "drr": aggregate.get("drr"),
        })
        (output / f"{name}.json").write_text(json.dumps({
            "rows": rows,
            "incidents": result["incidents"],
            "verification_failures": result["verification_failures"],
            "config": result["config"],
        }, indent=2, default=str))
        print(name, summary[-1], flush=True)
    with (output / "summary.csv").open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=summary[0])
        writer.writeheader()
        writer.writerows(summary)


if __name__ == "__main__":
    main()
