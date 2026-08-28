"""The natural-language layer.

Two properties matter more than routing accuracy:
  1. No model call is needed for the phrasings the console is demonstrated with.
  2. A model can never cause clinical data to be fabricated or a role to exceed
     its permissions - it only picks an action, which is then validated.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from aegis_care.api.app import app
from aegis_care.assistant import Router
from aegis_care.assistant.intents import ACTIONS_BY_NAME, actions_for, match_local
from aegis_care.assistant.router import Budget


@pytest.fixture
def client():
    client = TestClient(app)
    client.post("/api/system/reset")
    return client


@pytest.fixture
def router():
    return Router(budget=Budget(max_calls=0))   # model routing disabled outright


class TestLocalRouting:
    """These phrasings must never reach the model."""

    CASES = [
        ("yes i accidentally made a wrong registration", "safety", "report_incident"),
        ("we registered the wrong patient", "safety", "report_incident"),
        ("we mixed up two patients", "safety", "report_incident"),
        ("run the recovery", "safety", "run_recovery"),
        ("contain it", "safety", "run_recovery"),
        ("how far did it spread", "safety", "show_blast_radius"),
        ("which patients need my attention", "clinician", "list_patients"),
        ("list all patients", "clinician", "list_patients"),
        ("did any data leak", "compliance", "show_boundary"),
        ("what is waiting for me", "compliance", "show_queue"),
        ("run the leakage tests", "compliance", "run_leakage_tests"),
        ("reset everything", "safety", "reset_system"),
    ]

    @pytest.mark.parametrize("message,role,expected", CASES)
    def test_routes_without_a_model(self, router, message, role, expected):
        result = router.route(message, role)
        assert result["action"] == expected
        assert result["source"] in {"local", "glossary"}, \
            f"{message!r} should not need the model"
        assert router.budget.calls == 0

    def test_glossary_answers_are_free(self, router):
        for term in ("what is rwh", "what does bsr mean", "explain drr"):
            result = router.route(term, "clinician")
            assert result["action"] == "explain"
            assert result["source"].startswith("glossary")
            assert result["reply"]
        assert router.budget.calls == 0

    def test_repeat_messages_are_cached(self, router):
        first = router.route("run the recovery", "safety")
        second = router.route("Run the recovery", "safety")
        assert first["action"] == second["action"]
        assert "cache" in second["source"]

    def test_ambiguous_input_is_not_force_matched(self, router):
        """Gibberish must defer rather than pick a destructive action."""
        result = router.route("hmm ok sure whatever", "safety")
        assert result["action"] == "none"


class TestRoleSafety:
    def test_action_outside_the_role_is_refused(self, router):
        """A clinician must not be able to reset the sandbox by asking nicely."""
        result = router.route("reset everything", "clinician")
        assert result["action"] != "reset_system"

    def test_catalogue_roles_are_declared(self):
        for action in ACTIONS_BY_NAME.values():
            assert action.roles, f"{action.name} declares no roles"
            for role in action.roles:
                assert role in {"any", "clinician", "safety", "compliance", "researcher"}

    def test_every_role_has_actions(self):
        for role in ("clinician", "safety", "compliance", "researcher"):
            assert actions_for(role)

    def test_model_action_is_validated_against_the_role(self, router):
        """Simulate a model naming an action the role cannot take."""
        resolved = router._validate(
            {"action": "reset_system", "params": {}, "source": "model", "reply": "ok"},
            "clinician", "reset")
        assert resolved["action"] == "none"

    def test_unknown_action_from_a_model_is_dropped(self, router):
        resolved = router._validate(
            {"action": "drop_database", "params": {}, "source": "model", "reply": "ok"},
            "safety", "do it")
        assert resolved["action"] == "none"

    def test_undeclared_params_are_stripped(self, router):
        """A model cannot smuggle extra parameters into an action."""
        resolved = router._validate(
            {"action": "run_recovery", "source": "model", "reply": "ok",
             "params": {"evil": "rm -rf", "family": "F1"}},
            "safety", "run recovery")
        assert "evil" not in resolved["params"]


class TestBudget:
    def test_budget_refuses_model_calls_when_spent(self):
        router = Router(budget=Budget(max_calls=0))
        result = router.route("zzz qqq unmatched phrasing here", "safety")
        assert result["action"] == "none"
        assert router.budget.calls == 0

    def test_status_reports_spend(self, client):
        body = client.get("/api/assistant/status").json()
        assert "model_calls" in body and "max_calls" in body
        assert body["model_calls"] == 0


class TestAssistantEndpoint:
    def test_report_then_recover_drives_the_console(self, client):
        first = client.post("/api/assistant", json={
            "message": "we registered the wrong patient", "role": "safety"}).json()
        assert first["action"] == "report_incident"
        assert first["ui"]["view"] == "command"
        assert first["ui"]["incident_id"]

        second = client.post("/api/assistant", json={
            "message": "run the recovery", "role": "safety"}).json()
        assert second["action"] == "run_recovery"
        assert second["ui"]["recovered"] is True
        # The reply must carry real measured values, not model prose.
        assert "rebuilt" in second["reply"]

    def test_patient_names_resolve_without_a_model(self, client):
        client.post("/api/assistant", json={
            "message": "we registered the wrong patient", "role": "safety"})
        client.post("/api/assistant", json={"message": "run recovery", "role": "safety"})
        listing = client.get("/api/patients").json()["patients"]
        name = listing[0]["patient"]["name"].split()[0]

        body = client.post("/api/assistant", json={
            "message": f"show me {name}", "role": "clinician"}).json()
        assert body["action"] == "show_patient"
        assert body["source"] == "local"
        assert listing[0]["patient"]["name"] in body["reply"]

    def test_recovery_without_an_incident_is_handled(self, client):
        body = client.post("/api/assistant", json={
            "message": "run the recovery", "role": "safety"}).json()
        assert body["action"] == "run_recovery"
        assert "no open incident" in body["reply"].lower()

    def test_empty_message_does_not_error(self, client):
        body = client.post("/api/assistant", json={"message": "  ", "role": "safety"})
        assert body.status_code == 200
        assert body.json()["action"] == "none"

    def test_endpoint_never_500s_on_odd_input(self, client):
        for message in ("!!!", "😀😀", "a" * 600, "select * from patients"):
            response = client.post("/api/assistant",
                                   json={"message": message, "role": "clinician"})
            assert response.status_code == 200
