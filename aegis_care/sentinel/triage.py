"""Manual entry and briefing for the Sentinel.

Manual reports are the fallback for anything the detectors cannot see. A
person types what looks wrong in their own words; the Sentinel turns that into
a structured concern, cross-checks it against the live detectors for the same
patient, and files it in the registry - so a report is never just a note in a
queue, it arrives with whatever evidence already corroborates it.

Gemini is used when a key is configured, and only for two narrow jobs:
classifying free text, and writing a short situation brief from finding
metadata. Neither job lets the model state a finding: classifications are
cross-checked by deterministic detectors, and the brief is given counts and
rule names, never record content. Without a key both jobs run locally.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
from typing import Any, Dict, List, Optional

from ..assistant import gemini

CATEGORIES = {
    "wrong_patient": {"label": "Wrong patient", "severity": "high",
                      "rules": ["identity_reresolve", "work_order", "lineage_drift",
                                "evidence_ownership", "source_identity"]},
    "stale_value": {"label": "Outdated value", "severity": "medium",
                    "rules": ["stale_value", "source_invalid"]},
    "restricted_exposure": {"label": "Restricted information shown", "severity": "high",
                            "rules": ["restricted_exposure"]},
    "source_mismatch": {"label": "Source record filed wrongly", "severity": "medium",
                        "rules": ["source_identity", "source_invalid", "held_transfer"]},
    "assistant_answer": {"label": "Assistant answer looks wrong", "severity": "medium",
                         "rules": ["identity_reresolve", "work_order", "lineage_drift",
                                   "evidence_ownership", "stale_value", "inherited_withdrawn"]},
    "other": {"label": "Other concern", "severity": "low", "rules": []},
}

_KEYWORDS = [
    ("restricted_exposure", r"restricted|confidential|psych|substance|behaviou?ral|"
                            r"shouldn'?t (be able to )?see|not allowed to see|private|hiv"),
    ("wrong_patient", r"wrong patient|not (my|this|the right) patient|different patient|"
                      r"someone else|another patient|mixed up|mix-?up|swapped|"
                      r"belongs to|wrong (name|mrn|person|dob)"),
    ("stale_value", r"\bold\b|outdated|stale|was corrected|out of date|previous value|"
                    r"no longer|superseded|changed since|amended"),
    ("source_mismatch", r"misfiled|filed (in|under)|wrong chart|in (the )?wrong record|"
                        r"source record|transfer|handover blocked"),
    ("assistant_answer", r"assistant|\bai\b|summary|handover said|told me|suggested|"
                         r"memory|hallucinat"),
]

_BUDGET = {"calls": 0}
MAX_CALLS = int(os.environ.get("AEGIS_SENTINEL_MAX_CALLS", "80"))


def model_available() -> bool:
    return gemini.configured() and _BUDGET["calls"] < MAX_CALLS


def _call_model(system: str, user: str, schema: Dict[str, Any], max_tokens: int):
    if not model_available():
        raise gemini.AssistantUnavailable("model not configured or budget spent")
    _BUDGET["calls"] += 1
    return gemini.generate_json(system, user, schema, max_output_tokens=max_tokens)


# ======================================================================
# Patient + record extraction
# ======================================================================
def extract_refs(text: str, registry) -> Dict[str, Any]:
    ids = re.findall(r"\bS1\d{3}\b", text, re.I)
    mrns = re.findall(r"\bMRN\s?(\d{5,})\b", text, re.I)
    records = re.findall(r"\b(?:Observation|Condition|Encounter|MedicationRequest)/[A-Za-z0-9-]+",
                         text)
    candidates: List[str] = [i.upper() for i in ids]
    if registry is not None:
        lowered = text.lower()
        for patient in registry.patients():
            name = patient["name"].lower()
            if name and name in lowered:
                candidates.append(patient["id"])
            elif patient["mrn"] and any(patient["mrn"].endswith(m) for m in mrns):
                candidates.append(patient["id"])
            else:
                family = name.split()[-1] if name else ""
                given = name.split()[0] if name else ""
                if family and given and re.search(rf"\b{re.escape(given)}\b", lowered) \
                        and re.search(rf"\b{re.escape(family)}\b", lowered):
                    candidates.append(patient["id"])
    seen: List[str] = []
    for c in candidates:
        if c not in seen:
            seen.append(c)
    return {"patients": seen, "records": records}


def _local_classify(text: str) -> Dict[str, Any]:
    lowered = text.lower()
    for category, pattern in _KEYWORDS:
        if re.search(pattern, lowered):
            break
    else:
        category = "other"
    info = CATEGORIES[category]
    return {"category": category, "severity": info["severity"],
            "summary": "", "patient_ref": "", "reasoning": "keyword match"}


TRIAGE_SCHEMA = {
    "type": "object",
    "properties": {
        "category": {"type": "string", "enum": list(CATEGORIES)},
        "severity": {"type": "string", "enum": ["critical", "high", "medium", "low"]},
        "concern_type": {"type": "string", "enum": ["source_record", "assistant_memory"]},
        "patient_ref": {"type": "string"},
        "summary": {"type": "string"},
        "reasoning": {"type": "string"},
    },
    "required": ["category", "severity", "concern_type", "summary"],
}

TRIAGE_SYSTEM = (
    "You triage error reports for a clinical-AI safety console that uses synthetic "
    "patients only. Classify the report.\n"
    "Categories: wrong_patient (information belongs to a different patient), "
    "stale_value (a value that has since been corrected), restricted_exposure "
    "(physician-only or confidential information shown to someone who should not see "
    "it), source_mismatch (a source record filed in the wrong chart or a blocked "
    "handover), assistant_answer (the assistant's answer or summary looks wrong in "
    "another way), other.\n"
    "concern_type is assistant_memory when the problem is in something the assistant "
    "said, summarised or remembered; source_record when it is in the underlying chart.\n"
    "patient_ref: copy the patient name, ID (like S1042) or MRN exactly as written in "
    "the report, or empty.\n"
    "summary: one neutral sentence restating the concern. Never add facts, values or "
    "diagnoses that are not in the report.\n"
    "reasoning: at most 12 words."
)


def triage(text: str, *, registry, run_detectors, patient_id: Optional[str] = None,
           record_key: Optional[str] = None, file_report: bool = True) -> Dict[str, Any]:
    text = (text or "").strip()
    if len(text) < 10:
        raise ValueError("Describe what looks wrong in at least 10 characters.")

    steps: List[Dict[str, str]] = []
    refs = extract_refs(text, registry)
    source, tokens = "local", None
    try:
        reply = _call_model(TRIAGE_SYSTEM, text[:900], TRIAGE_SCHEMA, 220)
        result = reply["data"]
        tokens = reply["tokens"]
        source = "gemini"
        steps.append({"phase": "understand",
                      "text": "Gemini classified the report "
                              f"({tokens.get('input', 0)}+{tokens.get('output', 0)} tokens)."})
    except gemini.AssistantUnavailable as exc:
        result = _local_classify(text)
        steps.append({"phase": "understand",
                      "text": "Classified locally" + ("" if not gemini.configured()
                                                      else f" (Gemini unavailable: {exc})") + "."})
    category = result.get("category") if result.get("category") in CATEGORIES else "other"
    severity = result.get("severity") or CATEGORIES[category]["severity"]
    concern_type = result.get("concern_type")
    if concern_type not in ("source_record", "assistant_memory"):
        concern_type = "source_record" if category == "source_mismatch" else "assistant_memory"
    if record_key or refs["records"]:
        record_key = record_key or refs["records"][0]
        if category == "source_mismatch":
            concern_type = "source_record"

    # Resolve the patient: explicit choice > model reference > text extraction.
    resolved = patient_id
    if not resolved and result.get("patient_ref"):
        model_refs = extract_refs(result["patient_ref"], registry)["patients"]
        resolved = model_refs[0] if model_refs else None
    if not resolved and refs["patients"]:
        resolved = refs["patients"][0]
    if resolved and registry is not None and not registry.patient(resolved):
        resolved = None
    steps.append({"phase": "resolve",
                  "text": f"Matched patient {resolved}." if resolved else
                          "No patient could be identified from the text."})

    # Cross-check against the live detectors for that patient.
    corroboration: List[Dict[str, Any]] = []
    if resolved:
        wanted = set(CATEGORIES[category]["rules"]) or None
        for f in run_detectors(resolved):
            if f["rule"] == "human_report":
                continue
            corroboration.append({**f, "relevant": wanted is None or f["rule"] in wanted})
        corroboration.sort(key=lambda f: (not f["relevant"], f["severity"]))
        relevant = sum(1 for f in corroboration if f["relevant"])
        steps.append({"phase": "corroborate",
                      "text": (f"{relevant} detector finding(s) corroborate the report."
                               if relevant else
                               "No detector currently corroborates it; a person must review.")})
        if relevant and severity in ("low", "medium") and \
                any(f["severity"] in ("critical", "high") for f in corroboration if f["relevant"]):
            severity = "high"

    filed = None
    if file_report and resolved:
        if record_key and concern_type == "source_record":
            # A record key must belong to this chart; otherwise file without it.
            charted = {r["record_key"] for r in registry.records(resolved)}
            record_key = record_key if record_key in charted else None
        try:
            filed = registry.report(resolved, record_key if concern_type == "source_record" else None,
                                    text[:1000], concern_type)
            steps.append({"phase": "file",
                          "text": ("Filed for safety triage." if concern_type == "assistant_memory"
                                   else "Filed for compliance review.")
                                  + f" Report #{filed['id']}."})
        except (KeyError, ValueError) as exc:
            steps.append({"phase": "file", "text": f"Not filed: {exc}"})

    return {
        "category": category,
        "category_label": CATEGORIES[category]["label"],
        "severity": severity,
        "concern_type": concern_type,
        "summary": result.get("summary") or "",
        "reasoning": result.get("reasoning") or "",
        "patient_id": resolved,
        "candidates": refs["patients"][:5],
        "record_key": record_key,
        "source": source,
        "tokens": tokens,
        "corroboration": corroboration[:8],
        "filed": filed,
        "steps": steps,
    }


# ======================================================================
# Situation brief
# ======================================================================
_BRIEF_CACHE: Dict[str, Dict[str, Any]] = {}

BRIEF_SCHEMA = {
    "type": "object",
    "properties": {"headline": {"type": "string"}, "brief": {"type": "string"},
                   "next_step": {"type": "string"}},
    "required": ["headline", "brief", "next_step"],
}

BRIEF_SYSTEM = (
    "You write the situation brief for a clinical-AI memory safety officer. You receive "
    "JSON describing what an automated sentinel found. Write: headline (max 9 words), "
    "brief (2 sentences, plain language, no jargon), next_step (one imperative sentence). "
    "Use only numbers and facts present in the JSON. Never invent patient details."
)


def _brief_facts(patrol: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "posture": patrol["posture"]["label"],
        "memories_scanned": patrol["observed"]["memories"],
        "source_records_scanned": patrol["observed"]["source_records"],
        "lineage_coverage": patrol["observed"]["lineage"]["coverage"],
        "open_cases": [{"title": c["title"], "severity": c["severity"],
                        "affected": len(c["members"]), "roots": len(c["roots"]),
                        "patients": len(c["patients"])} for c in patrol["cases"][:5]],
        "source_items": len(patrol["source_findings"]),
        "contained_this_patrol": [{"repaired": a["repaired"], "held": a["quarantined"],
                                   "safe_resume": a["safe_resume"]} for a in patrol["acted"]],
        "autopilot": patrol["autopilot"],
    }


def _local_brief(facts: Dict[str, Any]) -> Dict[str, str]:
    cases = facts["open_cases"]
    acted = facts["contained_this_patrol"]
    if acted:
        rebuilt = sum(a["repaired"] for a in acted)
        held = sum(a["held"] for a in acted)
        return {"headline": f"{len(acted)} incident(s) contained automatically",
                "brief": (f"The sentinel found and contained {len(acted)} memory incident(s), "
                          f"rebuilding {rebuilt} record(s) from FHIR"
                          + (f" and holding {held} for review." if held else ".")
                          + " A follow-up scan confirmed no servable memory still trips a detector."),
                "next_step": ("Review the held records in Assurance." if held else
                              "Spot-check the recovery certificates, then clear the source items.")}
    if cases:
        top = cases[0]
        affected = sum(c["affected"] for c in cases)
        return {"headline": f"{len(cases)} open memory incident(s)",
                "brief": (f"The most serious is \"{top['title']}\" ({top['severity']}). "
                          f"{affected} servable memor{'y is' if affected == 1 else 'ies are'} "
                          "affected and could still be retrieved by the assistant."),
                "next_step": "Contain the top case now, or switch on autopilot."}
    if facts["source_items"]:
        return {"headline": "Memory clean; source items open",
                "brief": (f"All {facts['memories_scanned']} memories pass every check. "
                          f"{facts['source_items']} source-record item(s) still need a person."),
                "next_step": "Work through the source queue below."}
    return {"headline": "All clear",
            "brief": (f"{facts['memories_scanned']} memories and "
                      f"{facts['source_records_scanned']} source records pass every check."),
            "next_step": "Run a blind drill to prove the sentinel catches a planted fault."}


def brief(patrol: Dict[str, Any], use_model: bool = True) -> Dict[str, Any]:
    facts = _brief_facts(patrol)
    fingerprint = hashlib.sha256(json.dumps(facts, sort_keys=True).encode()).hexdigest()
    if fingerprint in _BRIEF_CACHE:
        return {**_BRIEF_CACHE[fingerprint], "cached": True}
    out: Dict[str, Any]
    if use_model and model_available():
        try:
            reply = _call_model(BRIEF_SYSTEM, json.dumps(facts), BRIEF_SCHEMA, 180)
            out = {**_local_brief(facts), **{k: v for k, v in reply["data"].items() if v},
                   "source": "gemini", "tokens": reply["tokens"]}
        except gemini.AssistantUnavailable:
            out = {**_local_brief(facts), "source": "local"}
    else:
        out = {**_local_brief(facts), "source": "local"}
    if len(_BRIEF_CACHE) > 64:
        _BRIEF_CACHE.clear()
    _BRIEF_CACHE[fingerprint] = out
    return {**out, "cached": False}


def status() -> Dict[str, Any]:
    return {"configured": gemini.configured(), "model": gemini.DEFAULT_MODEL,
            "calls": _BUDGET["calls"], "budget": MAX_CALLS}


__all__ = ["triage", "brief", "status", "extract_refs", "CATEGORIES"]
