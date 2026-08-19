"""
Verilab local web app: the Verification Console.

Runs the REAL pipeline, not a reimplementation: extractor.py (LLM),
labware_resolver.py, checker.py's overflow + ordering checks,
tip_contamination.py, and generator.py, wired together behind a few
endpoints. Nothing in checker.py, labware_resolver.py, tip_contamination.py,
or generator.py is modified here -- this file only calls them and reshapes
their real output into something a human reviewer can read at a glance,
then drill into.

Deliberately local-only. Run with:
    uvicorn app:app --reload
then open http://127.0.0.1:8000

Not deployed publicly on purpose -- every request that verifies pasted
protocol text calls the real Anthropic API on your key, and this is meant
to be demoed by you, not opened to strangers.
"""

import io
import contextlib
import json
import os
import re
import tempfile
import time
import traceback
from collections import defaultdict, deque
from pathlib import Path

from dotenv import load_dotenv

# Loaded before extractor.py is imported below: extractor.py builds its
# Anthropic client at module import time from os.environ, so ANTHROPIC_API_KEY
# has to already be set by the time that import runs.
load_dotenv()

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from extractor import (
    extract_steps,
    expand_dest_wells,
    normalize_labware_refs,
    validate_labware_ids,
)
from labware_resolver import build_capacity_table
from checker import check_protocol, check_ordering, resource_summary, CHECKS_AGAINST
from generator import generate_protocol
from tip_contamination import check_tip_contamination

BASE_DIR = Path(__file__).parent

app = FastAPI()

# The public site (site/index.html) is deployed on a different origin than
# this API (static frontend host vs. persistent backend host), so the verify
# and evidence endpoints need to be reachable cross-origin. There is no
# session or cookie auth here to protect, and the Anthropic key never leaves
# the server, so an open CORS policy on these read/verify-only endpoints
# doesn't widen what a caller could otherwise already do by hand.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)


class VerifyRequest(BaseModel):
    protocol_text: str
    protocol_name: str = "Untitled Protocol"
    input_kind: str = "auto"  # "auto" | "text" | "structured" | "code"


# ---------------------------------------------------------------------------
# Per-IP rate limit on the verify endpoints. These are the only endpoints
# that call the live Anthropic API and run subprocess-based simulation, so
# they're the only ones worth protecting once this is reachable by anyone on
# the internet. A fixed in-memory window is enough for a single small
# persistent server; it does not need to survive a restart or be shared
# across instances.
# ---------------------------------------------------------------------------

RATE_LIMIT_MAX_REQUESTS = 8
RATE_LIMIT_WINDOW_SECONDS = 60
_request_log: dict[str, deque] = defaultdict(deque)


def client_ip(request: Request) -> str:
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def check_rate_limit(request: Request) -> JSONResponse | None:
    ip = client_ip(request)
    now = time.monotonic()
    log = _request_log[ip]
    while log and now - log[0] > RATE_LIMIT_WINDOW_SECONDS:
        log.popleft()
    if len(log) >= RATE_LIMIT_MAX_REQUESTS:
        return JSONResponse(
            {"error": f"Rate limit exceeded: max {RATE_LIMIT_MAX_REQUESTS} verify requests per {RATE_LIMIT_WINDOW_SECONDS} seconds per IP. Try again shortly."},
            status_code=429,
        )
    log.append(now)
    return None


# ---------------------------------------------------------------------------
# Example protocols. Real files already in the repo, read fresh off disk on
# every request. Nothing here is a canned response -- loading an example
# only fills the textarea; Verify Protocol still hits the real backend.
# ---------------------------------------------------------------------------

