# Verilab

Verilab is a verification layer that sits between an AI-generated lab
protocol and a real Opentrons Flex liquid-handling robot. An LLM turns
English protocol text into structured steps; before any of that ever
becomes robot code, Verilab checks it against real labware capacities,
physical step ordering, and tip contamination risk, deterministically, with
no AI involved in the checking itself. Only a protocol that passes is
allowed to generate real Opentrons Python.

The **Verification Console** is the web interface on top of that pipeline.
It exists to make every check's reasoning fully visible to a human
reviewer before anything is approved: what was checked, exactly what is
wrong (in plain English, not implementation jargon), the real numbers
involved, what could physically go wrong, a concrete corrected
instruction, and, for anyone who wants to verify the tool isn't
hand-waving, the raw data underneath.

## Pipeline

```
protocol text --(extractor.py, LLM)--> structured steps
             --(labware_resolver.py)--> real Opentrons container capacities
             --(checker.py)--> capacity + ordering violations
             --(tip_contamination.py)--> tip reuse violations
             --(generator.py)--> real Opentrons Python, only if nothing blocking was found
```

- `extractor.py` calls Claude to turn protocol text into structured JSON
  steps.
- `labware_resolver.py` is deterministic. It matches labware descriptions
  to a real Opentrons catalog entry and reads that entry's actual well
  capacities. No AI, no guessed numbers.
- `checker.py` is deterministic. It checks cumulative volume against real
  capacity, source depletion, and physical step ordering (nothing can be
  drawn from, incubated, or measured before this protocol fills it).
- `tip_contamination.py` is deterministic. It runs the generated code for
  real, with the pipette's aspirate/drop_tip calls instrumented, and flags
  a tip that touches two different sources before being replaced.
- `generator.py` is deterministic. It only ever runs on a plan that already
  passed the checks above, and turns it into real Opentrons Flex Python.
- `app.py` wires all of the above behind a local FastAPI app and serves the
  Verification Console.

None of `checker.py`, `labware_resolver.py`, `tip_contamination.py`, or
`generator.py` are touched by the web layer. `app.py` and
`static/index.html` only call them and present their real output.

## Quick start

Requires Python 3.10+ (the codebase uses `X | None` type hints).

```bash
pip install -r requirements.txt
```

Set your Anthropic API key. Create a `.env` file in this directory:

```
ANTHROPIC_API_KEY=sk-ant-...
```

`.env` is already covered by `.gitignore`, it will not be committed.

Run the app:

```bash
uvicorn app:app --reload
```

Then open `http://127.0.0.1:8000`.

This is local-only on purpose. Verifying pasted protocol text calls the
real Anthropic API on your key, so it is meant to be run and demoed by
you, not deployed publicly.

## Using the Verification Console

Paste a protocol, or click one of the "Load example" buttons to load a
real file already in this repo (the overflow demo, the contaminated-tip
demo, the ordering-violation demo, or a protocol that passes clean) and
hit **Verify Protocol**. Every one of those hits the real backend; nothing
in the UI is a canned response.

While a check is running, the status line shows the real pipeline stage in
progress ("Reading the protocol", "Identifying containers and reagents",
"Checking volumes, order, and tip use", "Preparing robot code"), streamed
live from the server as each stage actually happens.

The result has three layers you can stop reading at any point:

1. **Headline** (zero clicks): "Cleared for the robot" or "Do not run
   yet", plus one compact card per problem found, each with a category
   icon and label (Volume, Order, or Tip reuse), never color alone.
2. **Details** (one click, "View details"): exactly where the problem is,
   the real numbers involved, the physical consequence if it ran as
   written, and a concrete corrected instruction built from the checker's
   own `suggested_fix`.
3. **Raw technical readout** (one more click, "Show technical detail"):
   the literal extracted step, the resolved labware capacity, and the
   corresponding generated-code line, so anyone can verify the tool isn't
   hand-waving.

Below that, the **evidence panel** answers "does this actually work" with
numbers pulled from real, already-collected results: how naive
single-prompt generation compares to the full pipeline, a scoreboard
across every real protocol this has been run against, and specific cases
confirmed to NOT be false alarms.

