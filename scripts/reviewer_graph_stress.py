#!/usr/bin/env python3
"""Controlled branched-graph stress study for the reviewer response.

One wrong-patient registration seed fans out into independently scheduled
lookup, handover, summary, and aggregate artifacts. Each branch has a distinct
task/cache key. Stages are interleaved across branches. This tests a larger
one-to-many DAG, not concurrent processes or multi-parent joins.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from aegis_care.agents.runtime import AgentMessage
from aegis_care.environment import AegisEnvironment, TrajectoryNode
from aegis_care.eval.baselines import BaselineRunner
from aegis_care.eval.metrics import MetricsEvaluator
from aegis_care.incident.masks import ProvenanceMask
from aegis_care.incident.scenarios import ScenarioBuilder
from aegis_care.incident.tasks import CHAIN, purpose_for_role


def build(env: AegisEnvironment, fanout: int):
    task = next(t for t in env.tasks if t["family"] == "labs")
    incident = ScenarioBuilder(env).build(
        "F1", task, incident_id=f"GRAPH-F1-{fanout}", depth=0, n_controls=0)
    seed = env.find_artifact(incident.seed_key)
    assert seed is not None
    parents = [seed for _ in range(fanout)]
    branch_tasks = []
    siblings = [t for t in env.tasks if t["family"] == task["family"]
                and t["task_id"] != task["task_id"]]
    for branch in range(fanout):
        control_task = dict(siblings[branch % len(siblings)])
        control_task["task_id"] = f"{control_task['task_id']}-CTL{branch:02d}"
        env.tasks.append(control_task)
        control = env.run_trajectory(control_task, depth=4, is_control=True)
        incident.controls.append(control)
        incident.clean_keys.update(control.node_keys())

    # Stage-major order interleaves branch writes without real concurrency.
    for step, (role, kind) in enumerate(CHAIN[1:], start=1):
        next_parents = []
        for branch, parent in enumerate(parents):
            branch_task = dict(task)
            branch_task["task_id"] = f"{task['task_id']}-BR{branch:02d}"
            branch_task["purpose"] = purpose_for_role(role, branch_task)
            if not any(t["task_id"] == branch_task["task_id"] for t in env.tasks):
                env.tasks.append(dict(branch_task))
                branch_tasks.append(dict(branch_task))
            pid = parent.structured_facts["patient_id"]
            msg = AgentMessage(
                from_role=parent.owner, to_role=role, patient_id=pid,
                patient_display=env.fhir.patient_display(pid),
                mrn=env.fhir.patient_mrn(pid),
                source_commitment=parent.commitment(),
            )
            rt = env.runtime(role)
            result = rt.derive(kind, branch_task, msg)
            artifact = rt.write_memory(
                f"GRAPH-{fanout}-BR{branch:02d}-{kind.value}",
                kind, result, branch_task,
                session_id=f"GRAPH-{step}-{branch}",
                true_parents=[parent.commitment()],
            )
            node = TrajectoryNode(
                key=artifact.key, role=role, artifact_type=kind, depth=step,
                true_parent_keys=[parent.key], true_patient=pid,
                intended_patient=task["patient_id"], contaminated=True,
            )
            env.truth.add_node(node)
            incident.contaminated.nodes.append(node)
            incident.true_contaminated.add(node.key)
            next_parents.append(artifact)
        parents = next_parents
    incident.depth = 4
    incident.notes["branch_tasks"] = branch_tasks
    return incident


def run(fanout: int, mask: str) -> dict:
    env = AegisEnvironment()
    incident = build(env, fanout)
    mask_result = ProvenanceMask(env, seed=20261016).apply(mask, incident.all_keys())
    snapshot = env.snapshot()
    rows = []
    followups = [incident.task] + incident.notes["branch_tasks"]
    for condition in ("D", "I"):
        env.restore(snapshot)
        outcome = BaselineRunner(env).run(condition, incident, followup_tasks=followups)
        metrics = MetricsEvaluator(env).evaluate(
            outcome, incident, provenance=mask,
            edge_loss=mask_result.loss_fraction, followup_tasks=followups)
        rows.append({
            "condition": condition,
            "recall": metrics.descendant_recall,
            "precision": metrics.descendant_precision,
            "benign_retention": metrics.bsr,
            "repaired_task_success": metrics.rts,
            "rwh": metrics.rwh,
            "confirmed": len(outcome.recovery.confirmed),
            "repaired": len(outcome.recovery.repaired),
            "quarantined": len(outcome.recovery.quarantined),
            "rounds": outcome.recovery.rounds,
            "closure": outcome.recovery.closure_reached,
            "candidates": len(outcome.recovery.candidates_considered),
            "replays": outcome.overhead.get("replays", 0),
            "wrong_followups": metrics.counts["wrong_followups"],
            "followups": metrics.counts["followups"],
        })
    return {
        "fanout": fanout, "graph_nodes": env.truth.stats()["nodes"],
        "graph_edges": env.truth.stats()["edges"],
        "contaminated_descendants": len(incident.true_contaminated),
        "clean_control_artifacts": len(incident.clean_keys),
        "mask": mask, "edges_before": mask_result.edges_before,
        "edges_removed": mask_result.edges_removed,
        "conditions": rows,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--fanouts", nargs="+", type=int, default=[4, 8, 16])
    parser.add_argument("--masks", nargs="+", default=["complete", "random40", "targeted"])
    args = parser.parse_args()
    rows = [run(f, m) for f in args.fanouts for m in args.masks]
    result = {
        "design": "deterministic in-process one-to-many DAG with interleaved stages; no concurrent execution or multi-parent joins",
        "seed": 20261016, "rows": rows,
    }
    out = Path("results/reviewer_graph_stress/results.json")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(rows, indent=2))


if __name__ == "__main__":
    main()
