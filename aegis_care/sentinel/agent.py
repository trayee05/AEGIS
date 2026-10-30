"""The Sentinel agent: observe -> detect -> correlate -> decide -> act -> verify.

A patrol is one pass of that loop. It is deterministic and cheap enough to run
every few seconds. Two things are deliberately left to people:

* The agent may *contain* (dispatch CARE on a root it found). CARE itself
  quarantines anything it cannot rebuild, so containment never guesses.
* The agent never *corrects* a source chart on its own. It proposes the
  refile, shows the FHIR evidence, and a reviewer approves it.

Autopilot only changes who presses "contain"; it never widens what the agent
is allowed to do.
"""
from __future__ import annotations

import hashlib
import random
import threading
import time
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional, Set

from ..care.coordinator import CAREOptions, RecoveryCoordinator
from ..incident.masks import ProvenanceMask
from ..incident.scenarios import FAMILIES, FAMILY_INFO
from .detectors import DETECTORS, DetectorSuite, Finding, SEVERITY_RANK

CONTAINABLE = {"identity_reresolve", "work_order", "lineage_drift", "evidence_ownership",
               "stale_value", "restricted_exposure", "inherited_withdrawn", "integrity"}

CASE_TITLES = {
    "identity_reresolve": "Wrong-patient alias in assistant memory",
    "work_order": "Memory names the wrong patient for its task",
    "lineage_drift": "Wrong-chart fact copied into a derived note",
    "evidence_ownership": "Memory cites another patient's results",
    "stale_value": "Memory asserts values that were since corrected",
    "restricted_exposure": "Restricted field laundered into shared memory",
    "inherited_withdrawn": "Memory still built on a withdrawn record",
    "integrity": "Memory content changed after it was sealed",
}
#: When several rules fire in one case, the title comes from the most causal one.
TITLE_PRIORITY = ["identity_reresolve", "restricted_exposure", "integrity", "lineage_drift",
                  "evidence_ownership", "stale_value", "work_order", "inherited_withdrawn"]

