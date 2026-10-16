# AEGIS-Care experimental report

_Privacy-bounded memory recompilation for recovering poisoned clinical AI agents._

Wall time: 555.039s · 72 incidents · 648 condition runs


## Recovery conditions

| id | condition | purpose |
| --- | --- | --- |
| A | No recovery | Measures residual harm and ordinary task utility. |
| B | Delete confirmed seed only | Tests whether descendants survive local cleanup. |
| C | Full memory reset | Safety-heavy fallback and lower bound on retained utility. |
| D | Explicit-lineage quarantine | Strong privacy-respecting baseline with no missing-edge reconstruction. |
| E | Explicit-lineage clean replay | Separates recompilation value from latent candidate discovery. |
| F | Sketch-only quarantine | Measures false positives when semantic candidates are treated as causality. |
| G | Central raw-content oracle | Non-private upper comparator for discovery and reconstruction. |
| H | Complete private oracle graph | Unattainable provenance upper bound. |
| I | AEGIS-Care / full CARE | Lineage + sketches + local attribution + recompilation + enforcement. |


## Primary results by condition

RWH = residual wrong-patient/unauthorized harm (lower better); BSR = benign-state retention (higher better); RTS = repaired task success; UER = unauthorized exposure; DRR = deletion resurrection rate.

| condition | n | rwh | descendant_recall | descendant_precision | bsr | rts | false_repair_rate | uer | drr |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| A | 72 | 0.2500 | 0.0000 | 1.0000 | 1.0000 | 0.7500 | 0.0000 | 0.1000 | 1.0000 |
| B | 72 | 0.2500 | 0.0000 | 1.0000 | 1.0000 | 0.7500 | 0.0000 | 0.0833 | 1.0000 |
| C | 72 | 0.0000 | 1.0000 | 0.2824 | 0.0000 | 1.0000 | 0.0000 | 0.0000 | 1.0000 |
| D | 72 | 0.1620 | 0.4062 | 0.9583 | 0.9896 | 0.8333 | 0.0000 | 0.0440 | 0.0000 |
| E | 72 | 0.1620 | 0.4062 | 0.9583 | 1.0000 | 0.8333 | 0.0000 | 0.0417 | 0.0000 |
| F | 72 | 0.0000 | 1.0000 | 0.3562 | 0.2765 | 1.0000 | 0.0000 | 0.0000 | 0.0000 |
| G | 72 | 0.0000 | 1.0000 | 0.7604 | 0.8683 | 1.0000 | 0.0000 | 1.0000 | 1.0000 |
| H | 72 | 0.0000 | 1.0000 | 1.0000 | 1.0000 | 1.0000 | 0.0000 | 0.0000 | 1.0000 |
| I | 72 | 0.0000 | 1.0000 | 1.0000 | 1.0000 | 1.0000 | 0.0000 | 0.0000 | 0.0000 |


## RQ1 - sensitivity to provenance loss

_Hypothesis: targeted loss of cross-role and semantic-derivation edges harms provenance-only recovery more than random edge loss._

| condition | provenance | n | descendant_recall | descendant_precision | bsr | rwh |
| --- | --- | --- | --- | --- | --- | --- |
| A | complete | 24 | 0.0000 | 1.0000 | 1.0000 | 0.2500 |
| A | random40 | 24 | 0.0000 | 1.0000 | 1.0000 | 0.2500 |
| A | targeted | 24 | 0.0000 | 1.0000 | 1.0000 | 0.2500 |
| B | complete | 24 | 0.0000 | 1.0000 | 1.0000 | 0.2500 |
| B | random40 | 24 | 0.0000 | 1.0000 | 1.0000 | 0.2500 |
| B | targeted | 24 | 0.0000 | 1.0000 | 1.0000 | 0.2500 |
| C | complete | 24 | 1.0000 | 0.2824 | 0.0000 | 0.0000 |
| C | random40 | 24 | 1.0000 | 0.2824 | 0.0000 | 0.0000 |
| C | targeted | 24 | 1.0000 | 0.2824 | 0.0000 | 0.0000 |
| D | complete | 24 | 1.0000 | 0.8958 | 0.9740 | 0.0000 |
| D | random40 | 24 | 0.1354 | 0.9792 | 0.9948 | 0.2361 |
| D | targeted | 24 | 0.0833 | 1.0000 | 1.0000 | 0.2500 |
| E | complete | 24 | 1.0000 | 0.8958 | 1.0000 | 0.0000 |
| E | random40 | 24 | 0.1354 | 0.9792 | 1.0000 | 0.2361 |
| E | targeted | 24 | 0.0833 | 1.0000 | 1.0000 | 0.2500 |
| F | complete | 24 | 1.0000 | 0.3528 | 0.2708 | 0.0000 |
| F | random40 | 24 | 1.0000 | 0.3590 | 0.2820 | 0.0000 |
| F | targeted | 24 | 1.0000 | 0.3569 | 0.2768 | 0.0000 |
| G | complete | 24 | 1.0000 | 0.7604 | 0.8683 | 0.0000 |
| G | random40 | 24 | 1.0000 | 0.7604 | 0.8683 | 0.0000 |
| G | targeted | 24 | 1.0000 | 0.7604 | 0.8683 | 0.0000 |
| H | complete | 24 | 1.0000 | 1.0000 | 1.0000 | 0.0000 |
| H | random40 | 24 | 1.0000 | 1.0000 | 1.0000 | 0.0000 |
| H | targeted | 24 | 1.0000 | 1.0000 | 1.0000 | 0.0000 |
| I | complete | 24 | 1.0000 | 1.0000 | 1.0000 | 0.0000 |
| I | random40 | 24 | 1.0000 | 1.0000 | 1.0000 | 0.0000 |
| I | targeted | 24 | 1.0000 | 1.0000 | 1.0000 | 0.0000 |


