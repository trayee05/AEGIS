# AEGIS-Care experimental report

_Privacy-bounded memory recompilation for recovering poisoned clinical AI agents._

Wall time: 159.184s · 12 incidents · 108 condition runs


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
| A | 12 | 0.2500 | 0.0000 | 1.0000 | 1.0000 | 0.7500 | 0.0000 | 0.1000 | 1.0000 |
| B | 12 | 0.2500 | 0.0000 | 1.0000 | 1.0000 | 0.7500 | 0.0000 | 0.0833 | 1.0000 |
| C | 12 | 0.0000 | 1.0000 | 0.2778 | 0.0000 | 1.0000 | 0.0000 | 0.0000 | 1.0000 |
| D | 12 | 0.1667 | 0.4444 | 0.9167 | 0.9792 | 0.8333 | 0.0000 | 0.0486 | 0.0000 |
| E | 12 | 0.1667 | 0.4444 | 0.9167 | 1.0000 | 0.8333 | 0.0000 | 0.0463 | 0.0000 |
| F | 12 | 0.0000 | 1.0000 | 0.3444 | 0.2679 | 1.0000 | 0.0000 | 0.0000 | 0.0000 |
| G | 12 | 0.0000 | 1.0000 | 0.7500 | 0.8646 | 1.0000 | 0.0000 | 1.0000 | 1.0000 |
| H | 12 | 0.0000 | 1.0000 | 1.0000 | 1.0000 | 1.0000 | 0.0000 | 0.0000 | 1.0000 |
| I | 12 | 0.0000 | 1.0000 | 1.0000 | 1.0000 | 1.0000 | 0.0000 | 0.0000 | 0.0000 |


## RQ1 - sensitivity to provenance loss

_Hypothesis: targeted loss of cross-role and semantic-derivation edges harms provenance-only recovery more than random edge loss._

| condition | provenance | n | descendant_recall | descendant_precision | bsr | rwh |
| --- | --- | --- | --- | --- | --- | --- |
| A | complete | 4 | 0.0000 | 1.0000 | 1.0000 | 0.2500 |
| A | random40 | 4 | 0.0000 | 1.0000 | 1.0000 | 0.2500 |
| A | targeted | 4 | 0.0000 | 1.0000 | 1.0000 | 0.2500 |
| B | complete | 4 | 0.0000 | 1.0000 | 1.0000 | 0.2500 |
| B | random40 | 4 | 0.0000 | 1.0000 | 1.0000 | 0.2500 |
| B | targeted | 4 | 0.0000 | 1.0000 | 1.0000 | 0.2500 |
| C | complete | 4 | 1.0000 | 0.2778 | 0.0000 | 0.0000 |
| C | random40 | 4 | 1.0000 | 0.2778 | 0.0000 | 0.0000 |
| C | targeted | 4 | 1.0000 | 0.2778 | 0.0000 | 0.0000 |
| D | complete | 4 | 1.0000 | 0.8750 | 0.9688 | 0.0000 |
| D | random40 | 4 | 0.2500 | 0.8750 | 0.9688 | 0.2500 |
| D | targeted | 4 | 0.0833 | 1.0000 | 1.0000 | 0.2500 |
| E | complete | 4 | 1.0000 | 0.8750 | 1.0000 | 0.0000 |
| E | random40 | 4 | 0.2500 | 0.8750 | 1.0000 | 0.2500 |
| E | targeted | 4 | 0.0833 | 1.0000 | 1.0000 | 0.2500 |
| F | complete | 4 | 1.0000 | 0.3444 | 0.2679 | 0.0000 |
| F | random40 | 4 | 1.0000 | 0.3444 | 0.2679 | 0.0000 |
| F | targeted | 4 | 1.0000 | 0.3444 | 0.2679 | 0.0000 |
| G | complete | 4 | 1.0000 | 0.7500 | 0.8646 | 0.0000 |
| G | random40 | 4 | 1.0000 | 0.7500 | 0.8646 | 0.0000 |
| G | targeted | 4 | 1.0000 | 0.7500 | 0.8646 | 0.0000 |
| H | complete | 4 | 1.0000 | 1.0000 | 1.0000 | 0.0000 |
| H | random40 | 4 | 1.0000 | 1.0000 | 1.0000 | 0.0000 |
| H | targeted | 4 | 1.0000 | 1.0000 | 1.0000 | 0.0000 |
| I | complete | 4 | 1.0000 | 1.0000 | 1.0000 | 0.0000 |
| I | random40 | 4 | 1.0000 | 1.0000 | 1.0000 | 0.0000 |
| I | targeted | 4 | 1.0000 | 1.0000 | 1.0000 | 0.0000 |


