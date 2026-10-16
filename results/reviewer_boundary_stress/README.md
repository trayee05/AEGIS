# Controlled security and replay-boundary probes

Regenerate with `.venv/bin/python scripts/reviewer_boundary_stress.py` from the repository root. The run uses one deterministic synthetic clinical-summary artifact. The 102 changed-prose cases hold its structured facts fixed; 100 are generated from a fixed nonclinical word list. They are not outputs from a stochastic language model and do not estimate a clinical false-negative rate.

The current results show that independent environments no longer share the same signing key and a signature made under a different public test seed is rejected. If an attacker obtains the runtime's private key, a forged payload verifies. Process-level access can read raw artifact content because logical roles share one process. These latter outcomes are expected failures of the current trust boundary, not passed security claims.

None of the 102 controlled prose-only changes crossed the default influence threshold when structured facts were held constant. This reveals a blind spot for text-only errors and motivates repeated-model evaluation and human review before using a stochastic composer. See `results.json` for the per-variant scores.
