"""Sentinel: proactive detection, root-cause correlation, containment, triage.

The central claim is that the Sentinel finds planted faults it was never told
about, using only operational data (FHIR, replay recipes, lineage, policy) and
never benchmark instrumentation. Every test that scores it does so against
labels the detectors cannot read.
"""
from __future__ import annotations

import ast
import threading
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from aegis_care.api.app import app
from aegis_care.clinical_registry import ClinicalRegistry
from aegis_care.environment import AegisEnvironment
from aegis_care.incident.masks import ProvenanceMask
from aegis_care.incident.scenarios import FAMILIES, ScenarioBuilder
from aegis_care.memory.models import MemoryState
from aegis_care.sentinel.agent import Sentinel
from aegis_care.sentinel.detectors import DETECTORS, DetectorSuite

SENTINEL_DIR = Path(__file__).resolve().parent.parent / "aegis_care" / "sentinel"


def _fresh(tmp_path):
    env = AegisEnvironment()
    registry = ClinicalRegistry(tmp_path / "registry.sqlite3")
    sentinel = Sentinel(lambda: env, registry, threading.Lock(), lambda: ScenarioBuilder(env))
    return env, registry, sentinel


class TestNoGroundTruthAccess:
    def test_detectors_never_read_instrumentation(self):
        """The drill score is only honest if detection cannot see the answers."""
        forbidden = {"_true_parents", "true_contaminated", "truth", "true_patient",
                     "contaminated", "clean_keys"}
        for name in ("detectors.py",):
            tree = ast.parse((SENTINEL_DIR / name).read_text(encoding="utf-8"))
            attrs = {n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute)}
            assert not attrs & forbidden, attrs & forbidden

    def test_catalogue_is_complete(self):
        ids = [d["id"] for d in DETECTORS]
        assert len(ids) == len(set(ids)) == 13


class TestDetection:
    @pytest.mark.parametrize("provenance", ["complete", "random40", "targeted"])
    def test_finds_every_family_without_false_positives(self, tmp_path, provenance):
        env, registry, _ = _fresh(tmp_path)
        builder = ScenarioBuilder(env)
        incidents = [builder.build(f, env.tasks[i * 3], incident_id=f"T{i}", depth=4,
                                   n_controls=1) for i, f in enumerate(FAMILIES)]
        for inc in incidents:
            ProvenanceMask(env, 7).apply(provenance, scope_keys=inc.all_keys())
        scan = DetectorSuite(env, registry).run()
        flagged = {f.subject for f in scan["findings"] if f.domain == "memory"}
        # Ground truth per node: wrong patient, or labelled contaminated.
        wrong = {n.key for t in env.trajectories.values() for n in t.nodes
                 if n.true_patient != t.intended_patient or n.contaminated}
        assert wrong <= flagged, sorted(wrong - flagged)
        assert flagged <= wrong, sorted(flagged - wrong)

    def test_clean_environment_is_quiet(self, tmp_path):
        env, registry, _ = _fresh(tmp_path)
        for task in env.tasks[:6]:
            env.run_trajectory(task, depth=4)
        scan = DetectorSuite(env, registry).run()
        assert not [f for f in scan["findings"] if f.domain == "memory"]

    def test_scan_does_not_inflate_care_overhead(self, tmp_path):
        env, registry, _ = _fresh(tmp_path)
        env.run_trajectory(env.tasks[0], depth=4)
        before = env.fhir.read_count
        DetectorSuite(env, registry).run()
        assert env.fhir.read_count == before

    def test_content_tamper_is_detected(self, tmp_path):
        env, registry, _ = _fresh(tmp_path)
        traj = env.run_trajectory(env.tasks[0], depth=4)
        art = env.find_artifact(traj.nodes[2].key)
        art.content += " (edited)"
        rules = {f.rule for f in DetectorSuite(env, registry).run()["findings"]
                 if f.subject == art.key}
        assert "integrity" in rules

    def test_seeded_source_mismatches_are_found(self, tmp_path):
        env, registry, _ = _fresh(tmp_path)
        source = [f for f in DetectorSuite(env, registry).run()["findings"]
                  if f.rule == "source_identity"]
        assert len(source) == 6
        assert all(f.action and f.evidence["fix_verified"] for f in source)


