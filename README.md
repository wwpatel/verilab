# Verilab

Verilab is a verification layer that sits between an AI-generated lab
protocol and a real Opentrons Flex liquid-handling robot. An LLM turns
English protocol text into structured steps; before any of that ever
becomes robot code, Verilab checks it against real labware capacities,
physical step ordering, and tip contamination risk, deterministically, with
no AI involved in the checking itself. Only a protocol that passes is
allowed to generate real Opentrons Python.

The **Verification Console** (`static/index.html`, served at `/`) is the
local, single-user web interface on top of that pipeline, meant to be run
and demoed on your own machine and your own key. It exists to make every
check's reasoning fully visible to a human reviewer before anything is
approved: what was checked, exactly what is wrong (in plain English, not
implementation jargon), the real numbers involved, what could physically go
wrong, a concrete corrected instruction, and, for anyone who wants to
verify the tool isn't hand-waving, the raw data underneath.

`site/` (served at `/site`) is the separate public product: a marketing
page built from real precomputed pipeline output, plus real accounts. A
signed-in user pastes a protocol on the Dashboard, it runs live on their
own stored Anthropic API key, and every result is saved to Stored
Protocols. See [Public deployment](#public-deployment) below.

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
`VERILAB_ENCRYPTION_KEY` (used to encrypt each signed-up user's own stored
API key at `/site`) is generated automatically on first run and appended to
this same file, no manual step needed for local use.

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

## Using the public product

Open `http://127.0.0.1:8000/site/` for the marketing page. "Get started"
creates a real account (email and password, hashed, never stored or
logged in plain text). A new account lands on the Dashboard.

Before verifying raw protocol text there, add an Anthropic API key in
Settings (`/site/app/settings.html`); it's encrypted at rest and only ever
used to power that account's own verification requests. Already-structured
step JSON or already-generated Opentrons Python don't need a key, since
neither calls the extractor.

Every verification run on the Dashboard is real (real extraction if
needed, real checks, real code generation on a clean pass) and is saved;
it reappears under Stored Protocols with its exact original three-layer
result, viewable any time.

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

`site/` is the public-facing product: a marketing page (hero, feature
sections, evidence, pipeline diagram, recent activity), real sign up and
sign in, and an authenticated app (Dashboard, Stored Protocols, Settings)
where a signed-in user verifies real protocols on their own stored
Anthropic API key. It is additive: it does not replace or change
`static/index.html`, the local Verification Console described above, which
keeps working exactly as it does today.

Unlike the read-only marketing mockups, the authenticated product uses real
httponly session cookies, so `site/` has to be served from the same origin
as the API, one persistent server (`app.py`), not split across a separate
static frontend host and a separate backend host. `app.py` already mounts
`site/` at `/site` for exactly this reason.

Deploy `app.py` on a small persistent server, for example
[Render](https://render.com) (`render.yaml` is included), Railway, or
Fly.io. Not a serverless function: the tip contamination check and the real
Opentrons simulator both run subprocess calls and execute generated code,
which a typical stateless serverless platform doesn't support well.

On first run, two secrets are needed:

- `ANTHROPIC_API_KEY`: only used by the local console's own examples and
  the public marketing page's read-only `/api/evidence`. It is never used
  to power a signed-in user's own verification requests; that always runs
  on their own key, entered in Settings and decrypted per request.
- `VERILAB_ENCRYPTION_KEY`: encrypts every user's stored API key at rest.
  If unset, one is generated on first startup and appended to `.env`
  automatically. Set this explicitly and keep it stable across restarts on
  a real deployment; losing it makes every already-stored user API key
  unrecoverable.

User accounts and stored protocols live in `verilab.db` (SQLite, gitignored,
a real file on disk, not in-memory). Back it up like any other production
database if this is deployed for real.

The verify endpoints are rate limited per IP (8 requests / 60s on the
unauthenticated `/api/verify*` routes used by the local console) since
those are the only ones that call the live LLM on the server's own key.

## Project layout

```
extractor.py            structured extraction (LLM)
labware_resolver.py     real Opentrons catalog lookups (deterministic)
checker.py              capacity + ordering checks (deterministic)
tip_contamination.py    tip reuse check (deterministic)
generator.py            Opentrons Python code generation (deterministic)
app.py                  FastAPI app: pipeline orchestration + auth + product API
db.py                   SQLite schema and queries: users, sessions, protocols
auth.py                 password hashing, session cookies
crypto.py               encrypts stored API keys at rest (Fernet)
static/index.html       the Verification Console (single page, no build step)
site/                   the public product: marketing page, auth, app shell
site/shared.css         brand tokens + components shared across site/
site/shared-result-view.js   the three-layer disclosure renderer, shared across site/
site/app/               Dashboard, Stored Protocols, Settings (signed-in only)
render.yaml             Render blueprint for the backend
build_evidence.py       computes evidence_results.json from real fixtures
evidence_results.json   the evidence panel's data
build_hero_capture.py   computes site/data/hero_capture.json from a real run
build_marketing_examples.py  computes site/data/marketing_examples.json from a real run
build_changelog.py      computes site/data/changelog.json from real git history
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
