# AEGIS-Care presentation runbook

## Prepare on this Mac

From the repository root:

```bash
/opt/homebrew/bin/python3.12 -m venv .venv312
.venv312/bin/python -m pip install -r requirements.txt
.venv312/bin/python -m aegis_care.cli demo
./scripts/run_demo.sh
```

Open <http://127.0.0.1:8000/> while the last command keeps running. The launcher
refuses an occupied port so an old server cannot silently supply the page. It
uses a fresh temporary synthetic case database and defaults to zero external
assistant model calls. To change ports, use `./scripts/run_demo.sh 8001`.

Immediately before presenting, restart the launcher to get a fresh sandbox.
Do not use real patient information. Keep the CLI output and
[`output/pdf/AEGIS_Care_Research_Poster_16x9.pdf`](../output/pdf/AEGIS_Care_Research_Poster_16x9.pdf)
open as backups.

The older `output/pdf/AEGIS_Care_Capstone_Infographic.pdf` still describes a
900-run campaign. Use the research poster and the live Evidence Center for
tomorrow's numbers; the committed mechanism matrix currently has 270 runs.

## Four-minute agent-led walkthrough

1. **Overview (30 seconds).** Open `http://127.0.0.1:8000/#overview`. Say: “A
   wrong patient association can be copied into a handover and summary. Deleting
   the original leaves those descendants. AEGIS repairs the affected state.”
2. **Enter the agent workflow (30 seconds).** Click **Watch AEGIS act**. The role
   chooser opens over the overview with **Clinical Safety Officer** selected.
   Click **Continue as Safety**. The Incident Command screen opens with the
   Operator and “Demo an end-to-end recovery” already in its input.
3. **Show bounded autonomy (75 seconds).** Press **Send**. The Operator chooses
   its local `fix_everything` action and shows a four-step execution plan. Point
   to the incident scope and explicit approval gate; click **Approve plan**.
   The response logs the error, discovers candidates, confirms them by local
   replay, rebuilds from FHIR, withdraws unsafe versions, and probes for return.
   Read the actual counts on screen; in a clean default F1 session the expected
   result is four affected descendants and four repairs.
4. **Verify (45 seconds).** Show **Safe to resume**, the 0.000 residual harm and
   1.000 clean-state retention for this synthetic incident, then expand the
   recovery certificate. Ask the Operator **“Show the case inbox”** to show the
   recorded case and next action. The model-call counter remains at 0/0 because
   this demonstrated route uses local intent matching and deterministic tools.
5. **Explain and qualify (60 seconds).** C nominates, A checks causal influence,
   R rebuilds or quarantines, and E enforces the withdrawal. Say explicitly:
   this is a synthetic prototype with a temporary case database and demonstration role selection,
   not a hospital deployment or proof of clinical effectiveness.

For the visual mechanism path, click **Manual trajectory** from the public
overview, choose **Researcher / Evaluator**, then click **Inject trajectory**
and **Run CARE recovery**. The Evidence Center in that role shows 10 synthetic
Synthea patients, 12 incidents, 108 external-format paired runs, and eight
integrity-checked artifacts. The separate committed mechanism matrix has 30
incidents and 270 condition runs.

## One-sentence answer to “what actually runs?”

“A FastAPI service hosts a browser console, synthetic FHIR data, role-separated
agent memory, the CARE recovery pipeline, and evaluation endpoints; the default
composer is deterministic, so the demonstrated incident can be replayed.”

The Operator is an agent interface over a fixed action catalogue. For this demo,
it interprets the request locally, proposes a plan, calls the recovery tools
after approval, and reports measurements computed by the backend. It is not an
open-ended autonomous LLM or a clinical decision maker.

## Questions to expect

- **Is this deployed in a hospital?** No. It is an in-memory research sandbox
  with synthetic records and demonstration role selection, not real staff login.
- **Is the model an LLM?** The default clinical composer is deterministic.
  An optional model adapter exists, but these metrics do not validate stochastic
  model output or its prose safety.
- **Does a sketch prove causation or guarantee privacy?** No. It nominates
  possible descendants. Local counterfactual replay provides the causal test.
  The privacy audit measures bounded leakage risks; it is not a confidentiality
  or regulatory certification.
- **What does “safe resume” mean?** Only that the configured checks for this
  synthetic incident passed, including follow-up and resurrection probes.
  Human-governed clinical deployment would require additional study.

## Fallback if the browser fails

Run `.venv312/bin/python -m aegis_care.cli demo` and show the contaminated
trajectory, CARE counts, post-recovery follow-up, and certificate. Run
`.venv312/bin/python -m aegis_care.cli baselines` for the comparison. The poster
PDF gives a static explanation of the same research boundary.
