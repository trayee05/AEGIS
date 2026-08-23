"""External-format validation on public synthetic FHIR R4 data."""
from __future__ import annotations

import copy
from dataclasses import replace
from pathlib import Path
from typing import Any, Callable, Dict, Optional, Sequence

from ..care.coordinator import RecoveryCoordinator
from ..config import CONFIG
from ..environment import AegisEnvironment
from ..fhir.loader import load_fhir_sources
from ..fhir.store import FHIRStore
from ..incident.scenarios import FAMILIES, ScenarioBuilder
from .evidence import verify_evidence_manifest, write_evidence_manifest
from .privacy import PrivacyAuditor
from .report import build_report, make_figures
from .runner import ExperimentRunner


SYNTHEA_REPOSITORY = "https://github.com/synthetichealth/synthea-sample-data"
SYNTHEA_PROJECT = "https://github.com/synthetichealth/synthea"


LIMITATIONS = [
    "All records are synthetic Synthea records; no real patient data or clinical outcomes are used.",
    "The deterministic clinical composer validates recovery mechanics, not open-ended LLM behaviour.",
    "The external run validates FHIR R4 shape and source independence, not hospital workflow integration.",
    "Family F3 adds a deterministic restricted-field incident overlay because Synthea does not encode the study's local role policy.",
    "Thresholds remain those frozen in the proposal; this run is not a prospective clinical study.",
]