EXAMPLES = {
    "overflow": {
        "label": "Overflow demo",
        "kind": "code",
        "path": "demo/overflow_demo.py",
        "protocol_name": "Overflow Demo",
    },
    "tip_contamination": {
        "label": "Contaminated-tip demo",
        "kind": "code",
        "path": "demo/contaminated_demo.py",
        "protocol_name": "Tip Contamination Demo",
    },
    "ordering": {
        "label": "Ordering-violation demo",
        "kind": "structured",
        "path": "demo/ordering_violation_demo.json",
        "protocol_name": "Ordering Violation Demo",
    },
    "clean": {
        "label": "Clean protocol (passes)",
        "kind": "text",
        "path": "test_protocols/protocol_11.txt",
        "protocol_name": "Phytip Protein A Reagent Plate Prep",
    },
}


@app.get("/api/examples")
def list_examples():
    return JSONResponse(
        [{"id": k, **{kk: vv for kk, vv in v.items() if kk != "path"}} for k, v in EXAMPLES.items()]
    )


@app.get("/api/examples/{example_id}")
def get_example(example_id: str):
    meta = EXAMPLES.get(example_id)
    if not meta:
        return JSONResponse({"error": f"Unknown example '{example_id}'"}, status_code=404)
    path = BASE_DIR / meta["path"]
    try:
        content = path.read_text()
    except OSError as e:
        return JSONResponse({"error": f"Could not read {meta['path']}: {e}"}, status_code=500)
    return JSONResponse(
        {"id": example_id, "kind": meta["kind"], "protocol_name": meta["protocol_name"], "content": content}
    )


# ---------------------------------------------------------------------------
# Evidence panel data. Pre-computed by build_evidence.py (real deterministic
# checks + real opentrons_simulate runs against files already in this repo,
# no LLM involved), stored as evidence_results.json, served as-is.
# ---------------------------------------------------------------------------

@app.get("/api/evidence")
def get_evidence():
    path = BASE_DIR / "evidence_results.json"
    if not path.exists():
        return JSONResponse(
            {"error": "evidence_results.json not found. Run `python3 build_evidence.py` first."},
            status_code=404,
        )
    return JSONResponse(json.loads(path.read_text()))


# ---------------------------------------------------------------------------
# Input-kind detection: lets one textarea + one button accept a raw English
# protocol, an already-extracted structured step JSON, or already-generated
# Opentrons Python, and route each to the right slice of the real pipeline.
# ---------------------------------------------------------------------------

def detect_input_kind(raw: str) -> str:
    stripped = raw.strip()
    if not stripped:
        return "text"
    if stripped.startswith("{"):
        try:
            obj = json.loads(stripped)
            if isinstance(obj, dict) and "steps" in obj:
                return "structured"
        except json.JSONDecodeError:
            pass
    if "protocol_api" in stripped and "def run(" in stripped:
        return "code"
    return "text"


# ---------------------------------------------------------------------------
# Violation enrichment: turns checker.py / tip_contamination.py's real
# output into the four Layer 2 items, worded for a biologist, plus the raw
# Layer 3 technical readout. This is additive reshaping only -- every
# number here is read from the real Violation/TipViolation objects and the
# real generated code, nothing is invented.
# ---------------------------------------------------------------------------

CATEGORY_BY_CODE = {
    "WELL_OVERFLOW": "volume",
    "SOURCE_DEPLETED": "volume",
    "INVALID_VOLUME": "volume",
    "USED_BEFORE_FILLED": "order",
    "ACTION_BEFORE_FILL": "order",
    "TIP_CONTAMINATION_RISK": "tip",
    "MISSING_FIELD": "data",
    "UNTRACKED_SOURCE": "data",
    "MISSING_DURATION": "data",
    "DISCARD_MISSING_SOURCE": "data",
}

CATEGORY_LABELS = {
    "volume": "Volume",
    "order": "Order",
    "tip": "Tip reuse",
    "data": "Needs review",
}

RISK_BY_CATEGORY = {
    "volume": (
        "If this step runs as written, the extra liquid has nowhere to go. It can "
        "overflow into neighboring wells, contaminating them, and the well's final "
        "reaction volume will be wrong."
    ),
    "order": (
        "The robot would draw from, incubate, or measure a well before anything has "
        "actually been put into it, since no transfer has filled that well yet at "
        "this point in the run."
    ),
    "tip": (
        "The same physical tip touched two different reagents before being "
        "replaced, so the second reagent, and everything that tip touches "
        "afterward, risks cross-contamination from the first."
    ),
    "data": (
        "Verilab could not confirm every detail of this step from the protocol "
        "text, so it is flagged here for a human to confirm before this step is "
        "trusted."
    ),
}