### RQ1 at matched edge loss

_Comparing the `targeted` and `random*` labels directly is unfair: they remove different numbers of edges. This groups runs by the realised loss fraction and compares within each bucket. A positive `targeted_worse_by` supports the hypothesis._

_no data_


## Macro averages by scenario family

| condition | family | n | descendant_recall | descendant_precision | bsr | rwh | uer |
| --- | --- | --- | --- | --- | --- | --- | --- |
| A | F1 | 18 | 0.0000 | 1.0000 | 1.0000 | 0.3333 | 0.0000 |
| A | F2 | 18 | 0.0000 | 1.0000 | 1.0000 | 0.3333 | 0.0000 |
| A | F3 | 18 | 0.0000 | 1.0000 | 1.0000 | 0.3333 | 0.4000 |
| A | F4 | 18 | 0.0000 | 1.0000 | 1.0000 | 0.0000 | 0.0000 |
| B | F1 | 18 | 0.0000 | 1.0000 | 1.0000 | 0.3333 | 0.0000 |
| B | F2 | 18 | 0.0000 | 1.0000 | 1.0000 | 0.3333 | 0.0000 |
| B | F3 | 18 | 0.0000 | 1.0000 | 1.0000 | 0.3333 | 0.3333 |
| B | F4 | 18 | 0.0000 | 1.0000 | 1.0000 | 0.0000 | 0.0000 |
| C | F1 | 18 | 1.0000 | 0.4444 | 0.0000 | 0.0000 | 0.0000 |
| C | F2 | 18 | 1.0000 | 0.2222 | 0.0000 | 0.0000 | 0.0000 |
| C | F3 | 18 | 1.0000 | 0.3333 | 0.0000 | 0.0000 | 0.0000 |
| C | F4 | 18 | 1.0000 | 0.1296 | 0.0000 | 0.0000 | 0.0000 |
| D | F1 | 18 | 0.4028 | 1.0000 | 1.0000 | 0.2222 | 0.0000 |
| D | F2 | 18 | 0.3333 | 1.0000 | 1.0000 | 0.2222 | 0.0000 |
| D | F3 | 18 | 0.5000 | 1.0000 | 1.0000 | 0.2037 | 0.1759 |
| D | F4 | 18 | 0.3889 | 0.8333 | 0.9583 | 0.0000 | 0.0000 |
| E | F1 | 18 | 0.4028 | 1.0000 | 1.0000 | 0.2222 | 0.0000 |
| E | F2 | 18 | 0.3333 | 1.0000 | 1.0000 | 0.2222 | 0.0000 |
| E | F3 | 18 | 0.5000 | 1.0000 | 1.0000 | 0.2037 | 0.1667 |
| E | F4 | 18 | 0.3889 | 0.8333 | 1.0000 | 0.0000 | 0.0000 |
| F | F1 | 18 | 1.0000 | 0.4444 | 0.0000 | 0.0000 | 0.0000 |
| F | F2 | 18 | 1.0000 | 0.4000 | 0.5714 | 0.0000 | 0.0000 |
| F | F3 | 18 | 1.0000 | 0.3333 | 0.0000 | 0.0000 | 0.0000 |
| F | F4 | 18 | 1.0000 | 0.2472 | 0.5347 | 0.0000 | 0.0000 |
| G | F1 | 18 | 1.0000 | 1.0000 | 1.0000 | 0.0000 | 1.0000 |
| G | F2 | 18 | 1.0000 | 1.0000 | 1.0000 | 0.0000 | 1.0000 |
| G | F3 | 18 | 1.0000 | 0.7500 | 0.8333 | 0.0000 | 1.0000 |
| G | F4 | 18 | 1.0000 | 0.2917 | 0.6399 | 0.0000 | 1.0000 |
| H | F1 | 18 | 1.0000 | 1.0000 | 1.0000 | 0.0000 | 0.0000 |
| H | F2 | 18 | 1.0000 | 1.0000 | 1.0000 | 0.0000 | 0.0000 |
| H | F3 | 18 | 1.0000 | 1.0000 | 1.0000 | 0.0000 | 0.0000 |
| H | F4 | 18 | 1.0000 | 1.0000 | 1.0000 | 0.0000 | 0.0000 |
| I | F1 | 18 | 1.0000 | 1.0000 | 1.0000 | 0.0000 | 0.0000 |
| I | F2 | 18 | 1.0000 | 1.0000 | 1.0000 | 0.0000 | 0.0000 |
| I | F3 | 18 | 1.0000 | 1.0000 | 1.0000 | 0.0000 | 0.0000 |
| I | F4 | 18 | 1.0000 | 1.0000 | 1.0000 | 0.0000 | 0.0000 |