### RQ1 at matched edge loss

_Comparing the `targeted` and `random*` labels directly is unfair: they remove different numbers of edges. This groups runs by the realised loss fraction and compares within each bucket. A positive `targeted_worse_by` supports the hypothesis._

_no data_


## Macro averages by scenario family

| condition | family | n | descendant_recall | descendant_precision | bsr | rwh | uer |
| --- | --- | --- | --- | --- | --- | --- | --- |
| A | F1 | 3 | 0.0000 | 1.0000 | 1.0000 | 0.3333 | 0.0000 |
| A | F2 | 3 | 0.0000 | 1.0000 | 1.0000 | 0.3333 | 0.0000 |
| A | F3 | 3 | 0.0000 | 1.0000 | 1.0000 | 0.3333 | 0.4000 |
| A | F4 | 3 | 0.0000 | 1.0000 | 1.0000 | 0.0000 | 0.0000 |
| B | F1 | 3 | 0.0000 | 1.0000 | 1.0000 | 0.3333 | 0.0000 |
| B | F2 | 3 | 0.0000 | 1.0000 | 1.0000 | 0.3333 | 0.0000 |
| B | F3 | 3 | 0.0000 | 1.0000 | 1.0000 | 0.3333 | 0.3333 |
| B | F4 | 3 | 0.0000 | 1.0000 | 1.0000 | 0.0000 | 0.0000 |
| C | F1 | 3 | 1.0000 | 0.4444 | 0.0000 | 0.0000 | 0.0000 |
| C | F2 | 3 | 1.0000 | 0.2222 | 0.0000 | 0.0000 | 0.0000 |
| C | F3 | 3 | 1.0000 | 0.3333 | 0.0000 | 0.0000 | 0.0000 |
| C | F4 | 3 | 1.0000 | 0.1111 | 0.0000 | 0.0000 | 0.0000 |
| D | F1 | 3 | 0.3333 | 1.0000 | 1.0000 | 0.2222 | 0.0000 |
| D | F2 | 3 | 0.3333 | 1.0000 | 1.0000 | 0.2222 | 0.0000 |
| D | F3 | 3 | 0.4444 | 1.0000 | 1.0000 | 0.2222 | 0.1944 |
| D | F4 | 3 | 0.6667 | 0.6667 | 0.9167 | 0.0000 | 0.0000 |
| E | F1 | 3 | 0.3333 | 1.0000 | 1.0000 | 0.2222 | 0.0000 |
| E | F2 | 3 | 0.3333 | 1.0000 | 1.0000 | 0.2222 | 0.0000 |
| E | F3 | 3 | 0.4444 | 1.0000 | 1.0000 | 0.2222 | 0.1852 |
| E | F4 | 3 | 0.6667 | 0.6667 | 1.0000 | 0.0000 | 0.0000 |
| F | F1 | 3 | 1.0000 | 0.4444 | 0.0000 | 0.0000 | 0.0000 |
| F | F2 | 3 | 1.0000 | 0.4000 | 0.5714 | 0.0000 | 0.0000 |
| F | F3 | 3 | 1.0000 | 0.3333 | 0.0000 | 0.0000 | 0.0000 |
| F | F4 | 3 | 1.0000 | 0.2000 | 0.5000 | 0.0000 | 0.0000 |
| G | F1 | 3 | 1.0000 | 1.0000 | 1.0000 | 0.0000 | 1.0000 |
| G | F2 | 3 | 1.0000 | 1.0000 | 1.0000 | 0.0000 | 1.0000 |
| G | F3 | 3 | 1.0000 | 0.7500 | 0.8333 | 0.0000 | 1.0000 |
| G | F4 | 3 | 1.0000 | 0.2500 | 0.6250 | 0.0000 | 1.0000 |
| H | F1 | 3 | 1.0000 | 1.0000 | 1.0000 | 0.0000 | 0.0000 |
| H | F2 | 3 | 1.0000 | 1.0000 | 1.0000 | 0.0000 | 0.0000 |
| H | F3 | 3 | 1.0000 | 1.0000 | 1.0000 | 0.0000 | 0.0000 |
| H | F4 | 3 | 1.0000 | 1.0000 | 1.0000 | 0.0000 | 0.0000 |
| I | F1 | 3 | 1.0000 | 1.0000 | 1.0000 | 0.0000 | 0.0000 |
| I | F2 | 3 | 1.0000 | 1.0000 | 1.0000 | 0.0000 | 0.0000 |
| I | F3 | 3 | 1.0000 | 1.0000 | 1.0000 | 0.0000 | 0.0000 |
| I | F4 | 3 | 1.0000 | 1.0000 | 1.0000 | 0.0000 | 0.0000 |


