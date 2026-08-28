#!/usr/bin/env python
"""Re-bind an evidence manifest's digests to the artifacts as they exist on disk.

Use this only to migrate a manifest to newline-normalised hashing (schema v1 ->
v2). It rewrites the `artifacts` block and nothing else: the original run's
provenance -- generated_at, command, platform, package versions, evaluation
numbers -- is preserved exactly, because that record describes the run and must
not be restated by a later machine.

Re-sealing is not a way to make a failing check pass. Every digest it changes is
printed, and any artifact whose content differs beyond line endings is reported
as CONTENT CHANGED so it can be judged rather than silently re-bound.

    python scripts/reseal_evidence.py results/external_validation --dry-run
    python scripts/reseal_evidence.py results/external_validation
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from aegis_care.eval.evidence import TEXT_SUFFIXES, sha256_file  # noqa: E402


def classify(path: Path, expected: dict) -> str:
    """Why does this artifact's digest differ from the one on record?"""
    raw = path.read_bytes()
    old = expected.get("sha256")
    if hashlib.sha256(raw).hexdigest() == old:
        return "raw match (already bound to these bytes)"
    crlf = raw.replace(b"\n", b"\r\n")
    if hashlib.sha256(crlf).hexdigest() == old:
        return "line endings only (sealed as CRLF, stored as LF)"
    return "CONTENT CHANGED beyond line endings"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("directory", help="directory holding evidence_manifest.json")
    parser.add_argument("--dry-run", action="store_true",
                        help="report what would change without writing")
    args = parser.parse_args()

    out_dir = Path(args.directory).resolve()
    manifest_path = out_dir / "evidence_manifest.json"
    if not manifest_path.is_file():
        sys.exit(f"error: {manifest_path} not found")

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    artifacts = manifest.get("artifacts", {})
    if not artifacts:
        sys.exit("error: manifest binds no artifacts")

    changed, unchanged, suspicious, missing = [], [], [], []
    for relative, expected in sorted(artifacts.items()):
        path = out_dir / relative
        if not path.is_file():
            missing.append(relative)
            continue
        text = path.suffix.lower() in TEXT_SUFFIXES
        digest = sha256_file(path)
        size = (len(path.read_bytes().replace(b"\r\n", b"\n").replace(b"\r", b"\n"))
                if text else path.stat().st_size)
        if digest == expected.get("sha256"):
            unchanged.append(relative)
        else:
            reason = classify(path, expected)
            changed.append((relative, expected.get("sha256"), digest, reason))
            if reason.startswith("CONTENT CHANGED"):
                suspicious.append(relative)
        artifacts[relative] = {"sha256": digest, "bytes": size,
                               "hash_input": "newline-normalised" if text else "raw"}

    print(f"Manifest: {manifest_path}")
    print(f"  artifacts bound : {len(artifacts)}")
    print(f"  already correct : {len(unchanged)}")
    print(f"  re-bound        : {len(changed)}")
    if missing:
        print(f"  MISSING         : {', '.join(missing)}")
    print()
    for relative, old, new, reason in changed:
        print(f"  {relative}")
        print(f"    reason : {reason}")
        print(f"    {old[:16]}... -> {new[:16]}...")
    if suspicious:
        print()
        print("  WARNING: the following artifacts differ in content, not just line")
        print("  endings. Re-sealing binds the manifest to the files as they are now;")
        print("  confirm that is what you intend:")
        for relative in suspicious:
            print(f"    - {relative}")

    if args.dry_run:
        print("\nDry run: nothing written.")
        return 0

    manifest["artifacts"] = artifacts
    manifest["schema"] = "aegis-evidence-manifest/v2"
    manifest["hash_method"] = {
        "algorithm": "sha256",
        "text_suffixes": sorted(TEXT_SUFFIXES),
        "note": ("Text artifacts are hashed after CRLF/CR to LF normalisation so a "
                 "seal survives checkout on any platform; binary artifacts are "
                 "hashed byte-for-byte."),
    }
    manifest.setdefault("reseal_history", []).append({
        "reason": "migrated to newline-normalised hashing (schema v1 -> v2)",
        "rebound_artifacts": [c[0] for c in changed],
        "content_changed_artifacts": suspicious,
    })
    manifest_path.write_text(
        json.dumps(manifest, indent=2, sort_keys=True, default=str), encoding="utf-8")
    print(f"\nRe-sealed {manifest_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
