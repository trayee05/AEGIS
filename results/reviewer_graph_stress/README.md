# Deterministic branched graph stress test

Regenerate from the repository root:

```sh
.venv/bin/python scripts/reviewer_graph_stress.py
```

`results.json` records nine graph/mask cells. Each cell compares condition D
(observed-lineage quarantine) with condition I (full CARE) from the same
pre-recovery snapshot. A wrong-patient registration hint feeds 4, 8, or 16
independent four-step branches spanning nursing and clinical-summary roles.
Writes are interleaved by stage. One separate clean five-artifact trajectory
per branch supplies controls. The largest graph has 145 artifacts: one seed,
64 contaminated descendants, and 80 clean controls. The mask seed is 20261016.

All 18 condition runs completed. Full CARE neutralized all contaminated
descendants and retained every clean control in these cells. At 16 branches,
condition D recall was 64/64 with complete provenance, 24/64 with 40% random
edge loss, and 0/64 with targeted loss. Its wrong-patient follow-up counts were
0/17, 14/17, and 16/17, respectively; full CARE had 0/17 in each mask.

This is a controlled in-process fan-out test with a deterministic composer and
one generated graph per size/mask cell. It does not exercise concurrent
processes, multi-parent joins, cycles, independent incident authorship, or
clinical data. `results.json` contains the exact counts and metrics; no
confidence interval or external-validity claim is implied.