def humanize(identifier: str | None) -> str:
    if not identifier:
        return "this reagent"
    return identifier.replace("_", " ").replace("-", " ").strip().title()


def split_ref(ref: str | None):
    if not ref or ":" not in ref:
        return None, None
    labware_id, well = ref.split(":", 1)
    return labware_id, well


def find_code_line(code: str | None, ref: str | None):
    """Finds the generated-code line touching a given 'labware_id:well' (or,
    for tip-contamination messages, 'catalog_load_name:well') reference.
    Read-only text search over already-generated code, does not execute or
    modify generator.py."""
    if not code or not ref:
        return None, None
    labware_id, well = split_ref(ref)
    if not labware_id or not well:
        return None, None

    var_name = labware_id
    if not re.search(rf"^\s*{re.escape(labware_id)}\s*=", code, re.MULTILINE):
        for line in code.splitlines():
            m = re.match(r"\s*(\w+)\s*=\s*protocol\.load_labware\(\"([^\"]+)\"", line)
            if m and m.group(2) == labware_id:
                var_name = m.group(1)
                break

    pattern = re.compile(rf'{re.escape(var_name)}\["{re.escape(well)}"\]')
    for i, line in enumerate(code.splitlines()):
        if pattern.search(line):
            return i + 1, line.strip()
    return None, None


_OVERFLOW_RE = re.compile(r"Step (\d+): (\S+) now holds ([\d.]+) uL cumulative, exceeds ([\d.]+) uL capacity")
_DEPLETED_RE = re.compile(r"Step (\d+): (\S+) drawn beyond its capacity \(([\d.]+) uL\) across the protocol")
_USED_BEFORE_RE = re.compile(r"Step (\d+): draws from (\S+),")
_ACTION_BEFORE_RE = re.compile(r"Step (\d+): (\w+) references (\S+) before any transfer has filled it")
_TIP_RE = re.compile(r"The same tip aspirated from (\S+) and then from (\S+) without being dropped in between")


