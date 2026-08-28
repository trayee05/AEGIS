"""Intent routing with a hard spend ceiling.

The order is always: cache -> local matcher -> glossary -> model. Only the last
step costs anything, and it is refused outright once the session budget is
spent, so an idle browser tab can never quietly burn an API quota.
"""
from __future__ import annotations

import os
import re
import threading
from collections import OrderedDict
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from . import gemini
from .intents import ACTIONS_BY_NAME, actions_for, extract_params, match_local

# A session is one server process. The default is generous for a demo and still
# bounded; set AEGIS_ASSISTANT_MAX_CALLS=0 to disable model routing entirely.
DEFAULT_MAX_CALLS = int(os.environ.get("AEGIS_ASSISTANT_MAX_CALLS", "150"))
CACHE_SIZE = 128


# Answered locally, so "what is RWH" never costs a token.
GLOSSARY: Dict[str, str] = {
    "rwh": "Residual harm - whether any wrong-patient or unauthorised content is "
           "still reachable after recovery. Zero is the goal.",
    "residual harm": "Whether any wrong-patient or unauthorised content is still "
                     "reachable after recovery. Zero is the goal.",
    "recall": "Of the records that really did inherit the error, the share the "
              "system found.",
    "precision": "Of the records the system acted on, the share that really were "
                 "affected. Low precision means it damaged healthy records.",
    "bsr": "Benign-state retention - how much untouched, healthy memory survived "
           "the recovery. A full wipe scores zero.",
    "benign-state retention": "How much untouched, healthy memory survived the "
                              "recovery. A full wipe scores zero.",
    "benign state retention": "How much untouched, healthy memory survived the "
                              "recovery. A full wipe scores zero.",
    "descendant recall": "Of the records that really did inherit the error, the "
                         "share the system found.",
    "descendant precision": "Of the records the system acted on, the share that "
                            "really were affected.",
    "unauthorised exposure": "Whether any role received data outside its "
                             "permissions. Zero is the goal.",
    "unauthorized exposure": "Whether any role received data outside its "
                             "permissions. Zero is the goal.",
    "resurrection": "A withdrawn entry finding its way back into use. The "
                    "firewall exists to make that impossible.",
    "false repair": "Rebuilding a record that was never actually affected - the "
                    "cost of treating similarity as proof.",
    "rts": "Repaired task success - whether the assistant answers the follow-up "
           "task correctly after repair.",
    "uer": "Unauthorised exposure rate - whether any role received data outside "
           "its permissions.",
    "drr": "Deletion resurrection rate - whether a withdrawn entry came back.",
    "care": "The four-stage loop: find candidates, prove influence by replay, "
            "rebuild from trusted source data, then enforce the withdrawal.",
    "capsule": "The small metadata packet a runtime sends the coordinator. It "
               "carries commitments, bands and tokens - never clinical text.",
    "tombstone": "A signed record that a version was withdrawn. Content is never "
                 "destructively deleted; it becomes non-servable.",
    "quarantine": "What happens when a record cannot be rebuilt safely. It is "
                  "held for a human instead of guessed at.",
    "blast radius": "How far the original error spread through derived records.",
    "provenance": "The recorded links showing which record was derived from "
                  "which. In practice these links are often incomplete.",
    "sketch": "A bounded, receiver-scoped fingerprint used to nominate candidate "
              "records when provenance links are missing. It never authorises a "
              "repair on its own.",
    "counterfactual": "Rebuilding a record without the suspect entry to see "
                      "whether it actually mattered. Similarity is not causality.",
    "fhir": "The clinical data standard the sandbox uses as its trusted source "
            "of truth for rebuilds.",
}


@dataclass
class Budget:
    """Session spend ceiling for model calls."""

    max_calls: int = DEFAULT_MAX_CALLS
    calls: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    local_hits: int = 0
    lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    def remaining(self) -> int:
        return max(0, self.max_calls - self.calls)

    def spend(self, tokens: Dict[str, int]) -> None:
        with self.lock:
            self.calls += 1
            self.input_tokens += int(tokens.get("input", 0))
            self.output_tokens += int(tokens.get("output", 0))

    def note_local(self) -> None:
        with self.lock:
            self.local_hits += 1

    def to_dict(self) -> Dict[str, Any]:
        total = self.calls + self.local_hits
        return {
            "model_calls": self.calls,
            "local_hits": self.local_hits,
            "max_calls": self.max_calls,
            "remaining": self.remaining(),
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "free_share": round(self.local_hits / total, 3) if total else 0.0,
            "configured": gemini.configured(),
            "model": gemini.DEFAULT_MODEL,
        }