## Macro averages by propagation depth

| condition | depth | n | descendant_recall | bsr | rwh |
| --- | --- | --- | --- | --- | --- |
| A | 4 | 12 | 0.0000 | 1.0000 | 0.2500 |
| B | 4 | 12 | 0.0000 | 1.0000 | 0.2500 |
| C | 4 | 12 | 1.0000 | 0.0000 | 0.0000 |
| D | 4 | 12 | 0.4444 | 0.9792 | 0.1667 |
| E | 4 | 12 | 0.4444 | 1.0000 | 0.1667 |
| F | 4 | 12 | 1.0000 | 0.2679 | 0.0000 |
| G | 4 | 12 | 1.0000 | 0.8646 | 0.0000 |
| H | 4 | 12 | 1.0000 | 1.0000 | 0.0000 |
| I | 4 | 12 | 1.0000 | 1.0000 | 0.0000 |


## Paired comparisons (Section 10.1)

| comparison | metric | difference | ci_low | ci_high | n | significant | rationale |
| --- | --- | --- | --- | --- | --- | --- | --- |
| I vs D | rwh | -0.1667 | -0.2500 | -0.0833 | 12 | yes | value of missing-edge recovery plus recompilation |
| I vs D | descendant_recall | 0.5556 | 0.2778 | 0.8333 | 12 | yes |  |
| I vs D | bsr | 0.0208 | 0.0000 | 0.0521 | 12 | no |  |
| I vs D | uer | -0.0486 | -0.1181 | 0.0000 | 12 | no |  |
| I vs E | rwh | -0.1667 | -0.2500 | -0.0833 | 12 | yes | value of latent candidate discovery under incomplete provenance |
| I vs E | descendant_recall | 0.5556 | 0.2778 | 0.8333 | 12 | yes |  |
| I vs E | bsr | 0.0000 | 0.0000 | 0.0000 | 12 | no |  |
| I vs E | uer | -0.0463 | -0.1111 | 0.0000 | 12 | no |  |
| I vs F | rwh | 0.0000 | 0.0000 | 0.0000 | 12 | no | necessity of counterfactual confirmation to protect clean state |
| I vs F | descendant_recall | 0.0000 | 0.0000 | 0.0000 | 12 | no |  |
| I vs F | bsr | 0.7321 | 0.5893 | 0.8690 | 12 | yes |  |
| I vs F | uer | 0.0000 | 0.0000 | 0.0000 | 12 | no |  |
| I vs C | rwh | 0.0000 | 0.0000 | 0.0000 | 12 | no | utility retained relative to the safest simple fallback |
| I vs C | descendant_recall | 0.0000 | 0.0000 | 0.0000 | 12 | no |  |
| I vs C | bsr | 1.0000 | 1.0000 | 1.0000 | 12 | yes |  |
| I vs C | uer | 0.0000 | 0.0000 | 0.0000 | 12 | no |  |
| I vs G | rwh | 0.0000 | 0.0000 | 0.0000 | 12 | no | recovery loss and privacy gain vs centralized raw-content access |
| I vs G | descendant_recall | 0.0000 | 0.0000 | 0.0000 | 12 | no |  |
| I vs G | bsr | 0.1354 | 0.0556 | 0.2292 | 12 | yes |  |
| I vs G | uer | -1.0000 | -1.0000 | -1.0000 | 12 | yes |  |
| I vs H | rwh | 0.0000 | 0.0000 | 0.0000 | 12 | no | oracle regret and irreducible cost of missing provenance |
| I vs H | descendant_recall | 0.0000 | 0.0000 | 0.0000 | 12 | no |  |
| I vs H | bsr | 0.0000 | 0.0000 | 0.0000 | 12 | no |  |
| I vs H | uer | 0.0000 | 0.0000 | 0.0000 | 12 | no |  |
| I vs B | rwh | -0.2500 | -0.3333 | -0.1667 | 12 | yes | value of descendant repair over seed deletion |
| I vs B | descendant_recall | 1.0000 | 1.0000 | 1.0000 | 12 | yes |  |
| I vs B | bsr | 0.0000 | 0.0000 | 0.0000 | 12 | no |  |
| I vs B | uer | -0.0833 | -0.1667 | 0.0000 | 12 | no |  |
| I vs A | rwh | -0.2500 | -0.3333 | -0.1667 | 12 | yes | total effect of recovery |
| I vs A | descendant_recall | 1.0000 | 1.0000 | 1.0000 | 12 | yes |  |
| I vs A | bsr | 0.0000 | 0.0000 | 0.0000 | 12 | no |  |
| I vs A | uer | -0.1000 | -0.2000 | 0.0000 | 12 | no |  |