def _external_report(load_report: Dict[str, Any], results: Dict[str, Any],
                     verification: Dict[str, Any], out_dir: Path) -> Path:
    rows = {row["condition"]: row for row in results.get("by_condition", [])}
    care = rows.get("I", {})
    lineage = rows.get("E", {})
    reset = rows.get("C", {})
    lines = [
        "# AEGIS-Care external-format validation",
        "",
        "> Evidence tier: **external-format mechanism validation on fully synthetic data**. ",
        "> This is not clinical validation and makes no patient-outcome claim.",
        "",
        "## Why this run exists",
        "",
        "The original benchmark used AEGIS's own deterministic FHIR generator. This run instead ",
        "loads public Synthea FHIR R4 transaction bundles, normalises their native references, ",
        "constructs the same role-separated contamination incidents, and evaluates every recovery ",
        "condition on paired snapshots. It tests whether the mechanism survives a different record ",
        "generator and realistic US Core resource shapes.",
        "",
        "## Data provenance and compatibility",
        "",
        f"- Source: [Synthea public sample-data repository]({SYNTHEA_REPOSITORY})",
        f"- Generator: [Synthea synthetic patient simulator]({SYNTHEA_PROJECT})",
        f"- Patient bundles loaded: **{load_report.get('patients_loaded', 0)}**",
        f"- FHIR bundles scanned / loaded: **{load_report.get('bundles_seen', 0)} / {load_report.get('bundles_loaded', 0)}**",
        f"- Resources loaded: `{load_report.get('resources_loaded', {})}`",
        f"- Intra-bundle references rewritten: **{load_report.get('references_rewritten', 0)}**",
        f"- Unresolved UUID references retained: **{load_report.get('unresolved_urn_references', 0)}**",
        f"- Input SHA-256: `{load_report.get('source_sha256', {})}`",
        "",
        "## Paired recovery result",
        "",
        f"The run completed **{len(results.get('rows', []))} condition runs across {len(results.get('incidents', []))} incidents** in {results.get('wall_seconds')} seconds.",
        "",
        "| Condition | RWH | Recall | Precision | BSR | RTS | UER | DRR |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for condition in ("A", "B", "C", "D", "E", "F", "G", "H", "I"):
        row = rows.get(condition)
        if not row:
            continue
        lines.append(
            f"| {condition} | {row['rwh']:.4f} | {row['descendant_recall']:.4f} | "
            f"{row['descendant_precision']:.4f} | {row['bsr']:.4f} | {row['rts']:.4f} | "
            f"{row['uer']:.4f} | {row['drr']:.4f} |"
        )
    lines.extend([
        "",
        "### Decision reading",
        "",
        f"- Full CARE residual harm: **{care.get('rwh', 'n/a')}**; descendant recall: **{care.get('descendant_recall', 'n/a')}**; benign-state retention: **{care.get('bsr', 'n/a')}**.",
        f"- Explicit-lineage replay residual harm: **{lineage.get('rwh', 'n/a')}**; recall: **{lineage.get('descendant_recall', 'n/a')}**.",
        f"- Full-reset benign-state retention: **{reset.get('bsr', 'n/a')}**.",
        f"- Verification failures: **{len(results.get('verification_failures', []))}**.",
        f"- Evidence-manifest integrity: **{'PASS' if verification.get('valid') else 'FAIL'}** ({verification.get('artifacts_checked', 0)} artifacts checked).",
        "",
        "These values show mechanism behaviour in a deterministic synthetic study. They do not ",
        "estimate effectiveness, safety, or utility in a hospital.",
        "",
        "## Limitations and next validation gate",
        "",
    ])
    lines.extend(f"- {item}" for item in LIMITATIONS)
    lines.extend([
        "",
        "The next evidence gate is a container-pinned MedAgentBench run with held-out task templates ",
        "and at least one open-weight model, followed by clinician review of every positive label and ",
        "hard negative. Live EHR evaluation would require institutional governance and a separate protocol.",
        "",
    ])
    path = out_dir / "EXTERNAL_VALIDATION.md"
    path.write_text("\n".join(lines), encoding="utf-8")
    return path


def run_external_validation(
    sources: Sequence[Path | str],
    *,
    out_dir: Path,
    max_patients: int = 10,
    model_spec: Optional[str] = None,
    progress: Optional[Callable[[str], None]] = None,
) -> Dict[str, Any]:
    """Run all nine recovery conditions on public-format synthetic records."""
    resources, report = load_fhir_sources(sources, max_patients=max_patients)
    source_info = report.to_dict()
    config = replace(
        CONFIG,
        n_patients=report.patients_loaded,
        n_base_tasks=9,
    )

    def environment_factory() -> AegisEnvironment:
        store = FHIRStore(
            resources=copy.deepcopy(resources),
            source_info=copy.deepcopy(source_info),
        )
        return AegisEnvironment(config=config, model_spec=model_spec, fhir_store=store)

    runner = ExperimentRunner(
        config=config,
        model_spec=model_spec,
        progress=progress,
        environment_factory=environment_factory,
        data_source=source_info,
    )
    results = runner.run(
        families=FAMILIES,
        depths=(4,),
        provenance_conditions=("complete", "random40", "targeted"),
        tasks_per_family=1,
        n_controls=1,
        seeds=(0,),
    )
    results["external_validation"] = source_info

    privacy = None
    try:
        env = environment_factory()
        incident = ScenarioBuilder(env).build("F1", env.tasks[0], depth=4, n_controls=1)
        recovery = RecoveryCoordinator(env).recover(incident.incident_id, [incident.seed_key])
        privacy = PrivacyAuditor(env).full_audit(incident, recovery.capsules)
        results["privacy"] = privacy
    except Exception as exc:  # reported, never silently promoted to a pass
        results["privacy_error"] = str(exc)

    out_dir = Path(out_dir).resolve()
    ExperimentRunner.save(results, out_dir)
    build_report(results, privacy=privacy, out_dir=out_dir)
    figures = make_figures(results, out_dir)

    provisional = {"valid": True, "artifacts_checked": 0, "failures": []}
    external_report = _external_report(source_info, results, provisional, out_dir)
    evidence_files = [
        out_dir / "results.json", out_dir / "metrics.csv", out_dir / "report.md",
        external_report, *figures,
    ]
    manifest = write_evidence_manifest(
        out_dir,
        results=results,
        data_source=source_info,
        evidence_files=evidence_files,
        command=(
            "python -m aegis_care.cli external-validate --fhir <path> "
            f"--limit-patients {max_patients} --out {out_dir}"
        ),
        limitations=LIMITATIONS,
        verification={
            "loader_validation_errors": report.validation_errors,
            "experiment_verification_failures": results.get("verification_failures", []),
        },
    )
    verification = verify_evidence_manifest(manifest)
    # Rebuild the human report with the now-measured manifest status, then
    # refresh its bound digest and verify one final time.
    _external_report(source_info, results, verification, out_dir)
    manifest = write_evidence_manifest(
        out_dir,
        results=results,
        data_source=source_info,
        evidence_files=evidence_files,
        command=(
            "python -m aegis_care.cli external-validate --fhir <path> "
            f"--limit-patients {max_patients} --out {out_dir}"
        ),
        limitations=LIMITATIONS,
        verification={
            "loader_validation_errors": report.validation_errors,
            "experiment_verification_failures": results.get("verification_failures", []),
        },
    )
    results["manifest"] = str(manifest)
    results["manifest_verification"] = verify_evidence_manifest(manifest)
    return results


__all__ = ["run_external_validation", "LIMITATIONS"]
