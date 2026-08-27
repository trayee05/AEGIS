"""Machine-verifiable evidence manifests for AEGIS evaluation runs."""
from __future__ import annotations

import hashlib
import json
import platform
import sys
from datetime import datetime, timezone
from importlib import metadata
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional


EVIDENCE_PACKAGES = (
    "aegis-care", "fastapi", "pydantic", "numpy", "scikit-learn",
    "pandas", "matplotlib", "cryptography", "httpx", "pytest",
)


# Artifacts whose bytes are line-ending dependent. .gitattributes normalises
# these to LF in the repository, but a checkout, an editor, or a Windows-native
# run can leave CRLF on disk. Hashing the raw bytes would then break the seal
# for reasons that have nothing to do with the evidence, so text artifacts are
# hashed after newline normalisation and binary artifacts are hashed as-is.
TEXT_SUFFIXES = frozenset({".md", ".csv", ".json", ".txt", ".yml", ".yaml"})


def sha256_file(path: Path) -> str:
    """SHA-256 of an artifact, normalised for text so the seal is portable."""
    path = Path(path)
    if path.suffix.lower() in TEXT_SUFFIXES:
        raw = path.read_bytes().replace(b"\r\n", b"\n").replace(b"\r", b"\n")
        return hashlib.sha256(raw).hexdigest()
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _package_versions() -> Dict[str, str]:
    versions: Dict[str, str] = {}
    for package in EVIDENCE_PACKAGES:
        try:
            versions[package] = metadata.version(package)
        except metadata.PackageNotFoundError:
            versions[package] = "not-installed"
    return versions


def write_evidence_manifest(
    out_dir: Path,
    *,
    results: Dict[str, Any],
    data_source: Dict[str, Any],
    evidence_files: Iterable[Path],
    command: str,
    limitations: Optional[List[str]] = None,
    verification: Optional[Dict[str, Any]] = None,
) -> Path:
    """Write a provenance record that binds results to inputs and runtime."""
    out_dir = Path(out_dir).resolve()
    artifacts: Dict[str, Dict[str, Any]] = {}
    for path in sorted({Path(p).resolve() for p in evidence_files}):
        if path.is_file():
            text = path.suffix.lower() in TEXT_SUFFIXES
            artifacts[str(path.relative_to(out_dir)).replace("\\", "/")] = {
                "sha256": sha256_file(path),
                # Normalised length for text, so `bytes` agrees with the digest
                # on every platform rather than describing this checkout only.
                "bytes": (len(path.read_bytes().replace(b"\r\n", b"\n").replace(b"\r", b"\n"))
                          if text else path.stat().st_size),
                "hash_input": "newline-normalised" if text else "raw",
            }

    full_care = next(
        (row for row in results.get("by_condition", []) if row.get("condition") == "I"),
        {},
    )
    manifest = {
        "schema": "aegis-evidence-manifest/v2",
        "hash_method": {
            "algorithm": "sha256",
            "text_suffixes": sorted(TEXT_SUFFIXES),
            "note": ("Text artifacts are hashed after CRLF/CR to LF normalisation so a "
                     "seal survives checkout on any platform; binary artifacts are "
                     "hashed byte-for-byte."),
        },
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "claim": {
            "tier": data_source.get("claim_tier", "mechanism validation"),
            "statement": (
                "AEGIS-Care was evaluated on synthetic FHIR records using paired, "
                "deterministic recovery scenarios. This is not clinical validation, "
                "a medical-device claim, or evidence of improved patient outcomes."
            ),
            "synthetic_evidence_only": bool(data_source.get("synthetic_evidence_only", True)),
        },
        "data_source": data_source,
        "evaluation": {
            "condition_runs": len(results.get("rows", [])),
            "incidents": len(results.get("incidents", [])),
            "verification_failures": results.get("verification_failures", []),
            "full_care": full_care,
            "wall_seconds": results.get("wall_seconds"),
        },
        "runtime": {
            "command": command,
            "python": sys.version,
            "platform": platform.platform(),
            "packages": _package_versions(),
        },
        "verification": verification or {},
        "limitations": limitations or [],
        "artifacts": artifacts,
    }
    path = out_dir / "evidence_manifest.json"
    path.write_text(json.dumps(manifest, indent=2, sort_keys=True, default=str), encoding="utf-8")
    return path


def verify_evidence_manifest(path: Path) -> Dict[str, Any]:
    """Rehash every bound artifact and report any mismatch."""
    path = Path(path).resolve()
    payload = json.loads(path.read_text(encoding="utf-8"))
    failures: List[Dict[str, Any]] = []
    for relative, expected in payload.get("artifacts", {}).items():
        artifact = path.parent / relative
        if not artifact.is_file():
            failures.append({"artifact": relative, "reason": "missing"})
            continue
        actual = sha256_file(artifact)
        if actual != expected.get("sha256"):
            failures.append({
                "artifact": relative, "reason": "sha256 mismatch",
                "expected": expected.get("sha256"), "actual": actual,
            })
    return {
        "valid": not failures,
        "artifacts_checked": len(payload.get("artifacts", {})),
        "failures": failures,
    }


__all__ = ["sha256_file", "write_evidence_manifest", "verify_evidence_manifest"]
