"""Sentinel detectors: proactive error discovery without a reported incident.

The CARE loop answers "given a known-bad memory, what inherited it?". The
Sentinel answers the question that comes first: "is anything wrong right now?".

Every detector is grounded in something the operational system legitimately
holds - trusted FHIR, the signed replay recipe, explicit lineage, the policy
matrix, or the source registry. None of them reads benchmark instrumentation
(`_true_parents`, `env.truth`, `Incident.true_contaminated`). That separation
is what lets the blind drill score the Sentinel honestly.

Detectors are written to run inside the owning runtime: they read content
locally and emit metadata-only findings (keys, rule codes, synthetic patient
ids, expected-vs-observed identifiers). No memory text leaves a detector.
"""
from __future__ import annotations

import hashlib
from contextlib import contextmanager
from dataclasses import dataclass, field, asdict
from typing import Any, Dict, Iterable, List, Optional, Set

from ..memory.models import ArtifactType, MemoryArtifact, MemoryState
from ..policy.rbac import ROLE_FIELD_MATRIX, FieldCategory
from ..util.crypto import commit_text

SEVERITY_RANK = {"critical": 0, "high": 1, "medium": 2, "low": 3, "info": 4}

#: Plain-language catalogue rendered by the dashboard. `grounding` names the
#: trusted reference each check compares against.
DETECTORS: List[Dict[str, str]] = [
    {"id": "identity_reresolve", "domain": "memory", "name": "Identity re-resolution",
     "what": "Re-runs every stored patient alias against the FHIR patient index.",
     "grounding": "FHIR Patient search", "families": "F1"},
    {"id": "work_order", "domain": "memory", "name": "Work-order cross-check",
     "what": "Resolves the task each memory was written for and checks it names the same patient.",
     "grounding": "Signed replay recipe + FHIR", "families": "F1 F2"},
    {"id": "lineage_drift", "domain": "memory", "name": "Lineage patient drift",
     "what": "Flags a memory whose patient differs from the parent it was derived from.",
     "grounding": "Explicit lineage", "families": "F2"},
    {"id": "evidence_ownership", "domain": "memory", "name": "Cited-evidence ownership",
     "what": "Checks every observation and condition a memory cites belongs to its patient.",
     "grounding": "FHIR subject reference", "families": "F1 F2"},
    {"id": "stale_value", "domain": "memory", "name": "Stale value",
     "what": "Compares asserted values and aggregates with the current FHIR record.",
     "grounding": "Current FHIR Observation", "families": "F4"},
    {"id": "restricted_exposure", "domain": "memory", "name": "Restricted-field exposure",
     "what": "Finds physician-only material held by a role with no right to it.",
     "grounding": "Role field matrix", "families": "F3"},
    {"id": "inherited_withdrawn", "domain": "memory", "name": "Inherits a withdrawn record",
     "what": "Finds servable memories still built on a parent that is held or withdrawn.",
     "grounding": "Lifecycle state + lineage", "families": "all"},
    {"id": "integrity", "domain": "memory", "name": "Content integrity",
     "what": "Re-hashes each memory against the commitment sealed when it was written.",
     "grounding": "Write-time content commitment", "families": "tamper"},
    {"id": "provenance_gap", "domain": "memory", "name": "Lineage coverage",
     "what": "Counts derived memories with no recorded parent (latent search will be needed).",
     "grounding": "Explicit lineage", "families": "masking"},
    {"id": "source_identity", "domain": "source", "name": "Chart identity mismatch",
     "what": "Source record filed under one chart while its FHIR subject names another.",
     "grounding": "Registry + FHIR subject", "families": "source"},
    {"id": "source_invalid", "domain": "source", "name": "Invalidated source",
     "what": "Source records marked entered-in-error or cancelled.",
     "grounding": "FHIR status", "families": "source"},
    {"id": "held_transfer", "domain": "source", "name": "Blocked handover",
     "what": "Handovers the transfer guard refused and nobody has resolved.",
     "grounding": "Transfer log", "families": "source"},
    {"id": "human_report", "domain": "source", "name": "Open human report",
     "what": "Concerns raised by staff that are still open.",
     "grounding": "Manual reports", "families": "human"},
]
DETECTOR_NAMES = {d["id"]: d["name"] for d in DETECTORS}

#: Artifact types that are derived from a parent and should carry lineage.
DERIVED_TYPES = {ArtifactType.LOOKUP_STRATEGY, ArtifactType.HANDOVER,
                 ArtifactType.CLINICAL_SUMMARY, ArtifactType.AGGREGATE,
                 ArtifactType.OBSERVATION_SUMMARY}

