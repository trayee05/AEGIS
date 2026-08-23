"""Load third-party synthetic FHIR R4 bundles into the AEGIS sandbox.

The built-in generator is useful for deterministic unit tests, but evaluating a
system only on records it generated itself leaves a circularity gap.  This
adapter accepts ordinary FHIR JSON bundles (including Synthea transaction
bundles), normalises intra-bundle ``urn:uuid`` references, and emits the same
resource-type keyed store used by :class:`FHIRStore`.

This is *external-format validation*, not clinical validation: Synthea records
are fully synthetic and no patient outcomes are measured.
"""
from __future__ import annotations

import copy
import hashlib
import json
import zipfile
from collections import Counter
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, Iterable, Iterator, List, Optional, Sequence, Tuple


SUPPORTED_RESOURCE_TYPES = (
    "Patient", "Observation", "Condition", "Encounter", "MedicationRequest",
)


@dataclass
class FHIRLoadReport:
    source_label: str = "external FHIR R4 JSON"
    source_files: List[str] = field(default_factory=list)
    source_sha256: Dict[str, str] = field(default_factory=dict)
    bundles_seen: int = 0
    bundles_loaded: int = 0
    patients_loaded: int = 0
    resources_loaded: Dict[str, int] = field(default_factory=dict)
    resources_ignored: Dict[str, int] = field(default_factory=dict)
    profiles_seen: Dict[str, int] = field(default_factory=dict)
    references_rewritten: int = 0
    unresolved_urn_references: int = 0
    validation_errors: List[str] = field(default_factory=list)
    synthetic_evidence_only: bool = True
    claim_tier: str = "external-format mechanism validation"

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _iter_documents(paths: Sequence[Path]) -> Iterator[Tuple[str, Dict[str, Any]]]:
    """Yield ``(display_name, JSON object)`` from files, folders, or zip files."""
    expanded: List[Path] = []
    for source in paths:
        source = source.expanduser().resolve()
        if source.is_dir():
            expanded.extend(sorted(source.rglob("*.json")))
        else:
            expanded.append(source)

    for source in sorted(set(expanded), key=lambda p: str(p).lower()):
        if source.suffix.lower() == ".zip":
            with zipfile.ZipFile(source) as archive:
                for name in sorted(n for n in archive.namelist() if n.lower().endswith(".json")):
                    try:
                        with archive.open(name) as stream:
                            yield f"{source.name}!{name}", json.load(stream)
                    except (json.JSONDecodeError, UnicodeDecodeError):
                        yield f"{source.name}!{name}", {"_aegisLoadError": "invalid JSON"}
        elif source.suffix.lower() == ".json":
            try:
                yield source.name, json.loads(source.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, UnicodeDecodeError):
                yield source.name, {"_aegisLoadError": "invalid JSON"}


def _bundle_entries(document: Dict[str, Any]) -> List[Dict[str, Any]]:
    if document.get("resourceType") == "Bundle":
        return [entry for entry in document.get("entry", []) if isinstance(entry, dict)]
    if document.get("resourceType"):
        return [{"resource": document}]
    return []


def _normalise_references(value: Any, mapping: Dict[str, str]) -> Tuple[Any, int, int]:
    rewritten = unresolved = 0
    if isinstance(value, dict):
        out: Dict[str, Any] = {}
        for key, item in value.items():
            if key == "reference" and isinstance(item, str) and item.startswith("urn:uuid:"):
                if item in mapping:
                    out[key] = mapping[item]
                    rewritten += 1
                else:
                    out[key] = item
                    unresolved += 1
            else:
                out[key], r, u = _normalise_references(item, mapping)
                rewritten += r
                unresolved += u
        return out, rewritten, unresolved
    if isinstance(value, list):
        out_list = []
        for item in value:
            normalised, r, u = _normalise_references(item, mapping)
            out_list.append(normalised)
            rewritten += r
            unresolved += u
        return out_list, rewritten, unresolved
    return value, 0, 0


def _is_restricted(resource: Dict[str, Any]) -> bool:
    security = resource.get("meta", {}).get("security", [])
    codes = {str(coding.get("code", "")).upper() for coding in security}
    return bool(codes & {"R", "V", "RESTRICTED", "VERY-RESTRICTED"})


def _validate_resource(resource: Dict[str, Any], source_name: str) -> Optional[str]:
    rtype = resource.get("resourceType")
    rid = resource.get("id")
    if not rtype or not rid:
        return f"{source_name}: resource missing resourceType or id"
    if rtype == "Patient":
        if not resource.get("name"):
            return f"{source_name}: Patient/{rid} has no name"
        if not resource.get("identifier"):
            return f"{source_name}: Patient/{rid} has no identifier"
        if not resource.get("birthDate"):
            return f"{source_name}: Patient/{rid} has no birthDate"
    return None


