"""The action catalogue the assistant is allowed to take, and a free local matcher.

Design rule: the language model NEVER produces clinical data, metrics, or chart
values. It only chooses one action from this catalogue and fills its parameters.
Everything the user then sees is computed by the existing deterministic API, so
a hallucinated number cannot reach the interface - the worst a bad model call
can do is route to the wrong screen.

The local matcher runs first and costs nothing. Only genuinely ambiguous input
reaches the model, which is what keeps token spend low.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence, Tuple


@dataclass(frozen=True)
class Action:
    """One thing the assistant can do."""

    name: str
    summary: str                       # one line, shown to the model
    roles: Tuple[str, ...]             # which roles may invoke it
    params: Dict[str, str] = field(default_factory=dict)
    patterns: Tuple[str, ...] = ()     # regexes for the free local matcher
    keywords: Tuple[str, ...] = ()     # scored fallback terms


# Roles: clinician | safety | compliance | researcher | any
ACTIONS: Tuple[Action, ...] = (
    Action(
        name="report_incident",
        summary="Report that a wrong entry was made, so its blast radius can be found.",
        roles=("safety", "researcher"),
        params={
            "family": "F1 wrong-patient alias | F2 wrong-chart copied fact | "
                      "F3 access-scope laundering | F4 stale corrected fact",
            "provenance": "complete | random20 | random40 | random60 | targeted",
        },
        patterns=(
            r"\b(i|we)\s+(accidentally|mistakenly|wrongly)?\s*(made|created|entered|filed|registered)\b",
            r"\bwrong\s+(patient|registration|chart|record|entry|name|mrn)\b",
            r"\breport\s+(an?\s+)?(error|incident|mistake|problem)\b",
            r"\bsomething\s+went\s+wrong\b",
            r"\bmixed\s+up\b",
        ),
        keywords=("report", "error", "mistake", "wrong", "incident", "accident",
                  "registration", "registered", "mixup", "misfiled"),
    ),
    Action(
        name="run_recovery",
        summary="Run the CARE containment loop on the open incident.",
        roles=("safety", "researcher"),
        patterns=(
            r"\b(run|start|begin|do|perform)\s+(the\s+)?(recovery|care|containment|repair|fix)\b",
            r"\b(fix|repair|contain|clean)\s+(it|this|that|the\s+\w+)\b",
            r"\bcontain\s+it\b",
        ),
        keywords=("recover", "recovery", "contain", "containment", "repair",
                  "fix", "clean", "remediate"),
    ),
    Action(
        name="show_blast_radius",
        summary="Show how far the error spread.",
        roles=("safety", "researcher"),
        patterns=(
            r"\b(blast\s*radius|how\s+far|spread|impact|affected\s+records)\b",
            r"\bwhat\s+(else\s+)?(was|got)\s+affected\b",
        ),
        keywords=("blast", "radius", "spread", "affected", "impact", "far"),
    ),
    Action(
        name="list_cases",
        summary="Open the case inbox and brief the user on work needing attention.",
        roles=("any",),
        patterns=(
            r"\b(case\s+inbox|list\s+(the\s+)?cases|show\s+(me\s+)?(the\s+)?cases)\b",
            r"\b(which|what)\s+cases?\s+(need|needs|require|requires)\s+attention\b",
        ),
        keywords=("case", "cases", "inbox", "worklist"),
    ),
    Action(
        name="show_case",
        summary="Open one incident case and explain its status, owner, timeline, and next action.",
        roles=("any",),
        params={"case_id": "case identifier such as INC-F1-T-ID-01"},
        patterns=(
            r"\b(open|show|brief|explain)\s+(me\s+)?(case|incident)\b",
            r"\bcase\s+inc-[a-z0-9-]+\b",
        ),
        keywords=("case", "incident", "open", "brief", "timeline"),
    ),
    Action(
        name="system_status",
        summary="Report what is happening right now: open incidents, affected records, what needs a person.",
        roles=("any",),
        patterns=(
            r"\b(any|are\s+there)\s+(open\s+)?(incidents?|problems?|issues?|errors?)\b",
            r"\b(current|system)\s+(state|status|situation)\b",
            r"\bwhat('?s| is)\s+(going\s+on|happening|the\s+(state|status|situation))\b",
            r"\bwhere\s+(are\s+we|do\s+(we|i)\s+stand)\b",
            r"\bstatus\b",
            r"\bcatch\s+me\s+up\b",
            r"\bbrief\s+me\b",
            r"\banything\s+(open|active|outstanding)\b",
        ),
        keywords=("status", "state", "situation", "incidents", "happening",
                  "going", "currently", "overview", "summary", "outstanding"),
    ),
    Action(
        name="fix_everything",
        summary="Handle an incident end to end: report it, run recovery, and report the outcome.",
        roles=("safety", "researcher"),
        params={
            "family": "F1 | F2 | F3 | F4",
            "provenance": "complete | random20 | random40 | random60 | targeted",
        },
        patterns=(
            r"\b(sort|handle|deal\s+with|take\s+care\s+of|clean\s+up)\b.{0,18}\b(it|this|that|everything|the\s+whole)\b",
            r"\bsort\s+it\s+out\b",
            r"\bdo\s+(the\s+)?(whole|everything|all\s+of\s+it)\b",
            r"\bfix\s+(it\s+)?all\b",
            r"\bend\s+to\s+end\b",
            r"\bwalk\s+me\s+through\b",
            r"\bdemo(nstrate)?\b",
            r"\bshow\s+me\s+the\s+whole\b",
        ),
        keywords=("everything", "whole", "demo", "walkthrough", "showcase"),
    ),
    Action(
        name="show_patient",
        summary="Open one patient's records and show what changed.",
        roles=("clinician", "researcher"),
        params={"patient": "patient name, MRN, or record id"},
        patterns=(
            r"\b(show|open|find|pull\s+up|look\s+up|check)\b.*\b(patient|record|chart)\b",
            r"\bwhat\s+changed\s+for\b",
            r"\bcan\s+i\s+trust\b",
        ),
        keywords=("patient", "record", "chart", "open", "show", "trust", "changed"),
    ),
    Action(
        name="list_patients",
        summary="List patients, optionally only those needing attention.",
        roles=("clinician", "researcher"),
        params={"filter": "all | attention | corrected | withdrawn | clear"},
        patterns=(
            r"\b(which|what|any)\s+patients?\b",
            r"\b(list|show)\s+(all\s+)?(my\s+)?patients?\b",
            r"\bwho\s+(needs|is)\s+affected\b",
            r"\banything\s+i\s+(need|should)\b",
        ),
        keywords=("patients", "list", "who", "attention", "affected", "everyone"),
    ),
    Action(
        name="show_boundary",
        summary="Show which fields crossed the policy boundary and which never leave.",
        roles=("compliance", "researcher"),
        patterns=(
            r"\b(what|which)\s+(data|fields?|information)\s+(left|crossed|shared|exported)\b",
            r"\b(data\s+)?boundary\b",
            r"\bdid\s+(anything|any\s+data)\s+leak\b",
            r"\bwas\s+anything\s+(shared|exposed|exported)\b",
        ),
        keywords=("boundary", "leaked", "exported", "shared", "crossed", "fields",
                  "privacy", "exposed"),
    ),
    Action(
        name="show_queue",
        summary="Show records the system held for a human decision.",
        roles=("compliance", "researcher"),
        patterns=(
            r"\b(review\s+queue|needs?\s+(my\s+)?(decision|review|approval))\b",
            r"\bwhat('?s| is| are)?\s+waiting\s+(on|for)\s+me\b",
            r"\banything\s+(waiting|to\s+(approve|review|decide))\b",
            r"\b(quarantined?|held)\s+records?\b",
        ),
        keywords=("queue", "review", "approve", "decision", "waiting", "held",
                  "quarantined", "escalated"),
    ),
    Action(
        name="run_leakage_tests",
        summary="Run the privacy attacks against our own recovery interface.",
        roles=("compliance", "researcher"),
        patterns=(
            r"\b(run|do)\s+(the\s+)?(leakage|privacy|attack)\b",
            r"\bhow\s+private\b",
            r"\bcan\s+(someone|anyone|an?\s+attacker)\s+(infer|learn|tell)\b",
        ),
        keywords=("leakage", "privacy", "attack", "infer", "membership",
                  "linkability", "private"),
    ),
    Action(
        name="switch_role",
        summary="Switch to a different role's console.",
        roles=("any",),
        params={"role": "clinician | safety | compliance | researcher"},
        patterns=(
            # "switch to the safety officer role", "take me to the nurse console",
            # "sign in as compliance" - the article and trailing noun are optional.
            r"\b(switch|change|log\s*in|sign\s*in|become|act|take\s+me)\s+"
            r"(to|as|in\s+as)?\s*(the\s+|a\s+)?"
            r"(nurse|clinician|doctor|safety|security|compliance|review|research)",
            r"\bi\s+am\s+(a\s+)?(nurse|clinician|doctor|safety|compliance|researcher)\b",
            r"\b(nurse|clinician|safety|compliance|researcher)\s+(console|view|role|side)\b",
        ),
        keywords=("switch", "role", "nurse", "clinician", "safety", "compliance",
                  "researcher", "login"),
    ),
    Action(
        name="navigate",
        summary="Open a named screen in the current role.",
        roles=("any",),
        params={"view": "records | command | assurance | overview | graph | "
                        "baselines | privacy | evidence | review | experiment | audit"},
        patterns=(
            r"\b(go\s+to|open|show\s+me\s+the)\s+(the\s+)?"
            r"(memory\s+graph|graph|audit|evidence|baselines|experiments?)\b",
        ),
        keywords=("open", "go", "navigate", "screen", "tab", "graph", "audit",
                  "evidence"),
    ),
    Action(
        name="explain",
        summary="Explain a term or what the current screen means. Answered locally.",
        roles=("any",),
        params={"topic": "the term to explain"},
        patterns=(
            r"\bwhat\s+(is|are|does)\b",
            r"\bwhat\s+do(es)?\s+.*\s+mean\b",
            r"\bexplain\b",
            r"\bhelp\b",
            r"\bhow\s+does\s+(this|it)\s+work\b",
            r"\b(tell|say)\s+me\s+more\b",
            r"\bwhat\s+(should|do)\s+i\s+(do|look\s+at)\b",
        ),
        keywords=("what", "explain", "mean", "help", "how", "why", "loop"),
    ),
    Action(
        name="reset_system",
        summary="Clear all incidents and start from a clean sandbox.",
        roles=("safety", "researcher", "compliance"),
        patterns=(
            r"\b(reset|clear|start\s+over|wipe|clean\s+slate)\b",
        ),
        keywords=("reset", "clear", "restart", "wipe", "fresh", "over"),
    ),
)

ACTIONS_BY_NAME = {a.name: a for a in ACTIONS}


def actions_for(role: str) -> List[Action]:
    return [a for a in ACTIONS if "any" in a.roles or role in a.roles]


# ----------------------------------------------------------------------
# Local, zero-cost intent matching
# ----------------------------------------------------------------------
FAMILY_HINTS = (
    ("F1", ("wrong patient", "wrong-patient", "registration", "registered", "alias",
            "name", "mrn", "identity", "mixed up", "wrong person")),
    ("F2", ("chart", "copied", "observation", "lab", "result", "value", "reading")),
    ("F3", ("restricted", "access", "permission", "confidential", "laundering",
            "shared", "leaked")),
    ("F4", ("stale", "outdated", "corrected", "old", "superseded", "out of date")),
)

ROLE_HINTS = (
    ("clinician", ("nurse", "clinician", "doctor", "physician", "ward", "patient care")),
    ("safety", ("safety", "security", "incident", "responder", "containment")),
    ("compliance", ("compliance", "privacy", "audit", "review", "governance", "dpo")),
    ("researcher", ("research", "evaluat", "experiment", "benchmark", "scientist")),
)

VIEW_HINTS = (
    ("graph", ("memory graph", "graph", "lineage map")),
    ("audit", ("audit log", "audit trail", "event log")),
    ("evidence", ("evidence", "validation", "seal")),
    ("baselines", ("baseline", "nine conditions", "comparison")),
    ("experiment", ("experiment", "matrix", "full run")),
    ("privacy", ("privacy audit", "leakage")),
    ("records", ("my patients", "patient list", "records")),
    ("command", ("incident command", "containment")),
    ("assurance", ("assurance", "compliance desk")),
)

PROVENANCE_HINTS = (
    ("complete", ("complete", "everything recorded", "full lineage", "all links")),
    ("targeted", ("worst", "targeted", "worst case", "hardest")),
    ("random60", ("severe", "most links", "60")),
    ("random40", ("degraded", "40")),
    ("random20", ("patchy", "20")),
)


# A model may echo a whole option description ("F1 wrong-patient alias") rather
# than the bare value. Normalise before anything downstream trusts it, or an
# F2 report silently becomes an F1 one.
VALID_VALUES = {
    "family": ("F1", "F2", "F3", "F4"),
    "provenance": ("complete", "random20", "random40", "random60", "targeted"),
    "role": ("clinician", "safety", "compliance", "researcher"),
    "view": ("records", "command", "assurance", "overview", "incident", "care",
             "graph", "baselines", "privacy", "evidence", "review", "experiment",
             "audit"),
    "filter": ("all", "attention", "checking", "corrected", "withdrawn", "clear"),
}


def normalise_param(key: str, value: Any) -> Any:
    """Reduce a loose value to a valid one, or drop it."""
    allowed = VALID_VALUES.get(key)
    if allowed is None or not isinstance(value, str):
        return value
    probe = value.strip().lower()
    for option in allowed:
        if probe == option.lower():
            return option
    # "F1 wrong-patient alias" -> F1; "nurse / clinician" -> clinician.
    for option in allowed:
        if re.search(rf"\b{re.escape(option.lower())}\b", probe):
            return option
    return None


def _first_hint(text: str, hints: Sequence[Tuple[str, Sequence[str]]]) -> Optional[str]:
    for value, needles in hints:
        if any(n in text for n in needles):
            return value
    return None


def match_local(message: str, role: str) -> Optional[Dict[str, Any]]:
    """Resolve an intent without calling any model.

    Returns None when the message is ambiguous enough that the model should
    decide, which is the only path that costs tokens.
    """
    text = " " + re.sub(r"[^a-z0-9\s'\-]", " ", message.lower()).strip() + " "
    if not text.strip():
        return None

    candidates = actions_for(role)
    scored: List[Tuple[float, Action]] = []

    for action in candidates:
        score = 0.0
        for pattern in action.patterns:
            if re.search(pattern, text):
                score += 3.0
                break
        hits = sum(1 for k in action.keywords if f" {k}" in text)
        score += hits * 0.9
        # `explain` matches on bare question words, so it must lose any tie with
        # a concrete action rather than swallowing "what is waiting for me".
        if action.name == "explain":
            score -= 1.2
        if score > 0:
            scored.append((score, action))

    if not scored:
        return None
    scored.sort(key=lambda pair: pair[0], reverse=True)
    best_score, best = scored[0]
    runner_up = scored[1][0] if len(scored) > 1 else 0.0

    # A pattern hit that clearly beats the alternatives is safe to act on.
    # Anything closer than that is exactly the case worth spending a token on.
    if best_score < 3.0 or (best_score - runner_up) < 1.0:
        return None

    return {
        "action": best.name,
        "params": extract_params(best.name, text),
        "source": "local",
    }


def extract_params(action_name: str, text: str) -> Dict[str, Any]:
    """Pull the few parameters our actions take straight out of the text."""
    params: Dict[str, Any] = {}
    if action_name == "report_incident":
        params["family"] = _first_hint(text, FAMILY_HINTS) or "F1"
        params["provenance"] = _first_hint(text, PROVENANCE_HINTS) or "targeted"
    elif action_name == "switch_role":
        role = _first_hint(text, ROLE_HINTS)
        if role:
            params["role"] = role
    elif action_name == "navigate":
        view = _first_hint(text, VIEW_HINTS)
        if view:
            params["view"] = view
    elif action_name == "list_patients":
        for value, needles in (
            ("attention", ("attention", "urgent", "problem", "needs")),
            ("corrected", ("corrected", "fixed", "repaired")),
            ("withdrawn", ("withdrawn", "removed")),
        ):
            if any(n in text for n in needles):
                params["filter"] = value
                break
        params.setdefault("filter", "all")
    elif action_name == "show_patient":
        # A capitalised name in the ORIGINAL message is the best signal, but the
        # lowercased text still carries MRNs and record ids.
        mrn = re.search(r"\b(mrn\s*\w+|s\d{3,})\b", text)
        if mrn:
            params["patient"] = mrn.group(1).replace(" ", "").upper()
    elif action_name == "show_case":
        case_id = re.search(r"\binc-[a-z0-9-]+\b", text)
        if case_id:
            params["case_id"] = case_id.group(0).upper()
    elif action_name == "explain":
        params["topic"] = text.strip()
    return params


__all__ = ["Action", "ACTIONS", "ACTIONS_BY_NAME", "actions_for", "match_local",
           "extract_params", "normalise_param", "VALID_VALUES"]
