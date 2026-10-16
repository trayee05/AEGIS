#!/usr/bin/env python3
"""Controlled reviewer stress probes; never use these as clinical validation.

The key probes exercise the current in-process trust boundary. The replay probe
changes only prose while holding structured facts fixed. It is a deterministic
perturbation study, not an experiment with a stochastic language model.
"""
from __future__ import annotations

import base64
import json
import math
import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from aegis_care.agents.runtime import DerivationResult
from aegis_care.care.attribution import AttributionEngine
from aegis_care.environment import AegisEnvironment
from aegis_care.util.crypto import KeyRing, canonical_bytes


class ProseOnlyReplay:
    def __init__(self, role, prose: str) -> None:
        self.role = role
        self.prose = prose

    def replay(self, artifact, task, message=None, exclude=None):
        return DerivationResult(
            content=self.prose,
            structured_facts=dict(artifact.structured_facts),
            parent_commitments=[],
            route="controlled_prose_perturbation",
        )


def main() -> None:
    env = AegisEnvironment()
    task = env.tasks[0]
    trajectory = env.run_trajectory(task, depth=3)
    artifact = env.find_artifact(trajectory.nodes[-1].key)
    assert artifact is not None and artifact.replay_recipe is not None
    runtime = env.runtime(artifact.owner)

    payload = {"disposition": "repair", "memory_commitment": artifact.commitment()}
    attacker_with_public_seed = KeyRing(b"public-attacker-test-seed-32bytes!")
    public_seed_forgery_accepted = env.keyring.verify(
        artifact.owner.value, payload,
        attacker_with_public_seed.sign(artifact.owner.value, payload),
    )
    stolen_private_key = env.keyring.identity(artifact.owner.value)._private
    stolen_key_forgery_accepted = env.keyring.verify(
        artifact.owner.value, payload,
        base64.b64encode(stolen_private_key.sign(canonical_bytes(payload))).decode("ascii"),
    )
    process_level_raw_read = bool(runtime.vault.get(artifact.key).content)

    engine = AttributionEngine(env.encoder, env.keyring, env.config.influence)
    rng = random.Random(20261016)
    vocabulary = (
        "window garden copper river orbit ceramic lantern willow "
        "puzzle marble horizon violin cedar orbit textile meadow"
    ).split()
    variants = {"identical": artifact.content,
                "appended_sentence": artifact.content + " Additional review completed.",
                "unrelated_prose": "Unrelated synthetic workflow with different context."}
    for i in range(100):
        variants[f"random_{i:03d}"] = " ".join(rng.choices(vocabulary, k=80))

    reports = {}
    for name, prose in variants.items():
        report = engine.assess(ProseOnlyReplay(artifact.owner, prose), artifact, task, set())
        assert math.isfinite(report.influence_score)
        reports[name] = {
            "semantic_delta": report.semantic_delta,
            "influence_score": report.influence_score,
            "confirmed": report.confirmed,
            "predicate_changed": report.predicate_changed,
        }

    changed = [v for name, v in reports.items() if name != "identical"]
    output = {
        "study_type": "controlled in-process boundary and prose-only replay perturbation",
        "clinical_or_stochastic_model_validation": False,
        "key_and_process_access": {
            "independent_default_roots": (
                KeyRing().public_key_b64("nursing") != KeyRing().public_key_b64("nursing")
            ),
            "public_seed_forgery_accepted": public_seed_forgery_accepted,
            "stolen_key_forgery_accepted": stolen_key_forgery_accepted,
            "process_level_raw_read_possible": process_level_raw_read,
        },
        "prose_only_replay": {
            "artifact_type": artifact.artifact_type.value,
            "changed_variants": len(changed),
            "confirmed_changed_variants": sum(v["confirmed"] for v in changed),
            "max_influence_score": max(v["influence_score"] for v in changed),
            "default_attribution_threshold": env.config.influence.tau_i,
            "structured_facts_held_constant": True,
            "details": reports,
        },
    }
    out_dir = Path("results/reviewer_boundary_stress")
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "results.json").write_text(json.dumps(output, indent=2) + "\n")
    print(json.dumps({
        "key_and_process_access": output["key_and_process_access"],
        "changed_variants": len(changed),
        "confirmed_changed_variants": output["prose_only_replay"]["confirmed_changed_variants"],
        "max_influence_score": output["prose_only_replay"]["max_influence_score"],
    }, indent=2))


if __name__ == "__main__":
    main()
