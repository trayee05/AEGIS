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
- Patient bundles loaded: **30**
- FHIR bundles scanned / loaded: **31 / 30**
- Resources loaded: `{'Patient': 30, 'Observation': 7074, 'Condition': 702, 'Encounter': 1220, 'MedicationRequest': 918}`
- Intra-bundle references rewritten: **19258**
- Unresolved UUID references retained: **0**
- Input SHA-256: `{'aegis_synthea_r4_nov2021.zip': '6d3c5433bcae4791bc5c30469d1445b430fb4894d5c13bda15fee0584bbd7778'}`

## Paired recovery result

The run completed **648 condition runs across 72 incidents** in 555.039 seconds.

| Condition | RWH | Recall | Precision | BSR | RTS | UER | DRR |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| A | 0.2500 | 0.0000 | 1.0000 | 1.0000 | 0.7500 | 0.1000 | 1.0000 |
| B | 0.2500 | 0.0000 | 1.0000 | 1.0000 | 0.7500 | 0.0833 | 1.0000 |
| C | 0.0000 | 1.0000 | 0.2824 | 0.0000 | 1.0000 | 0.0000 | 1.0000 |
| D | 0.1620 | 0.4062 | 0.9583 | 0.9896 | 0.8333 | 0.0440 | 0.0000 |
| E | 0.1620 | 0.4062 | 0.9583 | 1.0000 | 0.8333 | 0.0417 | 0.0000 |
| F | 0.0000 | 1.0000 | 0.3562 | 0.2765 | 1.0000 | 0.0000 | 0.0000 |
| G | 0.0000 | 1.0000 | 0.7604 | 0.8683 | 1.0000 | 1.0000 | 1.0000 |
| H | 0.0000 | 1.0000 | 1.0000 | 1.0000 | 1.0000 | 0.0000 | 1.0000 |
| I | 0.0000 | 1.0000 | 1.0000 | 1.0000 | 1.0000 | 0.0000 | 0.0000 |

### Decision reading

- Full CARE residual harm: **0.0**; descendant recall: **1.0**; benign-state retention: **1.0**.
- Explicit-lineage replay residual harm: **0.162**; recall: **0.4062**.
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
- Thresholds are fixed implementation defaults; the original pilot-selection record is unavailable, and this is not a prospective clinical study.

The next evidence gate is a container-pinned MedAgentBench run with held-out task templates
and at least one open-weight model, followed by clinician review of every positive label and
hard negative. Live EHR evaluation would require institutional governance and a separate protocol.