def enrich_violation(v: dict, steps: list[dict] | None, code: str | None, capacity_table: dict) -> dict:
    code_data = v["code"]
    category = CATEGORY_BY_CODE.get(code_data, "data")
    message = v["message"]
    step = steps[v["step"]] if steps and 0 <= v.get("step", -1) < len(steps) else None

    def reagent_for(ref):
        # Only ever names a reagent when real extracted step data backs it
        # up. Code-only input (no protocol text was ever read) has no
        # reagent names at all -- falling back to a labware id here would
        # silently present a container's catalog name as if it were the
        # substance inside it, which is worse than saying nothing.
        if not steps:
            return None
        if step and step.get("reagent"):
            return step["reagent"]
        for s in steps:
            if s.get("dest") == ref or s.get("source") == ref:
                if s.get("reagent"):
                    return s["reagent"]
        return None

    def capacity_lookup(ref):
        labware_id, well = split_ref(ref)
        if not labware_id:
            return None
        entry = capacity_table.get(labware_id, {})
        max_vol = entry.get(well)
        if max_vol is None:
            return None
        return {
            "labware_id": labware_id,
            "well": well,
            "max_volume_ul": max_vol,
            "resolved_as": entry.get("_resolved_as"),
        }

    layer1 = message
    numbers = ""
    location = {"step": v.get("step"), "reagent": None, "container_well": None, "code_line": None}
    resolved_capacity = None
    code_line, code_snippet = None, None

    if code_data == "WELL_OVERFLOW":
        m = _OVERFLOW_RE.search(message)
        if m:
            step_idx, dest_ref, cumulative, capacity = m.groups()
            labware_id, well = split_ref(dest_ref)
            reagent = reagent_for(dest_ref)
            reagent_phrase = reagent or "liquid"
            this_vol = step.get("volume_ul") if step else None
            layer1 = f"Step {step_idx} would put more {reagent_phrase} into well {well} than it can hold."
            if this_vol is not None:
                numbers = (
                    f"This step adds {float(this_vol):.1f} microliters of {reagent_phrase} to well {well}, "
                    f"bringing the total there to {cumulative} microliters. Well {well} holds "
                    f"{capacity} microliters maximum."
                )
            else:
                numbers = (
                    f"Well {well} now holds {cumulative} microliters total, which is more than the "
                    f"{capacity} microliters it can hold."
                )
            location = {"step": int(step_idx), "reagent": reagent, "container_well": well, "code_line": None}
            resolved_capacity = capacity_lookup(dest_ref)
            code_line, code_snippet = find_code_line(code, dest_ref)

    elif code_data == "SOURCE_DEPLETED":
        m = _DEPLETED_RE.search(message)
        if m:
            step_idx, source_ref, capacity = m.groups()
            labware_id, well = split_ref(source_ref)
            reagent = reagent_for(source_ref)
            reagent_phrase = reagent or "liquid"
            layer1 = f"Step {step_idx} draws more {reagent_phrase} out of well {well} than this protocol ever put in."
            numbers = (
                f"More than {capacity} microliters have been drawn from well {well} across the "
                f"protocol, which is more than that container holds."
            )
            location = {"step": int(step_idx), "reagent": reagent, "container_well": well, "code_line": None}
            resolved_capacity = capacity_lookup(source_ref)
            code_line, code_snippet = find_code_line(code, source_ref)

    elif code_data == "USED_BEFORE_FILLED":
        m = _USED_BEFORE_RE.search(message)
        if m:
            step_idx, source_ref = m.groups()
            labware_id, well = split_ref(source_ref)
            layer1 = f"Step {step_idx} draws from well {well} before any earlier step has filled it."
            numbers = (
                f"Well {well} is used as a source in step {step_idx}, but no transfer fills well "
                f"{well} until a later step in this protocol."
            )
            location = {"step": int(step_idx), "reagent": reagent_for(source_ref), "container_well": well, "code_line": None}
            code_line, code_snippet = find_code_line(code, source_ref)

    elif code_data == "ACTION_BEFORE_FILL":
        m = _ACTION_BEFORE_RE.search(message)
        if m:
            step_idx, action, target_ref = m.groups()
            labware_id, well = split_ref(target_ref)
            layer1 = f"Step {step_idx} would {action} well {well} before anything has been put into it."
            numbers = (
                f"The {action} step at step {step_idx} references well {well}, but no transfer "
                f"fills well {well} until a later step."
            )
            location = {"step": int(step_idx), "reagent": reagent_for(target_ref), "container_well": well, "code_line": None}
            code_line, code_snippet = find_code_line(code, target_ref)

    elif code_data == "TIP_CONTAMINATION_RISK":
        m = _TIP_RE.search(message)
        if m:
            prior, key = m.groups()
            _, prior_well = split_ref(prior)
            _, key_well = split_ref(key)
            reagent_prior = reagent_for(prior)
            reagent_key = reagent_for(key)
            if reagent_prior and reagent_key:
                layer1 = f"The same pipette tip touches {reagent_prior} and then {reagent_key} without being replaced."
                reagent_display = f"{reagent_prior} and {reagent_key}"
            else:
                layer1 = "The same pipette tip touches two different reagents in this run without being replaced."
                reagent_display = None
            numbers = (
                f"One tip aspirated from well {prior_well} and then, without dropping it, aspirated "
                f"again from well {key_well}."
            )
            location = {"step": None, "reagent": reagent_display, "container_well": f"{prior_well}, {key_well}", "code_line": None}
            code_line, code_snippet = find_code_line(code, key)

    if code_line:
        location["code_line"] = code_line

    return {
        **v,
        "category": category,
        "category_label": CATEGORY_LABELS[category],
        "layer1_summary": layer1,
        "layer2": {
            "location": location,
            "numbers": numbers,
            "risk": RISK_BY_CATEGORY[category],
            "recommended_fix": v.get("suggested_fix") or "Review this step manually; no automatic suggestion is available for this case.",
        },
        "layer3": {
            "extracted_step": step,
            "resolved_capacity": resolved_capacity,
            "generated_code_line": code_line,
            "generated_code_snippet": code_snippet,
        },
    }