## Macro averages by propagation depth

| condition | depth | n | descendant_recall | bsr | rwh |
| --- | --- | --- | --- | --- | --- |
| A | 4 | 72 | 0.0000 | 1.0000 | 0.2500 |
| B | 4 | 72 | 0.0000 | 1.0000 | 0.2500 |
| C | 4 | 72 | 1.0000 | 0.0000 | 0.0000 |
| D | 4 | 72 | 0.4062 | 0.9896 | 0.1620 |
| E | 4 | 72 | 0.4062 | 1.0000 | 0.1620 |
| F | 4 | 72 | 1.0000 | 0.2765 | 0.0000 |
| G | 4 | 72 | 1.0000 | 0.8683 | 0.0000 |
| H | 4 | 72 | 1.0000 | 1.0000 | 0.0000 |
| I | 4 | 72 | 1.0000 | 1.0000 | 0.0000 |


## Paired comparisons (Section 10.1)

| comparison | metric | difference | ci_low | ci_high | n | significant | rationale |
| --- | --- | --- | --- | --- | --- | --- | --- |
| I vs D | rwh | -0.1620 | -0.1991 | -0.1250 | 72 | yes | value of missing-edge recovery plus recompilation |
| I vs D | descendant_recall | 0.5938 | 0.4873 | 0.7002 | 72 | yes |  |
| I vs D | bsr | 0.0104 | 0.0035 | 0.0191 | 72 | yes |  |
| I vs D | uer | -0.0440 | -0.0694 | -0.0220 | 72 | yes |  |
| I vs E | rwh | -0.1620 | -0.1991 | -0.1250 | 72 | yes | value of latent candidate discovery under incomplete provenance |
| I vs E | descendant_recall | 0.5938 | 0.4873 | 0.7002 | 72 | yes |  |
| I vs E | bsr | 0.0000 | 0.0000 | 0.0000 | 72 | no |  |
| I vs E | uer | -0.0417 | -0.0664 | -0.0201 | 72 | yes |  |
| I vs F | rwh | 0.0000 | 0.0000 | 0.0000 | 72 | no | necessity of counterfactual confirmation to protect clean state |
| I vs F | descendant_recall | 0.0000 | 0.0000 | 0.0000 | 72 | no |  |
| I vs F | bsr | 0.7235 | 0.6600 | 0.7867 | 72 | yes |  |
| I vs F | uer | 0.0000 | 0.0000 | 0.0000 | 72 | no |  |
| I vs C | rwh | 0.0000 | 0.0000 | 0.0000 | 72 | no | utility retained relative to the safest simple fallback |
| I vs C | descendant_recall | 0.0000 | 0.0000 | 0.0000 | 72 | no |  |
| I vs C | bsr | 1.0000 | 1.0000 | 1.0000 | 72 | yes |  |
| I vs C | uer | 0.0000 | 0.0000 | 0.0000 | 72 | no |  |
| I vs G | rwh | 0.0000 | 0.0000 | 0.0000 | 72 | no | recovery loss and privacy gain vs centralized raw-content access |
| I vs G | descendant_recall | 0.0000 | 0.0000 | 0.0000 | 72 | no |  |
| I vs G | bsr | 0.1317 | 0.0976 | 0.1659 | 72 | yes |  |
| I vs G | uer | -1.0000 | -1.0000 | -1.0000 | 72 | yes |  |
| I vs H | rwh | 0.0000 | 0.0000 | 0.0000 | 72 | no | oracle regret and irreducible cost of missing provenance |
| I vs H | descendant_recall | 0.0000 | 0.0000 | 0.0000 | 72 | no |  |
| I vs H | bsr | 0.0000 | 0.0000 | 0.0000 | 72 | no |  |
| I vs H | uer | 0.0000 | 0.0000 | 0.0000 | 72 | no |  |
| I vs B | rwh | -0.2500 | -0.2824 | -0.2176 | 72 | yes | value of descendant repair over seed deletion |
| I vs B | descendant_recall | 1.0000 | 1.0000 | 1.0000 | 72 | yes |  |
| I vs B | bsr | 0.0000 | 0.0000 | 0.0000 | 72 | no |  |
| I vs B | uer | -0.0833 | -0.1157 | -0.0509 | 72 | yes |  |
| I vs A | rwh | -0.2500 | -0.2824 | -0.2176 | 72 | yes | total effect of recovery |
| I vs A | descendant_recall | 1.0000 | 1.0000 | 1.0000 | 72 | yes |  |
| I vs A | bsr | 0.0000 | 0.0000 | 0.0000 | 72 | no |  |
| I vs A | uer | -0.1000 | -0.1389 | -0.0611 | 72 | yes |  |


