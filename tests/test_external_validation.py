"""External FHIR adapter and evidence-manifest regression tests."""
from __future__ import annotations

import json
from dataclasses import replace

from aegis_care.care.coordinator import RecoveryCoordinator
from aegis_care.config import CONFIG
from aegis_care.environment import AegisEnvironment
from aegis_care.eval.evidence import verify_evidence_manifest, write_evidence_manifest
from aegis_care.fhir.loader import load_fhir_sources
from aegis_care.fhir.store import FHIRStore
from aegis_care.incident.scenarios import ScenarioBuilder
from aegis_care.incident.masks import ProvenanceMask


def _bundle() -> dict:
    entries = []
    for index in range(2):
        patient_id = f"p{index + 1}"
        patient_url = f"urn:uuid:{patient_id}"
        entries.extend([
            {
                "fullUrl": patient_url,
                "resource": {
                    "resourceType": "Patient", "id": patient_id,
                    "meta": {"profile": [
                        "http://hl7.org/fhir/us/core/StructureDefinition/us-core-patient"
                    ]},
                    "identifier": [{
                        "type": {"coding": [{"code": "MR"}]},
                        "value": f"MR-{index + 1}",
                    }],
                    "name": [{"use": "official", "given": [f"Given{index}"],
                              "family": f"Family{index}"}],
                    "gender": "unknown", "birthDate": f"198{index}-01-01",
                },
            },
            {
                "fullUrl": f"urn:uuid:o{index + 1}",
                "resource": {
                    "resourceType": "Observation", "id": f"o{index + 1}",
                    "status": "final",
                    "category": [{"coding": [{"code": "vital-signs"}]}],
                    "code": {"coding": [{"system": "http://loinc.org",
                                           "code": "8867-4", "display": "Heart rate"}]},
                    "subject": {"reference": patient_url},
                    "effectiveDateTime": "2026-01-01T00:00:00Z",
                    "valueQuantity": {"value": 70 + index, "unit": "beats/min"},
                },
            },
        ])
    return {"resourceType": "Bundle", "type": "transaction", "entry": entries}


def test_external_fhir_reference_normalisation_and_recovery(tmp_path):
    source = tmp_path / "synthea-mini.json"
    source.write_text(json.dumps(_bundle()), encoding="utf-8")
    resources, report = load_fhir_sources([source])

    assert report.patients_loaded == 2
    assert report.references_rewritten == 2
    assert report.unresolved_urn_references == 0
    assert report.source_sha256[source.name]
    assert {obs["subject"]["reference"] for obs in resources["Observation"]} == {
        "Patient/p1", "Patient/p2"
    }

    config = replace(CONFIG, n_patients=2, n_base_tasks=9)
    env = AegisEnvironment(
        config,
        fhir_store=FHIRStore(resources=resources, source_info=report.to_dict()),
    )
    incident = ScenarioBuilder(env).build("F1", env.tasks[0], depth=4, n_controls=1)
    recovery = RecoveryCoordinator(env).recover(incident.incident_id, [incident.seed_key])
    assert recovery.closure_reached
    assert len(recovery.repaired) == len(incident.true_contaminated) == 4
    assert not recovery.quarantined

    # The external-data failure that motivated scoped support fingerprints:
    # stale-fact prose can be semantically dissimilar after correction and the
    # targeted mask removes most lineage.  Discovery may use the opaque scoped
    # fingerprints, but attribution still has to confirm every repair locally.
    env = AegisEnvironment(
        config,
        fhir_store=FHIRStore(resources=resources, source_info=report.to_dict()),
    )
    stale = ScenarioBuilder(env).build("F4", env.tasks[3], depth=4, n_controls=1)
    ProvenanceMask(env, seed=77).apply("targeted")
    recovery = RecoveryCoordinator(env).recover(stale.incident_id, [stale.seed_key])
    assert recovery.closure_reached
    assert set(recovery.confirmed) == stale.true_contaminated
    assert len(recovery.repaired) == len(stale.true_contaminated)
    assert not recovery.quarantined


def test_evidence_manifest_detects_tampering(tmp_path):
    artifact = tmp_path / "results.json"
    artifact.write_text('{"ok": true}', encoding="utf-8")
    manifest = write_evidence_manifest(
        tmp_path,
        results={
            "rows": [{"condition": "I"}], "incidents": [{}],
            "by_condition": [{"condition": "I", "rwh": 0.0}],
            "verification_failures": [], "wall_seconds": 1.0,
        },
        data_source={"claim_tier": "test", "synthetic_evidence_only": True},
        evidence_files=[artifact],
        command="pytest",
    )
    assert verify_evidence_manifest(manifest)["valid"]

    artifact.write_text('{"ok": false}', encoding="utf-8")
    verification = verify_evidence_manifest(manifest)
    assert not verification["valid"]
    assert verification["failures"][0]["reason"] == "sha256 mismatch"


class TestSealPortability:
    """The committed seal must verify on any platform.

    .gitattributes normalises text artifacts to LF, so a manifest that hashed
    raw bytes on a CRLF machine could never re-verify after a clone -- which is
    exactly the failure this guards against.
    """

    def test_committed_manifest_verifies(self):
        from pathlib import Path

        from aegis_care.eval.evidence import verify_evidence_manifest

        manifest = (Path(__file__).resolve().parent.parent
                    / "results" / "external_validation" / "evidence_manifest.json")
        if not manifest.is_file():
            import pytest
            pytest.skip("no committed external-validation package in this checkout")
        result = verify_evidence_manifest(manifest)
        assert result["valid"], f"integrity seal broken: {result['failures']}"
        assert result["artifacts_checked"] > 0

    def test_text_digest_is_line_ending_independent(self, tmp_path):
        from aegis_care.eval.evidence import sha256_file

        lf = tmp_path / "a.md"
        crlf = tmp_path / "b.md"
        lf.write_bytes(b"# title\n\nrow one\nrow two\n")
        crlf.write_bytes(b"# title\r\n\r\nrow one\r\nrow two\r\n")
        assert sha256_file(lf) == sha256_file(crlf)

    def test_binary_digest_is_exact(self, tmp_path):
        import hashlib

        from aegis_care.eval.evidence import sha256_file

        blob = tmp_path / "fig.png"
        payload = b"\x89PNG\r\n\x1a\n" + bytes(range(256))
        blob.write_bytes(payload)
        # A binary artifact must never be newline-normalised.
        assert sha256_file(blob) == hashlib.sha256(payload).hexdigest()

    def test_manifest_records_its_hash_method(self, tmp_path):
        from aegis_care.eval.evidence import write_evidence_manifest

        artifact = tmp_path / "report.md"
        artifact.write_text("body\n", encoding="utf-8")
        path = write_evidence_manifest(
            tmp_path, results={"rows": [], "incidents": []}, data_source={},
            evidence_files=[artifact], command="test")
        import json
        manifest = json.loads(path.read_text(encoding="utf-8"))
        assert manifest["schema"] == "aegis-evidence-manifest/v2"
        assert manifest["hash_method"]["algorithm"] == "sha256"
        assert manifest["artifacts"]["report.md"]["hash_input"] == "newline-normalised"