def capture_transfers_and_capacities(path: str):
    """
    For already-generated code given directly as input (the overflow and
    tip-contamination demo fixtures): executes it for real, with aspirate()
    and dispense() instrumented, and pairs each dispense with whatever this
    pipette most recently aspirated, to reconstruct real (source, dest,
    volume) transfer records the same way checker.check_protocol expects.

    Keyed by each labware's real catalog load_name (not the deck slot and
    not a Python variable name that doesn't exist at this level), so the
    same location key that tip_contamination.py already uses is reused
    here, which is what lets find_code_line() below resolve either kind of
    violation back to a real line in the given code.
    """
    from opentrons.protocol_api import InstrumentContext
    from opentrons.simulate import get_protocol_api
    import importlib.util

    protocol = get_protocol_api("2.20", robot_type="Flex")
    transfers = []
    pending_aspirate: dict[int, tuple] = {}

    orig_aspirate = InstrumentContext.aspirate
    orig_dispense = InstrumentContext.dispense

    def location_key(loc):
        try:
            well_name = getattr(loc, "well_name", None)
            parent = getattr(loc, "parent", None)
            parent_name = getattr(parent, "load_name", None) or str(id(parent))
            if well_name:
                return f"{parent_name}:{well_name}"
        except Exception:
            pass
        return None

    def patched_aspirate(self, volume=None, location=None, rate=1.0):
        try:
            if location is not None and volume is not None:
                pending_aspirate[id(self)] = (float(volume), location_key(location))
        except Exception:
            pass
        return orig_aspirate(self, volume, location, rate)

    def patched_dispense(self, volume=None, location=None, rate=1.0, push_out=None):
        try:
            if location is not None and volume is not None:
                dest_key = location_key(location)
                if dest_key is not None:
                    src = pending_aspirate.get(id(self))
                    transfers.append({
                        "action": "transfer",
                        "volume_ul": float(volume),
                        "source": src[1] if src else None,
                        "dest": dest_key,
                        "reagent": None,
                    })
        except Exception:
            pass
        return orig_dispense(self, volume, location, rate, push_out)

    InstrumentContext.aspirate = patched_aspirate
    InstrumentContext.dispense = patched_dispense

    error = None
    try:
        spec = importlib.util.spec_from_file_location("verify_code_target", path)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        mod.run(protocol)
    except Exception as e:
        error = f"{type(e).__name__}: {e}"
    finally:
        InstrumentContext.aspirate = orig_aspirate
        InstrumentContext.dispense = orig_dispense

    capacities = {}
    for labware in protocol.loaded_labwares.values():
        try:
            load_name = labware.load_name
            wells = {w.well_name: w.max_volume for w in labware.wells()}
            capacities[load_name] = wells
        except Exception:
            continue

    return transfers, capacities, error


# ---------------------------------------------------------------------------
# The pipeline core. A generator so both the streaming and non-streaming
# endpoints share one real implementation: it yields ("stage", label) as
# each real stage starts, then ("final", stages_dict) once done.
# ---------------------------------------------------------------------------

