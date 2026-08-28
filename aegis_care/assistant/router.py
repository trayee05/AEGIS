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
from .intents import (ACTIONS_BY_NAME, actions_for, extract_params, match_local,
                      normalise_param)

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



# "yes", "go on", "do it" - a standing offer is what makes the assistant able to
# propose a next step and then act on a one-word answer.
CONFIRM = re.compile(
    r"^\s*(y|ya|yes|yeah|yep|sure|ok|okay|go|go\s+on|go\s+ahead|do\s+it|"
    r"do\s+that|please\s+do|sounds\s+good|alright|proceed|continue|"
    r"lets\s+do\s+it|let's\s+do\s+it)\b[\s.!]*$", re.I)

DECLINE = re.compile(r"^\s*(n|no|nope|not\s+now|cancel|nevermind|never\s+mind)\b[\s.!]*$", re.I)

# "explain it", "what does that mean", "tell me more" - refers to the last thing.
REFERS_BACK = re.compile(
    r"\b(it|that|this|the\s+same|those|them)\b|^\s*(so\s+)?explain\s*[.!?]*$", re.I)


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
        # Conversational context. Without this, "so explain it" and "yes, do
        # that" have no referent and the assistant answers nothing.
        self.context: Dict[str, Any] = {
            "last_action": None,     # what we just did
            "last_topic": None,      # what we just talked about
            "offer": None,           # {action, params, label} we proposed
        }

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

        # Context-dependent input must never be cached or sent to the model:
        # "yes" means something different every time.
        contextual = self._resolve_from_context(message, role)
        if contextual is not None:
            self._remember(None, contextual)
            return contextual

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
    def _resolve_from_context(self, message: str, role: str) -> Optional[Dict[str, Any]]:
        """Handle replies that only make sense as part of a conversation."""
        text = message.strip()
        offer = self.context.get("offer")

        if DECLINE.match(text):
            self.context["offer"] = None
            return {"action": "none", "params": {}, "source": "context",
                    "reply": "No problem. Tell me when you want to pick it up."}

        if CONFIRM.match(text):
            if offer and offer.get("message"):
                # Replay the offered step as if the user had typed it. One level
                # of recursion only: the replayed message is never a bare "yes".
                self.context["offer"] = None
                replayed = self.route(offer["message"], role)
                replayed["source"] = f"{replayed.get('source', 'local')}+confirmed"
                return replayed
            if offer and offer.get("action"):
                self.context["offer"] = None
                return {"action": offer["action"],
                        "params": dict(offer.get("params") or {}),
                        "source": "context", "reply": ""}
            return {"action": "system_status", "params": {}, "source": "context",
                    "reply": ""}

        # "explain it" / "so explain" / "what does that mean" with no new subject.
        lowered = text.lower()
        wants_explanation = re.search(
            r"\b(explain|what\s+does\s+(it|that|this)\s+mean|tell\s+me\s+more|"
            r"go\s+deeper|elaborate)\b", lowered)
        if wants_explanation:
            named = any(term in lowered for term in GLOSSARY)
            if not named and REFERS_BACK.search(lowered) or (
                    wants_explanation and len(lowered.split()) <= 3 and not named):
                topic = self.context.get("last_topic") or self.context.get("last_action")
                return {"action": "explain", "params": {"topic": topic or "screen"},
                        "source": "context", "reply": ""}
        return None
    # ------------------------------------------------------------------
    def _fallback_explain(self, resolved: Dict[str, Any]) -> Dict[str, Any]:
        """Answer `explain` from the glossary, never from the model.

        The model is prompted to return a one-line confirmation of the action it
        picked - useful for "opening the queue", useless as an explanation. If
        that filler were allowed through, "what is the current system state"
        would answer "I can explain the current system state", which is what it
        used to do. Explanations are therefore always regenerated here, and an
        unmatched topic is handed to the API to answer from live state.
        """
        if resolved.get("action") != "explain":
            return resolved
        resolved["reply"] = ""            # discard any model-authored text
        topic = str(resolved.get("params", {}).get("topic", "")).strip()
        for term in sorted(GLOSSARY, key=len, reverse=True):
            if term in topic:
                resolved["reply"] = GLOSSARY[term]
                resolved["params"]["topic"] = term
                resolved["source"] = "glossary"
                return resolved
        # No glossary hit: the API answers from what is actually on screen.
        resolved["source"] = "state"
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
        params = {}
        for key, value in (resolved.get("params") or {}).items():
            if key not in declared or value in (None, ""):
                continue
            cleaned = normalise_param(key, value)
            if cleaned not in (None, ""):
                params[key] = cleaned
        for key, value in extract_params(name, " " + message.lower() + " ").items():
            params.setdefault(key, value)
        resolved["params"] = params
        resolved.setdefault("reply", "")
        return resolved

    # ------------------------------------------------------------------
    def _remember(self, key: Optional[str], resolved: Dict[str, Any]) -> None:
        action = resolved.get("action")
        if action and action != "none":
            self._history.append(action)
            del self._history[:-4]
            self.context["last_action"] = action
            topic = (resolved.get("params") or {}).get("topic")
            if topic:
                self.context["last_topic"] = topic
        if key is not None:
            self._cache[key] = dict(resolved)
            while len(self._cache) > CACHE_SIZE:
                self._cache.popitem(last=False)

    def offer(self, action: str, params: Optional[Dict[str, Any]] = None,
              label: str = "") -> None:
        """Record a proposed next step so a bare 'yes' can execute it."""
        self.context["offer"] = {"action": action, "params": params or {},
                                 "label": label}

    def offer_message(self, message: str, label: str = "") -> None:
        """Offer a next step by the phrasing that performs it.

        Storing the message rather than the action keeps the offer honest: a
        confirmation runs exactly the same path as typing it, including role
        validation, so "yes" can never reach somewhere typing could not.
        """
        self.context["offer"] = {"action": None, "params": {},
                                 "label": label, "message": message}

    def note_topic(self, topic: Optional[str]) -> None:
        if topic:
            self.context["last_topic"] = topic


__all__ = ["Router", "Budget", "GLOSSARY", "DEFAULT_MAX_CALLS"]