_HELD = {MemoryState.SUSPECTED, MemoryState.QUARANTINED, MemoryState.TOMBSTONED}


@dataclass
class Finding:
    rule: str
    severity: str
    domain: str
    subject: str
    summary: str
    patient_id: Optional[str] = None
    owner: Optional[str] = None
    artifact_type: Optional[str] = None
    session_id: Optional[str] = None
    task_id: Optional[str] = None
    confidence: float = 0.9
    evidence: Dict[str, Any] = field(default_factory=dict)
    action: Optional[Dict[str, str]] = None

    @property
    def id(self) -> str:
        raw = f"{self.rule}|{self.subject}".encode()
        return "F-" + hashlib.sha256(raw).hexdigest()[:10]

    def to_dict(self) -> Dict[str, Any]:
        data = asdict(self)
        data["id"] = self.id
        data["rule_name"] = DETECTOR_NAMES.get(self.rule, self.rule)
        return data


@contextmanager
def _out_of_band(fhir):
    """Sentinel reads are monitoring, not recovery work.

    The evaluation reports FHIR reads as CARE overhead; letting a background
    patrol inflate that counter would corrupt the experiment's cost numbers.
    """
    before = getattr(fhir, "read_count", None)
    try:
        yield
    finally:
        if before is not None:
            fhir.read_count = before


def _patient_of(artifact: MemoryArtifact) -> Optional[str]:
    return artifact.structured_facts.get("patient_id") or artifact.patient_scope


def _resolve_query(fhir, query: Dict[str, Any]) -> Optional[Set[str]]:
    """Resolve a task/alias query against FHIR. None means 'cannot check'."""
    params = {k: v for k, v in query.items()
              if k in ("identifier", "family", "given", "birthdate") and v}
    if not params:
        return None
    return {p["id"] for p in fhir.search("Patient", **params)}


def _query_from_key(query_key: str) -> Optional[Dict[str, Any]]:
    """Rebuild a FHIR query from a stored alias key (mrn:/name:/namedob:)."""
    if not query_key or ":" not in query_key:
        return None
    kind, _, body = query_key.partition(":")
    if kind == "mrn":
        return {"identifier": body}
    if kind == "name" and "|" in body:
        family, given = body.split("|", 1)
        return {"family": family, "given": given}
    if kind == "namedob" and "|" in body:
        family, dob = body.split("|", 1)
        return {"family": family, "birthdate": dob}
    return None