def run_pipeline(protocol_text: str, protocol_name: str, input_kind: str = "auto"):
    if input_kind == "auto":
        input_kind = detect_input_kind(protocol_text)

    stages = {"input_kind": input_kind}
    stages["checks_run"] = [
        "Capacity: does every transfer fit its real container",
        "Ordering: is anything used, incubated, or measured before it exists",
        "Tip contamination: does one physical tip touch two different sources unsafely",
    ]
    stages["checks_against_text"] = CHECKS_AGAINST

    yield "stage", {"stage": "reading", "label": "Reading the protocol"}

    result = None
    steps = None
    code_from_input = None

    if input_kind == "text":
        result = extract_steps(protocol_text)
        result["steps"] = expand_dest_wells(result["steps"])
        result, remap_notes = normalize_labware_refs(result)
        label_warnings = validate_labware_ids(result)
        stages["extraction"] = {
            "skipped": False,
            "labware": result.get("labware", {}),
            "step_count": len(result.get("steps", [])),
            "remap_notes": remap_notes,
            "unresolved_warnings": label_warnings,
        }
        steps = result["steps"]

    elif input_kind == "structured":
        result = json.loads(protocol_text)
        result["steps"] = expand_dest_wells(result.get("steps", []))
        result, remap_notes = normalize_labware_refs(result)
        label_warnings = validate_labware_ids(result)
        stages["extraction"] = {
            "skipped": True,
            "reason": "Input was already structured step data. Reading the protocol text and identifying containers were not needed.",
            "labware": result.get("labware", {}),
            "step_count": len(result.get("steps", [])),
            "remap_notes": remap_notes,
            "unresolved_warnings": label_warnings,
        }
        steps = result["steps"]

    else:  # "code"
        code_from_input = protocol_text
        stages["extraction"] = {
            "skipped": True,
            "reason": "Input was already generated robot code. Reading the protocol text and identifying containers were not needed; Verilab checked the real code as given.",
        }

    yield "stage", {"stage": "identify", "label": "Identifying containers and reagents"}

    labware_for_checker = {}
    capacity_table = {}
    transfers_for_checking = None

    if input_kind in ("text", "structured"):
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            capacity_table = build_capacity_table(result.get("labware", {}))
        unresolved_labware = []
        for lw_id, wells in capacity_table.items():
            if wells.get("_unresolved"):
                unresolved_labware.append({"labware_id": lw_id, "reason": wells["_reason"]})
                continue
            clean_wells = {k: v for k, v in wells.items() if not k.startswith("_")}
            labware_for_checker[lw_id] = {"wells": clean_wells}
        stages["labware_resolution"] = {
            "unresolved": unresolved_labware,
            "capacities": {
                lw_id: {k: v for k, v in wells.items() if not k.startswith("_") or k == "_resolved_as"}
                for lw_id, wells in capacity_table.items()
                if not wells.get("_unresolved")
            },
        }
        transfers_for_checking = steps
    else:
        tmp_path = None
        try:
            with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as f:
                f.write(code_from_input)
                tmp_path = f.name
            captured, capacities_by_name, exec_error = capture_transfers_and_capacities(tmp_path)
            transfers_for_checking = captured
            capacity_table = capacities_by_name
            labware_for_checker = {name: {"wells": wells} for name, wells in capacities_by_name.items()}
            stages["labware_resolution"] = {
                "unresolved": [],
                "capacities": capacity_table,
                "note": "Capacities read directly from the real labware this code loads (this code was not re-extracted, so there is no extractor labware section to show).",
                "execution_error": exec_error,
            }
        finally:
            if tmp_path:
                os.unlink(tmp_path)

    yield "stage", {"stage": "checking", "label": "Checking volumes, order, and tip use"}

    overflow_violations = check_protocol(transfers_for_checking or [], labware_for_checker)
    ordering_violations = check_ordering(steps) if steps is not None else []
    schema_violations = overflow_violations + ordering_violations
    has_blocking_errors = any(v.severity == "error" for v in schema_violations)

    yield "stage", {"stage": "generating", "label": "Preparing robot code"}

    tip_violations = []
    generated_code = None

    if input_kind == "code":
        generated_code = code_from_input
        stages["generated_code"] = {
            "code": generated_code,
            "note": "This code was provided as input; nothing new was generated.",
        }
        tmp_path = None
        try:
            with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as f:
                f.write(generated_code)
                tmp_path = f.name
            tip_violations, tip_error = check_tip_contamination(tmp_path)
            if tip_error:
                stages["tip_check_note"] = f"Execution stopped: {tip_error}"
        finally:
            if tmp_path:
                os.unlink(tmp_path)

    elif not has_blocking_errors:
        try:
            code, gen_warnings = generate_protocol(result, protocol_name=protocol_name)
            generated_code = code
            stages["generated_code"] = {"code": code, "warnings": gen_warnings}
            tmp_path = None
            try:
                with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as f:
                    f.write(code)
                    tmp_path = f.name
                tip_violations, tip_error = check_tip_contamination(tmp_path)
                if tip_error:
                    stages["tip_check_note"] = f"Execution stopped: {tip_error}"
            finally:
                if tmp_path:
                    os.unlink(tmp_path)
        except Exception as e:
            stages["generated_code"] = {"error": str(e)}
    else:
        stages["generated_code"] = {
            "skipped": True,
            "reason": "Blocking problems were found before code generation; nothing is generated until they're fixed.",
        }

    raw_violations = [
        {
            "step": v.step_index,
            "severity": v.severity,
            "code": v.code,
            "message": v.message,
            "suggested_fix": v.suggested_fix,
        }
        for v in schema_violations
    ] + [
        {
            "step": None,
            "severity": tv.severity,
            "code": tv.code,
            "message": tv.message,
            "suggested_fix": tv.suggested_fix,
        }
        for tv in tip_violations
    ]

    enriched = [enrich_violation(v, steps, generated_code, capacity_table) for v in raw_violations]
    error_count = sum(1 for v in enriched if v["severity"] == "error")
    warning_count = sum(1 for v in enriched if v["severity"] == "warning")

    stages["checks"] = {
        "violation_count": len(enriched),
        "error_count": error_count,
        "warning_count": warning_count,
        "violations": enriched,
    }

    if steps is not None:
        stages["resources"] = {"summary_text": resource_summary(steps)}
    elif transfers_for_checking:
        stages["resources"] = {"summary_text": resource_summary(transfers_for_checking)}
    else:
        stages["resources"] = {"summary_text": "No structured step data was available to total reagent volumes."}

    final_blocking = has_blocking_errors or any(tv.severity == "error" for tv in tip_violations)
    stages["overall_status"] = "BLOCKED" if final_blocking else "CLEARED"

    yield "final", stages


