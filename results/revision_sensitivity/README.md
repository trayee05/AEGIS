# Post-review exploratory sensitivity sweep

Run `python scripts/revision_sensitivity.py` from the repository root to regenerate this directory. The sweep uses condition I only, two task-selection seeds, depths 3 and 4, random-40 and targeted provenance masks, and one task per family (32 valid incidents per configuration). The 10 configurations include the paper default and nine perturbations. All use the same author-generated task engine; this is neither a held-out calibration study nor independent replication.

`summary.csv` reports aggregate metrics. Each JSON file retains incident rows, verification failures, and the complete configuration for its named variant.