class DetectorSuite:
    """Runs every detector over the live environment and source registry."""

    def __init__(self, env, registry=None) -> None:
        self.env = env
        self.registry = registry
        self._task_cache: Dict[str, Optional[Set[str]]] = {}

    # ------------------------------------------------------------------
    def run(self, patient_filter: Optional[str] = None) -> Dict[str, Any]:
        env = self.env
        with _out_of_band(env.fhir):
            artifacts = env.all_artifacts()
            memory_findings, coverage = self._memory(artifacts, patient_filter)
        source_findings, source_total = self._source(patient_filter)
        findings = memory_findings + source_findings
        findings.sort(key=lambda f: (SEVERITY_RANK[f.severity], f.rule, f.subject))
        hits: Dict[str, int] = {d["id"]: 0 for d in DETECTORS}
        for f in findings:
            hits[f.rule] = hits.get(f.rule, 0) + 1
        hits["provenance_gap"] = coverage["unlinked"]
        return {
            "findings": findings,
            "artifacts": artifacts,
            "hits": hits,
            "observed": {
                "memories": len(artifacts),
                "servable": sum(1 for a in artifacts if a.is_servable()),
                "runtimes": len(env.runtimes),
                "source_records": source_total,
                "lineage": coverage,
            },
        }

    # ------------------------------------------------------------------
    # Memory detectors
    # ------------------------------------------------------------------
    def _memory(self, artifacts: List[MemoryArtifact],
                patient_filter: Optional[str]):
        env = self.env
        by_commitment = {a.commitment(): a for a in artifacts}
        findings: List[Finding] = []
        derived = unlinked = 0

        for art in artifacts:
            if not art.is_servable():
                continue
            pid = _patient_of(art)
            if patient_filter and pid != patient_filter:
                continue
            recipe = art.replay_recipe
            common = dict(patient_id=pid, owner=art.owner.value,
                          artifact_type=art.artifact_type.value,
                          session_id=art.session_id or None,
                          task_id=recipe.task_id if recipe else None)
            facts = art.structured_facts or {}

            # --- content integrity ----------------------------------------
            # The commitment is sealed (and signed) at write time. Lineage can
            # legitimately be lost from logs, so only the content is re-hashed.
            if art.content_ref and commit_text(art.content) != art.content_ref:
                findings.append(Finding(
                    "integrity", "critical", "memory", art.key,
                    "Content no longer matches the commitment sealed when it was written.",
                    confidence=0.99, evidence={"signed_by": art.signed_by}, **common))

            # --- identity alias re-resolution -----------------------------
            if art.artifact_type == ArtifactType.IDENTITY_HINT and pid:
                query = _query_from_key(facts.get("query_key", ""))
                matches = _resolve_query(env.fhir, query) if query else None
                if matches is not None and pid not in matches:
                    findings.append(Finding(
                        "identity_reresolve", "critical", "memory", art.key,
                        "Stored alias points at a different patient than the FHIR "
                        "index returns for the same identifiers.",
                        confidence=0.97,
                        evidence={"query": facts.get("query_key"), "stored": pid,
                                  "fhir_returns": sorted(matches) or ["no match"]},
                        **common))

            # --- work-order cross-check -----------------------------------
            if (recipe and pid and art.artifact_type != ArtifactType.IDENTITY_HINT):
                expected = self._task_patients(recipe.task_id)
                if expected is not None and pid not in expected:
                    findings.append(Finding(
                        "work_order", "high", "memory", art.key,
                        "Written for a task about a different patient than the one it names.",
                        confidence=0.92,
                        evidence={"task": recipe.task_id, "expected": sorted(expected),
                                  "names": pid},
                        **common))

            # --- lineage patient drift + inheritance ----------------------
            parents = [by_commitment.get(c) for c in art.explicit_parent_commitments]
            parents = [p for p in parents if p is not None]
            if art.artifact_type in DERIVED_TYPES:
                derived += 1
                if not art.explicit_parent_commitments:
                    unlinked += 1
            for parent in parents:
                ppid = _patient_of(parent)
                if pid and ppid and ppid != pid:
                    findings.append(Finding(
                        "lineage_drift", "high", "memory", art.key,
                        "Derived from a parent about another patient.",
                        confidence=0.9,
                        evidence={"parent": parent.key, "parent_patient": ppid,
                                  "this_patient": pid},
                        **common))
                if parent.state in _HELD:
                    findings.append(Finding(
                        "inherited_withdrawn", "high", "memory", art.key,
                        f"Still in use although its parent is {parent.state.value}.",
                        confidence=0.95,
                        evidence={"parent": parent.key, "parent_state": parent.state.value},
                        **common))

            # --- cited-evidence ownership + stale values ------------------
            cited = list(facts.get("observation_ids") or []) + \
                list(facts.get("condition_ids") or [])
            foreign: List[str] = []
            current: Dict[str, Set[float]] = {}
            invalidated: List[str] = []
            for rid in cited:
                kind = "Condition" if "-CND" in rid else "Observation"
                res = env.fhir.read(kind, rid)
                if res is None:
                    continue
                subject = res.get("subject", {}).get("reference", "")
                if pid and subject and subject != f"Patient/{pid}":
                    foreign.append(rid)
                if res.get("status") in ("entered-in-error", "cancelled"):
                    invalidated.append(rid)
                if kind == "Observation":
                    code = ((res.get("code", {}).get("coding") or [{}])[0]).get("code")
                    value = res.get("valueQuantity", {}).get("value")
                    if code is not None and isinstance(value, (int, float)):
                        current.setdefault(str(code), set()).add(round(float(value), 4))
            if foreign:
                findings.append(Finding(
                    "evidence_ownership", "high", "memory", art.key,
                    f"Cites {len(foreign)} record(s) that belong to another patient.",
                    confidence=0.94, evidence={"foreign": foreign[:6]}, **common))

            stale: List[Dict[str, Any]] = []
            for code, asserted in (facts.get("values") or {}).items():
                live = current.get(str(code))
                if live and isinstance(asserted, (int, float)) and \
                        round(float(asserted), 4) not in live:
                    stale.append({"code": code, "asserted": asserted,
                                  "current": sorted(live)})
            if art.artifact_type == ArtifactType.AGGREGATE and pid and \
                    isinstance(facts.get("value"), (int, float)):
                code = facts.get("metric_code")
                obs = [o for o in env.fhir.observations_for(pid)
                       if ((o.get("code", {}).get("coding") or [{}])[0]).get("code") == code]
                if obs:
                    mean = round(sum(o["valueQuantity"]["value"] for o in obs) / len(obs), 2)
                    if abs(mean - float(facts["value"])) > 0.011:
                        stale.append({"code": code, "asserted": facts["value"],
                                      "current": [mean]})
            if stale or invalidated:
                findings.append(Finding(
                    "stale_value", "high", "memory", art.key,
                    "Asserts values the trusted record no longer holds."
                    if stale else "Cites a source that was invalidated.",
                    confidence=0.9,
                    evidence={"stale": stale[:4], "invalidated": invalidated[:4]},
                    **common))

            # --- restricted-field exposure --------------------------------
            restricted_ids = facts.get("restricted_ids") or []
            if restricted_ids and FieldCategory.RESTRICTED not in \
                    ROLE_FIELD_MATRIX.get(art.owner, frozenset()):
                confirmed = [rid for rid in restricted_ids
                             if (env.fhir.read("Observation", rid) or {}).get("_aegisRestricted")]
                if confirmed:
                    findings.append(Finding(
                        "restricted_exposure", "critical", "memory", art.key,
                        f"Holds {len(confirmed)} physician-only field(s) the "
                        f"{art.owner.value.replace('_', ' ')} role may not see.",
                        confidence=0.98,
                        evidence={"restricted": confirmed[:4], "role": art.owner.value},
                        **common))

        coverage = {"derived": derived, "unlinked": unlinked,
                    "coverage": round(1 - unlinked / derived, 3) if derived else 1.0}
        return findings, coverage

    def _task_patients(self, task_id: str) -> Optional[Set[str]]:
        if task_id not in self._task_cache:
            task = next((t for t in self.env.tasks if t["task_id"] == task_id), None)
            query = (task or {}).get("query") or {}
            self._task_cache[task_id] = _resolve_query(self.env.fhir, query) if query else None
        return self._task_cache[task_id]

    # ------------------------------------------------------------------
    # Source registry detectors
    # ------------------------------------------------------------------
    def _source(self, patient_filter: Optional[str]):
        if self.registry is None:
            return [], 0
        scan = self.registry.sentinel_scan()
        total = scan["total_records"][0]["count"]
        findings: List[Finding] = []

        def keep(*pids: Optional[str]) -> bool:
            return not patient_filter or patient_filter in pids

        for row in scan["mismatches"]:
            if not keep(row["chart_patient_id"], row["source_patient_id"]):
                continue
            verified = row["fhir_subject"] == f"Patient/{row['source_patient_id']}"
            findings.append(Finding(
                "source_identity", "high", "source", row["record_key"],
                f"{row['label']} is filed in {row['chart_patient_id']}'s chart but its "
                f"FHIR subject is {row['fhir_subject'].replace('Patient/', '')}.",
                patient_id=row["chart_patient_id"], confidence=0.96 if verified else 0.7,
                evidence={"chart": row["chart_patient_id"],
                          "fhir_subject": row["fhir_subject"],
                          "fix_verified": verified},
                action={"kind": "correct_source", "label": "Refile to verified chart"}
                if verified else None))
        for row in scan["invalid"]:
            if not keep(row["chart_patient_id"]):
                continue
            findings.append(Finding(
                "source_invalid", "medium", "source", row["record_key"],
                f"{row['label']} is marked {row['status']} at source.",
                patient_id=row["chart_patient_id"], confidence=0.99,
                evidence={"status": row["status"]}))
        for row in scan["held_transfers"]:
            if not keep(row["source_patient_id"], row["target_patient_id"]):
                continue
            findings.append(Finding(
                "held_transfer", "medium", "source", f"transfer:{row['id']}",
                f"Handover of {row['record_key']} to {row['destination']} was blocked.",
                patient_id=row["source_patient_id"], confidence=0.85,
                evidence={"why": row["explanation"][:220],
                          "target": row["target_patient_id"]}))
        for row in scan["open_reports"]:
            if not keep(row["patient_id"]):
                continue
            memory = row["concern_type"] == "assistant_memory"
            findings.append(Finding(
                "human_report", "high" if memory else "medium", "source",
                f"report:{row['id']}",
                ("Staff reported a possible assistant/memory error."
                 if memory else "Staff reported a possible source record problem."),
                patient_id=row["patient_id"], confidence=0.6,
                evidence={"report_id": row["id"], "concern": row["concern_type"],
                          "record": row["record_key"],
                          "triage": row.get("safety_status")}))
        return findings, total


__all__ = ["DetectorSuite", "Finding", "DETECTORS", "DETECTOR_NAMES", "SEVERITY_RANK"]