### Input types

The same textarea accepts three different things, auto-detected server
side, since the demo fixtures aren't all the same shape:

- **Raw protocol text** (English, e.g. `test_protocols/protocol_11.txt`):
  goes through the full pipeline including the real extractor call.
- **Already-extracted structured steps** (JSON, e.g.
  `demo/ordering_violation_demo.json`): extraction is skipped, the rest of
  the pipeline runs on the given steps directly.
- **Already-generated Opentrons Python** (e.g. `demo/overflow_demo.py`,
  `demo/contaminated_demo.py`): extraction and generation are both
  skipped, the given code is executed for real (with aspirate/dispense
  instrumented) and checked exactly as if it had just been produced.

## Evidence data

The evidence panel is backed by `evidence_results.json`, which is real
computed output, not hand-typed numbers. It is produced by
`build_evidence.py`, which:

- runs `checker.py` against every already-extracted protocol in
  `test_protocols/` (9 real published protocols) to build the scoreboard,
- runs the real Opentrons simulator against the already-generated naive
  single-prompt baselines in `test_protocols/*_baseline.py` for the
  baseline comparison,
- runs `tip_contamination.py` against real generated code to confirm the
  two documented false-alarm cases (the generator's default fresh-tip
  pattern, and a legitimate same-source-twice transfer) are not flagged.

None of this calls the LLM, so it is fully reproducible offline. Re-run it
whenever the underlying fixtures in `test_protocols/`, `demo/`, or
`ground_truth/` change:

```bash
python3 build_evidence.py
```

## Public deployment

`site/` is a separate, public-facing marketing and live-demo page (hero,
feature grid, "Try it live", evidence, pipeline diagram, quickstart). It is
additive: it does not replace or change `static/index.html`, the local
Verification Console described above, which keeps working exactly as it
does today.

Deploying the public site takes two pieces:

- **Backend** (this repo's `app.py`): deploy on a small persistent server,
  for example [Render](https://render.com) (`render.yaml` is included),
  Railway, or Fly.io. Not a serverless function: the tip contamination
  check and the real Opentrons simulator both run subprocess calls and
  execute generated code, which is not compatible with a typical stateless
  serverless platform. Set `ANTHROPIC_API_KEY` on the host; it is never
  sent to or exposed in the frontend. The verify endpoints are rate
  limited per IP (8 requests / 60s) since they are the only ones that call
  the live LLM and run subprocess-based simulation.
- **Frontend** (`site/`): a static build with no build step, deployable on
  Vercel or Netlify (`site/vercel.json` and `site/netlify.toml` are
  included). Before deploying, edit `site/config.js` to point
  `VERILAB_API_BASE` at the deployed backend's URL. If left blank, the
  page assumes it is served from the same origin as the backend (this is
  also how `app.py` mounts it locally at `/site` for preview, same-origin,
  no CORS needed).

## Project layout

```
extractor.py            structured extraction (LLM)
labware_resolver.py     real Opentrons catalog lookups (deterministic)
checker.py              capacity + ordering checks (deterministic)
tip_contamination.py    tip reuse check (deterministic)
generator.py            Opentrons Python code generation (deterministic)
app.py                  FastAPI app: pipeline orchestration + API
static/index.html       the Verification Console (single page, no build step)
site/                   the public marketing/demo site (separate deploy target)
render.yaml             Render blueprint for the backend
build_evidence.py       computes evidence_results.json from real fixtures
evidence_results.json   the evidence panel's data
build_hero_capture.py   computes site/data/hero_capture.json from a real run
demo/                   hand-built violation fixtures + false-alarm fixtures
test_protocols/         real published protocols, extracted/generated/baseline output
ground_truth/           hand-labeled expected extractions
check_ground_truth.py   compares an extraction against ground truth
baseline.py             naive single-prompt comparison tooling
repair_loop.py          simulate-and-repair loop for generated code
run_pipeline.py         CLI runner for the extract -> resolve -> check pipeline
```

## Scope

Currently validated on the Opentrons Flex only. Support for other robot
platforms is a planned next step, not a current claim.