LIKELY_FAMILY = {"identity_reresolve": "F1", "lineage_drift": "F2",
                 "evidence_ownership": "F2", "restricted_exposure": "F3",
                 "stale_value": "F4", "work_order": "F1/F2"}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class Sentinel:
    """Holds patrol history, contained cases, and blind drills."""

    def __init__(self, get_env: Callable[[], Any], registry, lock: threading.Lock,
                 builder_factory: Optional[Callable[[], Any]] = None) -> None:
        self._get_env = get_env
        self.registry = registry
        self.lock = lock
        self.builder_factory = builder_factory
        self.reset()

    def reset(self) -> None:
        self.patrols = 0
        self.last: Optional[Dict[str, Any]] = None
        self.contained: Dict[str, Dict[str, Any]] = {}
        self.results: Dict[str, Any] = {}
        self.drills: Dict[str, Dict[str, Any]] = {}
        self.activity: List[Dict[str, Any]] = []
        self.first_seen: Dict[str, str] = {}

    @property
    def env(self):
        return self._get_env()

    # ==================================================================
    # The loop
    # ==================================================================
    def patrol(self, *, autopilot: bool = False,
               patient: Optional[str] = None) -> Dict[str, Any]:
        trace: List[Dict[str, Any]] = []
        t0 = time.perf_counter()

        def step(phase: str, text: str, **extra: Any) -> None:
            trace.append({"phase": phase, "text": text,
                          "ms": round((time.perf_counter() - t0) * 1000, 1), **extra})

        # --- observe + detect --------------------------------------------
        suite = DetectorSuite(self.env, self.registry)
        scan = suite.run(patient_filter=patient)
        obs = scan["observed"]
        step("observe",
             f"Read {obs['memories']} memories across {obs['runtimes']} runtimes "
             f"({obs['servable']} servable) and {obs['source_records']} source records.")
        findings: List[Finding] = scan["findings"]
        fired = [d for d in DETECTORS if scan["hits"].get(d["id"])
                 and d["id"] != "provenance_gap"]
        step("detect",
             f"{len(DETECTORS)} detectors ran; {len(findings)} finding(s) from "
             f"{len(fired)} detector(s)." if findings else
             f"{len(DETECTORS)} detectors ran; nothing anomalous.",
             detectors=[d["id"] for d in fired])
        if obs["lineage"]["unlinked"]:
            step("detect",
                 f"{obs['lineage']['unlinked']} derived memories have no recorded parent; "
                 "containment will rely on latent search for those.")

        # --- correlate -----------------------------------------------------
        cases = self._correlate(findings, scan["artifacts"])
        source_items = [f for f in findings if f.domain == "source"]
        if cases:
            roots = sum(len(c["roots"]) for c in cases)
            step("correlate",
                 f"Traced {sum(len(c['members']) for c in cases)} memory finding(s) to "
                 f"{roots} root cause(s) in {len(cases)} case(s); "
                 f"{sum(len(c['at_risk']) for c in cases)} more downstream at risk.")
        else:
            step("correlate", "No memory incident to correlate.")

        # --- decide --------------------------------------------------------
        for case in cases:
            step("decide", f"{case['case_id']}: {case['plan']['label']} - {case['plan']['why']}",
                 case=case["case_id"])
        fixable = [f for f in source_items if f.action]
        if fixable:
            step("decide",
                 f"{len(fixable)} chart mismatch(es) have FHIR-verified fixes; "
                 "queued for a reviewer (the agent never refiles a chart on its own).")

        # --- act + verify --------------------------------------------------
        acted: List[Dict[str, Any]] = []
        if autopilot and cases:
            for case in cases:
                outcome = self._contain(case, actor="sentinel-autopilot")
                acted.append(outcome)
                waves = len(outcome["waves"])
                step("act",
                     f"Contained {case['case_id']}: seeded CARE at 1 root, "
                     f"{outcome['repaired']} rebuilt from FHIR, {outcome['withdrawn']} withdrawn, "
                     f"{outcome['quarantined']} held for review"
                     + (f" ({waves} waves)." if waves > 1 else "."), case=case["case_id"])
            verify = DetectorSuite(self.env, self.registry).run(patient_filter=patient)
            residual = [f for f in verify["findings"] if f.domain == "memory"
                        and f.rule in CONTAINABLE]
            step("verify",
                 "Re-scan clean: no servable memory still trips a detector."
                 if not residual else
                 f"Re-scan found {len(residual)} residual finding(s); escalating.",
                 ok=not residual)
            findings = verify["findings"]
            cases = self._correlate(findings, verify["artifacts"])
            scan = verify
        elif cases:
            step("act", "Autopilot is off. Containment plans are waiting for approval.")
        else:
            step("verify", "All servable memory passes every check." if not findings
                 else "Memory is clean; remaining items are source-record work.", ok=True)

        self.patrols += 1
        now = _now()
        for f in findings:
            self.first_seen.setdefault(f.id, now)
        self._score_drills(findings, cases)

        severity = Counter_by(findings, "severity")
        result = {
            "patrol": self.patrols,
            "at": now,
            "elapsed_ms": round((time.perf_counter() - t0) * 1000, 1),
            "autopilot": autopilot,
            "scope": patient,
            "observed": scan["observed"],
            "hits": scan["hits"],
            "severity": severity,
            "cases": cases,
            "findings": [self._finding_dict(f) for f in findings],
            "trace": trace,
            "acted": acted,
            "contained": list(self.contained.values())[-8:][::-1],
            "drills": [self._public_drill(d) for d in self.drills.values()][::-1][:6],
            "posture": self._posture(findings, cases),
        }
        # Source findings come from the post-action scan when autopilot ran.
        result["source_findings"] = [d for d in result["findings"] if d["domain"] == "source"]
        self.last = result
        return result

    # ==================================================================
    def _finding_dict(self, f: Finding) -> Dict[str, Any]:
        data = f.to_dict()
        data["first_seen"] = self.first_seen.get(f.id)
        return data

    def _posture(self, findings: List[Finding], cases: List[Dict[str, Any]]) -> Dict[str, Any]:
        crit = sum(1 for f in findings if f.severity == "critical")
        high = sum(1 for f in findings if f.severity == "high")
        if crit or any(c["severity"] == "critical" for c in cases):
            level, label = "critical", "Active memory incident"
        elif cases or high:
            level, label = "elevated", "Errors need attention"
        elif findings:
            level, label = "watch", "Minor items open"
        else:
            level, label = "clear", "All clear"
        return {"level": level, "label": label, "open_cases": len(cases),
                "findings": len(findings)}

    # ------------------------------------------------------------------
    def _correlate(self, findings: List[Finding], artifacts) -> List[Dict[str, Any]]:
        """Group memory findings into cases and find each case's root causes.

        A root is a flagged memory none of whose explicit ancestors is flagged.
        Grouping uses the session the memory was written in, so one poisoned
        trajectory becomes one case even when its lineage has been lost.
        """
        memory = [f for f in findings if f.domain == "memory" and f.rule in CONTAINABLE]
        if not memory:
            return []
        by_key = {a.key: a for a in artifacts}
        by_commitment = {a.commitment(): a for a in artifacts}
        children: Dict[str, List[str]] = {}
        for a in artifacts:
            for c in a.explicit_parent_commitments:
                parent = by_commitment.get(c)
                if parent is not None:
                    children.setdefault(parent.key, []).append(a.key)

        flagged: Dict[str, List[Finding]] = {}
        for f in memory:
            flagged.setdefault(f.subject, []).append(f)

        def parents_of(key: str) -> List[str]:
            art = by_key.get(key)
            if art is None:
                return []
            return [by_commitment[c].key for c in art.explicit_parent_commitments
                    if c in by_commitment]

        def has_flagged_ancestor(key: str) -> bool:
            seen: Set[str] = set()
            stack = parents_of(key)
            while stack:
                k = stack.pop()
                if k in seen:
                    continue
                seen.add(k)
                if k in flagged and by_key.get(k) is not None and by_key[k].is_servable():
                    return True
                stack.extend(parents_of(k))
            return False

        groups: Dict[str, List[str]] = {}
        for key, fs in flagged.items():
            group = fs[0].session_id or key
            groups.setdefault(group, []).append(key)

        cases: List[Dict[str, Any]] = []
        for group, keys in groups.items():
            roots = sorted(k for k in keys if not has_flagged_ancestor(k))
            if not roots:
                roots = sorted(keys)[:1]
            # A memory whose only fault is a held parent is a symptom; prefer
            # causal roots when the case has any.
            causal = [k for k in roots
                      if any(f.rule != "inherited_withdrawn" for f in flagged[k])]
            roots = causal or roots

            at_risk: Set[str] = set()
            stack = list(keys)
            while stack:
                k = stack.pop()
                for child in children.get(k, []):
                    if child not in flagged and child not in at_risk and \
                            by_key[child].is_servable():
                        at_risk.add(child)
                        stack.append(child)

            rules = sorted({f.rule for k in keys for f in flagged[k]},
                           key=TITLE_PRIORITY.index)
            sev = min((f.severity for k in keys for f in flagged[k]),
                      key=SEVERITY_RANK.__getitem__)
            patients = sorted({f.patient_id for k in keys for f in flagged[k] if f.patient_id})
            task_id = next((f.task_id for k in keys for f in flagged[k] if f.task_id), None)
            case_id = "SC-" + hashlib.sha256("|".join(sorted(roots)).encode()).hexdigest()[:6].upper()
            depth_order = {"identity_hint": 0, "lookup_strategy": 1, "observation_summary": 2,
                           "handover": 2, "clinical_summary": 3, "aggregate": 4}
            members = sorted(keys, key=lambda k: (depth_order.get(
                by_key[k].artifact_type.value if k in by_key else "", 9), k))
            confidence = round(max(f.confidence for k in keys for f in flagged[k]), 2)
            family = LIKELY_FAMILY.get(rules[0])
            cases.append({
                "case_id": case_id,
                "title": CASE_TITLES[rules[0]],
                "severity": sev,
                "rules": rules,
                "likely_family": family,
                "family_name": FAMILY_INFO.get(family, {}).get("name") if family in FAMILY_INFO else None,
                "roots": roots,
                "members": [{"key": k, "type": by_key[k].artifact_type.value if k in by_key else None,
                             "owner": by_key[k].owner.value if k in by_key else None,
                             "root": k in roots,
                             "rules": sorted({f.rule for f in flagged[k]}),
                             "summary": flagged[k][0].summary,
                             "evidence": flagged[k][0].evidence}
                            for k in members],
                "at_risk": sorted(at_risk),
                "patients": patients,
                "task_id": task_id,
                "session": group,
                "confidence": confidence,
                "plan": {
                    "action": "contain",
                    "label": "Contain with CARE",
                    "why": ("seed CARE at the earliest root; it confirms influence by "
                            "counterfactual replay, rebuilds from FHIR, holds what it cannot "
                            "rebuild, then the agent re-scans and repeats if needed"),
                },
            })
        cases.sort(key=lambda c: (SEVERITY_RANK[c["severity"]], -len(c["members"])))
        return cases

    # ------------------------------------------------------------------
    def contain(self, case_id: str, actor: str = "reviewer") -> Dict[str, Any]:
        scan = DetectorSuite(self.env, self.registry).run()
        cases = self._correlate(scan["findings"], scan["artifacts"])
        case = next((c for c in cases if c["case_id"] == case_id), None)
        if case is None:
            if case_id in self.contained:
                return {**self.contained[case_id], "already": True}
            raise KeyError(f"case {case_id} is no longer open")
        return self._contain(case, actor=actor)

    def _contain(self, case: Dict[str, Any], actor: str) -> Dict[str, Any]:
        """Contain one case in waves.

        CARE withdraws its seeds and *rebuilds* what it confirms downstream. So
        the agent seeds only the earliest root and lets CARE's lineage walk and
        latent search find the rest; it then re-scans, and only memories that
        CARE did not reach become seeds for a follow-up wave. Seeding every
        flagged memory at once would withdraw records that could be rebuilt.
        """
        env = self.env
        base_id = case["case_id"]
        if base_id in self.contained:
            base_id = f"{base_id}-{len(self.contained) + 1}"
        task = next((t for t in env.tasks if t["task_id"] == case["task_id"]), None)
        member_keys = [m["key"] for m in case["members"]]
        root_order = [k for k in member_keys if k in case["roots"]] or case["roots"]
        env.ledger.log_event(base_id, "sentinel", "incident_reported", root_order[0],
                             {"source": "sentinel", "actor": actor, "rules": case["rules"],
                              "roots": case["roots"], "affected": len(member_keys)})
        started = time.perf_counter()
        waves: List[Dict[str, Any]] = []
        seeds = root_order[:1]
        totals = {"confirmed": 0, "cleared": 0, "repaired": 0, "quarantined": 0, "rounds": 0}
        certificates: List[str] = []
        safe = True
        closure = True
        for wave in range(1, 5):
            incident_id = base_id if wave == 1 else f"{base_id}.w{wave}"
            result = RecoveryCoordinator(env).recover(
                incident_id, seeds, options=CAREOptions(),
                followup_tasks=[task] if task else None)
            self.results[incident_id] = result
            for k in totals:
                value = getattr(result, k) if k == "rounds" else len(getattr(result, k))
                totals[k] += value
            cert = result.certificate
            safe = safe and bool(cert and cert.safe_resume)
            closure = closure and result.closure_reached
            if cert:
                certificates.append(cert.to_text())
            waves.append({"wave": wave, "incident_id": incident_id, "seeds": list(seeds),
                          "confirmed": len(result.confirmed), "repaired": len(result.repaired),
                          "quarantined": len(result.quarantined)})
            # Verify: anything in this case still servable and still flagged?
            rescan = DetectorSuite(env, self.registry).run()
            residual = {f.subject for f in rescan["findings"]
                        if f.domain == "memory" and f.rule in CONTAINABLE
                        and (f.subject in member_keys or
                             (case["session"] and f.session_id == case["session"]))}
            if not residual:
                break
            ordered = [k for k in member_keys if k in residual] + \
                sorted(residual - set(member_keys))
            seeds = ordered[:1]
        outcome = {
            "case_id": case["case_id"],
            "incident_id": base_id,
            "title": case["title"],
            "actor": actor,
            "at": _now(),
            "roots": case["roots"],
            "flagged": len(member_keys),
            **totals,
            "withdrawn": sum(len(w["seeds"]) for w in waves),
            "waves": waves,
            "closure": closure,
            "safe_resume": safe,
            "seconds": round(time.perf_counter() - started, 3),
            "certificate_text": ("\n\n".join(certificates)),
            "patients": case["patients"],
        }
        self.contained[case["case_id"]] = outcome
        self.activity.append({"at": outcome["at"], "kind": "contained",
                              "text": f"{actor} contained {case['case_id']}"})
        return outcome

    # ==================================================================
    # Blind drills: plant a fault the Sentinel is not told about
    # ==================================================================
    def drill(self, family: Optional[str], provenance: str, register) -> Dict[str, Any]:
        env = self.env
        rng = random.Random(time.time_ns())
        family = family if family in FAMILIES else rng.choice(FAMILIES)
        used = {d["task_id"] for d in self.drills.values()}
        candidates = [t for t in env.tasks if t["task_id"] not in used] or env.tasks
        task = rng.choice(candidates)
        drill_id = f"DRILL-{len(self.drills) + 1:02d}"
        incident = self.builder_factory().build(family, task, incident_id=drill_id,
                                                depth=4, n_controls=1)
        mask = ProvenanceMask(env, rng.randrange(1 << 30)).apply(
            provenance, scope_keys=incident.all_keys())
        register(incident, mask)
        self.drills[drill_id] = {
            "drill_id": drill_id, "family": family, "provenance": provenance,
            "task_id": task["task_id"], "planted_at": _now(), "incident": incident,
            "detected_at": None, "detected_patrol": None, "score": None,
        }
        self.activity.append({"at": _now(), "kind": "drill",
                              "text": f"{drill_id} planted (family hidden)"})
        return {"drill_id": drill_id, "provenance": provenance,
                "message": "A fault was planted somewhere in assistant memory. "
                           "The Sentinel has not been told where or what kind."}

    def _score_drills(self, findings: List[Finding], cases: List[Dict[str, Any]]) -> None:
        flagged = {f.subject for f in findings if f.domain == "memory"}
        flagged |= {k for c in cases for k in c["at_risk"]}
        for drill in self.drills.values():
            if drill["score"] is not None:
                continue
            inc = drill["incident"]
            truth = set(inc.true_contaminated) | {inc.seed_key}
            hit = truth & flagged
            if not hit:
                continue
            clean = set(inc.clean_keys)
            drill["detected_at"] = _now()
            drill["detected_patrol"] = self.patrols
            drill["score"] = {
                "found": len(hit), "planted": len(truth),
                "recall": round(len(hit) / len(truth), 3) if truth else 1.0,
                "seed_found": inc.seed_key in flagged,
                "clean_flagged": len(clean & flagged),
                "clean_total": len(clean),
            }

    @staticmethod
    def _public_drill(d: Dict[str, Any]) -> Dict[str, Any]:
        """Family stays hidden until the Sentinel has found the drill."""
        found = d["score"] is not None
        return {"drill_id": d["drill_id"], "provenance": d["provenance"],
                "planted_at": d["planted_at"], "detected_at": d["detected_at"],
                "status": "detected" if found else "hidden",
                "family": d["family"] if found else None,
                "family_name": FAMILY_INFO[d["family"]]["name"] if found else None,
                "score": d["score"]}


def Counter_by(findings: List[Finding], attr: str) -> Dict[str, int]:
    out: Dict[str, int] = {}
    for f in findings:
        key = getattr(f, attr)
        out[key] = out.get(key, 0) + 1
    return out


__all__ = ["Sentinel", "CONTAINABLE"]