class TestAgent:
    @pytest.mark.parametrize("family", FAMILIES)
    def test_blind_drill_detect_contain_verify(self, tmp_path, family):
        env, _, sentinel = _fresh(tmp_path)
        sentinel.drill(family, "random40", register=lambda *_: None)
        first = sentinel.patrol()
        drill = first["drills"][0]
        assert drill["status"] == "detected"
        assert drill["score"]["recall"] == 1.0
        assert drill["score"]["clean_flagged"] == 0
        assert first["cases"], "a planted fault must become a case"

        second = sentinel.patrol(autopilot=True)
        assert second["acted"]
        assert not second["cases"]
        assert second["trace"][-1]["phase"] == "verify" and second["trace"][-1]["ok"]
        outcome = second["acted"][0]
        assert outcome["safe_resume"]
        # Waves seed CARE at one root, so lineage loss must not cost utility:
        # only the true seed is withdrawn; descendants are rebuilt.
        assert outcome["withdrawn"] == 1
        inc = sentinel.drills["DRILL-01"]["incident"]
        seed = env.find_artifact(inc.seed_key)
        assert seed.state == MemoryState.TOMBSTONED

    def test_autopilot_never_refiles_charts(self, tmp_path):
        env, registry, sentinel = _fresh(tmp_path)
        sentinel.patrol(autopilot=True)
        assert all(not registry.corrections(f"S{1000 + i}") for i in range(160))

    def test_drill_family_hidden_until_found(self, tmp_path):
        env, _, sentinel = _fresh(tmp_path)
        sentinel.drill("F3", "complete", register=lambda *_: None)
        public = Sentinel._public_drill(sentinel.drills["DRILL-01"])
        assert public["family"] is None and public["status"] == "hidden"


@pytest.fixture
def client():
    client = TestClient(app)
    client.post("/api/system/reset")
    return client


class TestAPI:
    def test_patrol_contain_certificate(self, client):
        assert client.post("/api/sentinel/drill", json={"family": "F1"}).status_code == 200
        patrol = client.post("/api/sentinel/patrol", json={}).json()
        assert patrol["posture"]["level"] == "critical"
        assert patrol["brief"]["source"] == "local"
        case = patrol["cases"][0]
        outcome = client.post(f"/api/sentinel/cases/{case['case_id']}/contain").json()
        assert outcome["repaired"] >= 1
        cert = client.get(f"/api/sentinel/certificates/{outcome['incident_id']}")
        assert cert.status_code == 200 and "RECOVERY CERTIFICATE" in cert.text
        assert not client.post("/api/sentinel/patrol", json={}).json()["cases"]

    def test_unknown_case_is_404(self, client):
        assert client.post("/api/sentinel/cases/SC-NOPE/contain").status_code == 404

    def test_findings_carry_no_memory_content(self, client):
        client.post("/api/sentinel/drill", json={"family": "F3"})
        patrol = client.post("/api/sentinel/patrol", json={}).json()
        body = str(patrol)
        assert "Carried-forward screening detail" not in body
        assert "Shift handover" not in body

    def test_manual_report_triage_and_filing(self, client):
        patients = client.get("/api/patients?only_with_memory=false").json()["patients"]
        target = next(p for p in patients if p["source_held"])
        name = target["patient"]["name"]
        r = client.post("/api/sentinel/report", json={
            "text": f"The assistant's handover for {name} shows a lab that belongs to someone else."
        }).json()
        assert r["category"] == "wrong_patient"
        assert r["patient_id"] == target["token"]
        assert r["filed"] and r["concern_type"] == "assistant_memory"
        assert any(f["relevant"] for f in r["corroboration"])
        referrals = client.get("/api/safety/referrals").json()
        assert referrals["pending"] == 1

    def test_manual_report_without_patient_is_not_filed(self, client):
        r = client.post("/api/sentinel/report", json={"text": "something about nobody in particular"}).json()
        assert r["patient_id"] is None and r["filed"] is None

    def test_report_validation(self, client):
        assert client.post("/api/sentinel/report", json={"text": "short"}).status_code == 422

    def test_bad_drill_inputs(self, client):
        assert client.post("/api/sentinel/drill", json={"family": "F9"}).status_code == 400
        assert client.post("/api/sentinel/drill", json={"provenance": "x"}).status_code == 400