### McNemar exact tests on paired binary outcomes

| comparison | b (A better) | c (B better) | p_value | n |
| --- | --- | --- | --- | --- |
| I vs D | 6 | 0 | 0.0312 | 12 |
| I vs E | 6 | 0 | 0.0312 | 12 |
| I vs F | 0 | 0 | 1.0000 | 12 |
| I vs C | 0 | 0 | 1.0000 | 12 |
| I vs G | 0 | 0 | 1.0000 | 12 |
| I vs H | 0 | 0 | 1.0000 | 12 |
| I vs B | 9 | 0 | 0.0039 | 12 |
| I vs A | 9 | 0 | 0.0039 | 12 |


## Safety-utility-privacy frontier (Section 10.2)

| condition | safety | utility | privacy | recall | precision | pareto | n |
| --- | --- | --- | --- | --- | --- | --- | --- |
| A | 0.2500 | 1.0000 | 0.1000 | 0.0000 | 1.0000 | False | 12 |
| B | 0.2500 | 1.0000 | 0.0833 | 0.0000 | 1.0000 | False | 12 |
| C | 0.0000 | 0.0000 | 0.0000 | 1.0000 | 0.2778 | False | 12 |
| D | 0.1667 | 0.9792 | 0.0486 | 0.4444 | 0.9167 | False | 12 |
| E | 0.1667 | 1.0000 | 0.0463 | 0.4444 | 0.9167 | False | 12 |
| F | 0.0000 | 0.2679 | 0.0000 | 1.0000 | 0.3444 | False | 12 |
| G | 0.0000 | 0.8646 | 1.0000 | 1.0000 | 0.7500 | False | 12 |
| H | 0.0000 | 1.0000 | 0.0000 | 1.0000 | 1.0000 | True | 12 |
| I | 0.0000 | 1.0000 | 0.0000 | 1.0000 | 1.0000 | True | 12 |


## Oracle regret vs condition H

| condition | regret |
| --- | --- |
| A | 1.0000 |
| B | 1.0000 |
| C | 1.0000 |
| D | 0.5764 |
| E | 0.5556 |
| F | 0.7321 |
| G | 0.1354 |
| I | 0.0000 |


## Empirical leakage (Section 7.2)

_The proposal makes no claim that sketches are private by construction; these are measured attacks._

| attack | n | accuracy | baseline | advantage |
| --- | --- | --- | --- | --- |
| attribute_inference[gender] | 10 | 0.3000 | 0.5000 | -0.2000 |
| attribute_inference[restricted_flag] | 10 | 0.0000 | 0.0000 | 0.0000 |
| membership_inference | 14 | 0.9286 | 0.6429 | 0.2857 |
| linkability[cross-recipient] | 10 | 0.1000 | 0.1000 | 0.0000 |


Raw content exported through the recovery interface: **False**. Fields released: `artifact_type_band, capsule_id, expires_at, incident_id, issued_at, issuer, nonce, patient_token, purpose, recipient, seed_commitment, sketch, support_tokens, time_band`.


Removing purpose/recipient scoping raises cross-recipient linkage accuracy to **1.0**, which is what the scoping ablation in Section 9.2 is meant to expose.


## Verification failures and negative results

_No incident failed pre-recovery verification._