def collect_result(protocol_text: str, protocol_name: str, input_kind: str = "auto") -> dict:
    result = None
    for kind, payload in run_pipeline(protocol_text, protocol_name, input_kind):
        if kind == "final":
            result = payload
    return result


@app.post("/api/verify")
def verify(req: VerifyRequest, request: Request):
    limited = check_rate_limit(request)
    if limited:
        return limited
    try:
        result = collect_result(req.protocol_text, req.protocol_name, req.input_kind)
        return JSONResponse(result)
    except Exception as e:
        return JSONResponse(
            {"error": str(e), "trace": traceback.format_exc()},
            status_code=500,
        )


@app.post("/api/verify/stream")
def verify_stream(req: VerifyRequest, request: Request):
    limited = check_rate_limit(request)
    if limited:
        return limited

    def gen():
        try:
            for kind, payload in run_pipeline(req.protocol_text, req.protocol_name, req.input_kind):
                if kind == "stage":
                    yield json.dumps({"type": "stage", **payload}) + "\n"
                else:
                    yield json.dumps({"type": "final", "result": payload}) + "\n"
        except Exception as e:
            yield json.dumps({"type": "error", "error": str(e), "trace": traceback.format_exc()}) + "\n"

    return StreamingResponse(gen(), media_type="application/x-ndjson")


STATIC_DIR = BASE_DIR / "static"
if STATIC_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


@app.get("/", response_class=HTMLResponse)
def index():
    index_path = STATIC_DIR / "index.html"
    return HTMLResponse(index_path.read_text())