def load_fhir_sources(
    sources: Sequence[Path | str],
    *,
    max_patients: Optional[int] = None,
    source_label: str = "Synthea public sample FHIR R4",
) -> Tuple[Dict[str, List[Dict[str, Any]]], FHIRLoadReport]:
    """Load patient-bearing FHIR JSON documents from files, folders, or zips.

    Only resources used by AEGIS are retained.  A patient-bearing bundle is the
    unit of sampling, preventing orphaned observations when ``max_patients`` is
    applied.
    """
    paths = [Path(p).expanduser().resolve() for p in sources]
    missing = [str(path) for path in paths if not path.exists()]
    if missing:
        raise FileNotFoundError(f"FHIR source not found: {', '.join(missing)}")

    report = FHIRLoadReport(source_label=source_label)
    # Evidence packages should be portable and must not disclose a reviewer's
    # workstation layout.  Content hashes retain the provenance binding.
    report.source_files = [path.name for path in paths]
    for path in paths:
        if path.is_file():
            report.source_sha256[path.name] = _sha256_file(path)

    resources: Dict[str, List[Dict[str, Any]]] = {
        resource_type: [] for resource_type in SUPPORTED_RESOURCE_TYPES
    }
    seen: set[Tuple[str, str]] = set()
    ignored: Counter[str] = Counter()
    profiles: Counter[str] = Counter()

    for source_name, document in _iter_documents(paths):
        report.bundles_seen += 1
        if document.get("_aegisLoadError"):
            report.validation_errors.append(f"{source_name}: invalid JSON")
            continue

        entries = _bundle_entries(document)
        patient_entries = [
            entry for entry in entries
            if entry.get("resource", {}).get("resourceType") == "Patient"
        ]
        if not patient_entries:
            ignored["document_without_patient"] += 1
            continue
        if max_patients is not None and report.patients_loaded >= max_patients:
            break

        reference_map: Dict[str, str] = {}
        for entry in entries:
            resource = entry.get("resource", {})
            rtype, rid = resource.get("resourceType"), resource.get("id")
            if rtype and rid:
                canonical = f"{rtype}/{rid}"
                if entry.get("fullUrl"):
                    reference_map[str(entry["fullUrl"])] = canonical
                reference_map[f"urn:uuid:{rid}"] = canonical

        accepted_patient_ids = {
            entry["resource"]["id"] for entry in patient_entries
            if entry.get("resource", {}).get("id")
        }
        if not accepted_patient_ids:
            report.validation_errors.append(f"{source_name}: Patient has no id")
            continue

        loaded_from_bundle = 0
        for entry in entries:
            raw = entry.get("resource", {})
            rtype = raw.get("resourceType")
            if rtype not in resources:
                if rtype:
                    ignored[rtype] += 1
                continue
            resource, rewritten, unresolved = _normalise_references(copy.deepcopy(raw), reference_map)
            report.references_rewritten += rewritten
            report.unresolved_urn_references += unresolved
            error = _validate_resource(resource, source_name)
            if error:
                if len(report.validation_errors) < 50:
                    report.validation_errors.append(error)
                continue

            key = (rtype, str(resource["id"]))
            if key in seen:
                ignored["duplicate_resource"] += 1
                continue
            if rtype in {"Observation", "Condition"}:
                resource["_aegisRestricted"] = _is_restricted(resource)
                code = resource.setdefault("code", {})
                if not code.get("text"):
                    coding = (code.get("coding") or [{}])[0]
                    code["text"] = coding.get("display") or coding.get("code") or "unspecified"
            if rtype == "Observation" and resource.get("valueQuantity"):
                quantity = resource["valueQuantity"]
                quantity.setdefault("unit", quantity.get("code", ""))
            if rtype == "MedicationRequest":
                resource["_aegisSimulatedOnly"] = True
            for profile in resource.get("meta", {}).get("profile", []):
                profiles[str(profile)] += 1
            resources[rtype].append(resource)
            seen.add(key)
            loaded_from_bundle += 1

        if loaded_from_bundle:
            report.bundles_loaded += 1
            report.patients_loaded += len(accepted_patient_ids)

    if report.patients_loaded < 2:
        raise ValueError("external validation requires at least two valid Patient bundles")

    report.resources_loaded = {key: len(value) for key, value in resources.items()}
    report.resources_ignored = dict(sorted(ignored.items()))
    report.profiles_seen = dict(profiles.most_common(20))
    return resources, report


__all__ = [
    "FHIRLoadReport", "SUPPORTED_RESOURCE_TYPES", "load_fhir_sources",
]
