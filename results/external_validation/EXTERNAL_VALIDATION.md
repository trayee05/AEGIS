# AEGIS-Care external-format validation

> Evidence tier: **external-format mechanism validation on fully synthetic data**.
> This is not clinical validation and makes no patient-outcome claim.

## Why this run exists

The original benchmark used AEGIS's own deterministic FHIR generator. This run instead
loads public Synthea FHIR R4 transaction bundles, normalises their native references,
constructs the same role-separated contamination incidents, and evaluates every recovery
condition on paired snapshots. It tests whether the mechanism survives a different record
generator and realistic US Core resource shapes.

## Data provenance and compatibility

- Source: [Synthea public sample-data repository](https://github.com/synthetichealth/synthea-sample-data)
- Generator: [Synthea synthetic patient simulator](https://github.com/synthetichealth/synthea)
- Patient bundles loaded: **10**
- FHIR bundles scanned / loaded: **11 / 10**
- Resources loaded: `{'Patient': 10, 'Observation': 2611, 'Condition': 297, 'Encounter': 434, 'MedicationRequest': 271}`
- Intra-bundle references rewritten: **7003**
- Unresolved UUID references retained: **0**
- Input SHA-256: `{'synthea_sample_data_fhir_latest.zip': '56cb9e49f7ba6ad4e61c40aa80999f8c10a710823fed1becdf2502053777a521'}`

## Paired recovery result

The run completed **108 condition runs across 12 incidents** in 159.184 seconds.

| Condition | RWH | Recall | Precision | BSR | RTS | UER | DRR |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| A | 0.2500 | 0.0000 | 1.0000 | 1.0000 | 0.7500 | 0.1000 | 1.0000 |
| B | 0.2500 | 0.0000 | 1.0000 | 1.0000 | 0.7500 | 0.0833 | 1.0000 |
| C | 0.0000 | 1.0000 | 0.2778 | 0.0000 | 1.0000 | 0.0000 | 1.0000 |
| D | 0.1667 | 0.4444 | 0.9167 | 0.9792 | 0.8333 | 0.0486 | 0.0000 |
| E | 0.1667 | 0.4444 | 0.9167 | 1.0000 | 0.8333 | 0.0463 | 0.0000 |
| F | 0.0000 | 1.0000 | 0.3444 | 0.2679 | 1.0000 | 0.0000 | 0.0000 |
| G | 0.0000 | 1.0000 | 0.7500 | 0.8646 | 1.0000 | 1.0000 | 1.0000 |
| H | 0.0000 | 1.0000 | 1.0000 | 1.0000 | 1.0000 | 0.0000 | 1.0000 |
| I | 0.0000 | 1.0000 | 1.0000 | 1.0000 | 1.0000 | 0.0000 | 0.0000 |

### Decision reading

- Full CARE residual harm: **0.0**; descendant recall: **1.0**; benign-state retention: **1.0**.
- Explicit-lineage replay residual harm: **0.1667**; recall: **0.4444**.
- Full-reset benign-state retention: **0.0**.
- Verification failures: **0**.
- Evidence-manifest integrity: **PASS** (8 artifacts checked).

These values show mechanism behaviour in a deterministic synthetic study. They do not
estimate effectiveness, safety, or utility in a hospital.

## Limitations and next validation gate

- All records are synthetic Synthea records; no real patient data or clinical outcomes are used.
- The deterministic clinical composer validates recovery mechanics, not open-ended LLM behaviour.
- The external run validates FHIR R4 shape and source independence, not hospital workflow integration.
- Family F3 adds a deterministic restricted-field incident overlay because Synthea does not encode the study's local role policy.
- Thresholds remain those frozen in the proposal; this run is not a prospective clinical study.

The next evidence gate is a container-pinned MedAgentBench run with held-out task templates
and at least one open-weight model, followed by clinician review of every positive label and
hard negative. Live EHR evaluation would require institutional governance and a separate protocol.