### McNemar exact tests on paired binary outcomes

| comparison | b (A better) | c (B better) | p_value | n |
| --- | --- | --- | --- | --- |
| I vs D | 35 | 0 | 0.0000 | 72 |
| I vs E | 35 | 0 | 0.0000 | 72 |
| I vs F | 0 | 0 | 1.0000 | 72 |
| I vs C | 0 | 0 | 1.0000 | 72 |
| I vs G | 0 | 0 | 1.0000 | 72 |
| I vs H | 0 | 0 | 1.0000 | 72 |
| I vs B | 54 | 0 | 0.0000 | 72 |
| I vs A | 54 | 0 | 0.0000 | 72 |


## Safety-utility-privacy frontier (Section 10.2)

| condition | safety | utility | privacy | recall | precision | pareto | n |
| --- | --- | --- | --- | --- | --- | --- | --- |
| A | 0.2500 | 1.0000 | 0.1000 | 0.0000 | 1.0000 | False | 72 |
| B | 0.2500 | 1.0000 | 0.0833 | 0.0000 | 1.0000 | False | 72 |
| C | 0.0000 | 0.0000 | 0.0000 | 1.0000 | 0.2824 | False | 72 |
| D | 0.1620 | 0.9896 | 0.0440 | 0.4062 | 0.9583 | False | 72 |
| E | 0.1620 | 1.0000 | 0.0417 | 0.4062 | 0.9583 | False | 72 |
| F | 0.0000 | 0.2765 | 0.0000 | 1.0000 | 0.3562 | False | 72 |
| G | 0.0000 | 0.8683 | 1.0000 | 1.0000 | 0.7604 | False | 72 |
| H | 0.0000 | 1.0000 | 0.0000 | 1.0000 | 1.0000 | True | 72 |
| I | 0.0000 | 1.0000 | 0.0000 | 1.0000 | 1.0000 | True | 72 |


## Oracle regret vs condition H

| condition | regret |
| --- | --- |
| A | 1.0000 |
| B | 1.0000 |
| C | 1.0000 |
| D | 0.6042 |
| E | 0.5937 |
| F | 0.7235 |
| G | 0.1317 |
| I | 0.0000 |


## Empirical leakage (Section 7.2)

_The proposal makes no claim that sketches are private by construction; these are measured attacks._

| attack | n | accuracy | baseline | advantage |
| --- | --- | --- | --- | --- |
| attribute_inference[gender] | 30 | 0.6000 | 0.5667 | 0.0333 |
| attribute_inference[restricted_flag] | 30 | 0.0000 | 0.0000 | 0.0000 |
| membership_inference | 14 | 0.8571 | 0.6429 | 0.2143 |
| linkability[cross-recipient] | 30 | 0.0000 | 0.0333 | -0.0333 |


Raw content exported through the recovery interface: **False**. Fields released: `artifact_type_band, capsule_id, expires_at, incident_id, issued_at, issuer, nonce, patient_token, purpose, recipient, seed_commitment, sketch, support_tokens, time_band`.


Removing purpose/recipient scoping raises cross-recipient linkage accuracy to **1.0**, which is what the scoping ablation in Section 9.2 is meant to expose.


## Verification failures and negative results

_No incident failed pre-recovery verification._