class Router:
    """Resolves a natural-language message to one catalogue action."""

    def __init__(self, budget: Optional[Budget] = None) -> None:
        self.budget = budget or Budget()
        self._cache: "OrderedDict[str, Dict[str, Any]]" = OrderedDict()
        self._history: List[str] = []

    # ------------------------------------------------------------------
    @staticmethod
    def _normalise(message: str) -> str:
        return re.sub(r"\s+", " ", message.strip().lower())

    def _glossary_answer(self, message: str) -> Optional[Dict[str, Any]]:
        text = self._normalise(message)
        if not re.search(r"\b(what|explain|mean|meaning|define|tell me about)\b", text):
            return None
        # Longest term first so "residual harm" wins over "harm".
        for term in sorted(GLOSSARY, key=len, reverse=True):
            if term in text:
                return {
                    "action": "explain",
                    "params": {"topic": term},
                    "reply": GLOSSARY[term],
                    "source": "glossary",
                }
        return None

    # ------------------------------------------------------------------
    def route(self, message: str, role: str) -> Dict[str, Any]:
        message = (message or "").strip()
        if not message:
            return {"action": "none", "params": {}, "source": "local",
                    "reply": "Tell me what happened, or ask what something means."}

        key = f"{role}:{self._normalise(message)}"
        if key in self._cache:
            cached = dict(self._cache[key])
            cached["source"] = f"{cached['source']}+cache"
            return cached

        resolved = self._glossary_answer(message)
        if resolved is None:
            local = match_local(message, role)
            if local is not None:
                self.budget.note_local()
                local.setdefault("reply", "")
                resolved = local

        if resolved is None:
            resolved = self._route_via_model(message, role)

        resolved = self._validate(resolved, role, message)
        resolved = self._fallback_explain(resolved)
        self._remember(key, resolved)
        return resolved

    # ------------------------------------------------------------------
    def _fallback_explain(self, resolved: Dict[str, Any]) -> Dict[str, Any]:
        """An `explain` with no glossary hit still answers locally, for free."""
        if resolved.get("action") != "explain" or resolved.get("reply"):
            return resolved
        topic = str(resolved.get("params", {}).get("topic", "")).strip()
        for term in sorted(GLOSSARY, key=len, reverse=True):
            if term in topic:
                resolved["reply"] = GLOSSARY[term]
                resolved["params"]["topic"] = term
                resolved["source"] = "glossary"
                return resolved
        resolved["reply"] = (
            "I can explain any of: " + ", ".join(sorted(
                t for t in GLOSSARY if " " not in t or len(t) < 20)[:12]) + ".")
        resolved["source"] = "glossary"
        return resolved

    def _route_via_model(self, message: str, role: str) -> Dict[str, Any]:
        if not gemini.configured():
            return {
                "action": "none", "params": {}, "source": "unconfigured",
                "reply": "I could not match that to an action. Set GEMINI_API_KEY "
                         "to let me interpret free-form phrasing, or use the "
                         "buttons on screen.",
            }
        if self.budget.remaining() <= 0:
            return {
                "action": "none", "params": {}, "source": "budget",
                "reply": "The assistant's request budget for this session is spent. "
                         "The console still works normally from the controls.",
            }
        try:
            result = gemini.route(message, role, actions_for(role), self._history)
        except gemini.AssistantUnavailable as exc:
            return {"action": "none", "params": {}, "source": "error",
                    "reply": f"I could not interpret that ({exc})."}
        self.budget.spend(result.pop("tokens", {}))
        return result

    # ------------------------------------------------------------------
    def _validate(self, resolved: Dict[str, Any], role: str,
                  message: str) -> Dict[str, Any]:
        """A model may name an action this role cannot take. Never trust it blind."""
        name = resolved.get("action", "none")
        if name == "none":
            resolved.setdefault("reply", "Could you say that a different way?")
            resolved["params"] = {}
            return resolved

        action = ACTIONS_BY_NAME.get(name)
        if action is None:
            return {"action": "none", "params": {}, "source": resolved.get("source", "model"),
                    "reply": "I do not have an action for that."}

        if "any" not in action.roles and role not in action.roles:
            allowed = ", ".join(a for a in action.roles)
            return {
                "action": "none", "params": {},
                "source": resolved.get("source", "model"),
                "reply": f"That is not something the {role} role can do - it "
                         f"belongs to: {allowed}. Switch role and ask again.",
            }

        # Keep only parameters this action declares, and backfill from the text.
        declared = set(action.params)
        params = {k: v for k, v in (resolved.get("params") or {}).items()
                  if k in declared and v not in (None, "")}
        for key, value in extract_params(name, " " + message.lower() + " ").items():
            params.setdefault(key, value)
        resolved["params"] = params
        resolved.setdefault("reply", "")
        return resolved

    # ------------------------------------------------------------------
    def _remember(self, key: str, resolved: Dict[str, Any]) -> None:
        if resolved.get("action") != "none":
            self._history.append(resolved["action"])
            del self._history[:-4]
        self._cache[key] = dict(resolved)
        while len(self._cache) > CACHE_SIZE:
            self._cache.popitem(last=False)


__all__ = ["Router", "Budget", "GLOSSARY", "DEFAULT_MAX_CALLS"]
