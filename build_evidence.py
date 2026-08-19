"""
Evidence builder for the Verification Console's evidence panel.

Runs the REAL deterministic pieces of the pipeline (checker.py,
labware_resolver.py, tip_contamination.py) against files already stored in
this repo, plus the real Opentrons simulator against the already-generated
naive baseline files, and writes the results to evidence_results.json.

Deliberately does not call the extractor (no LLM, no API key needed), so
this is fully reproducible offline. Nothing in this file modifies or
reimplements checker.py, labware_resolver.py, tip_contamination.py, or
generator.py -- it only calls them and records what they actually returned.

Re-run this any time the underlying test_protocols/, demo/, or ground_truth/
fixtures change:

    python3 build_evidence.py
"""

import io
import contextlib
import json
import subprocess
from datetime import datetime, timezone

from checker import check_protocol, check_ordering
from labware_resolver import build_capacity_table
from tip_contamination import check_tip_contamination

TEST_SUITE_PROTOCOLS = [
    "protocol_01", "protocol_02", "protocol_04", "protocol_07",
    "protocol_08", "protocol_09", "protocol_10", "protocol_11", "protocol_12",
]
BASELINE_PROTOCOLS = ["protocol_01", "protocol_02", "protocol_04", "protocol_07"]


def run_checks_on_extracted(name: str) -> dict:
    path = f"test_protocols/{name}_extracted.json"
    with open(path) as f:
        result = json.load(f)

    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        capacity_table = build_capacity_table(result.get("labware", {}))

    labware_for_checker = {}
    unresolved = []
    for lw_id, wells in capacity_table.items():
        if wells.get("_unresolved"):
            unresolved.append(lw_id)
            continue
        clean_wells = {k: v for k, v in wells.items() if not k.startswith("_")}
        labware_for_checker[lw_id] = {"wells": clean_wells}

    overflow = check_protocol(result["steps"], labware_for_checker)
    ordering = check_ordering(result["steps"])
    all_v = overflow + ordering
    errors = [v for v in all_v if v.severity == "error"]
    warnings = [v for v in all_v if v.severity == "warning"]

    if errors:
        status = "findings"
    elif warnings:
        status = "clean_with_warnings"
    else:
        status = "clean"

    return {
        "name": name,
        "step_count": len(result.get("steps", [])),
        "unresolved_labware_count": len(unresolved),
        "error_count": len(errors),
        "warning_count": len(warnings),
        "status": status,
    }


def simulate_baseline(name: str) -> dict:
    path = f"test_protocols/{name}_baseline.py"
    try:
        result = subprocess.run(
            ["opentrons_simulate", path], capture_output=True, text=True, timeout=60
        )
        success = result.returncode == 0
        output = result.stdout if success else (result.stderr + result.stdout)
    except Exception as e:
        success = False
        output = str(e)

    reason = None
    if not success:
        lines = [l.strip() for l in output.splitlines() if l.strip()]
        # keep the single most specific error line, not the whole traceback
        reason = next(
            (l for l in reversed(lines) if "Error" in l or "error" in l),
            lines[-1] if lines else "unknown simulator failure",
        )

    return {"name": name, "simulated_successfully": success, "failure_reason": reason}


def build_baseline_comparison() -> dict:
    baseline_results = [simulate_baseline(n) for n in BASELINE_PROTOCOLS]
    pipeline_results = {n: run_checks_on_extracted(n) for n in BASELINE_PROTOCOLS}

    naive_ok = [r for r in baseline_results if r["simulated_successfully"]]
    naive_fail = [r for r in baseline_results if not r["simulated_successfully"]]

    cleared = [n for n in BASELINE_PROTOCOLS if pipeline_results[n]["status"] != "findings"]
    blocked = [n for n in BASELINE_PROTOCOLS if pipeline_results[n]["status"] == "findings"]

    return {
        "description": (
            "Same protocols, two approaches: one naive single-prompt call straight to "
            "generated robot code, versus the full Verilab pipeline (extract, resolve "
            "real labware, check, then generate)."
        ),
        "protocols_tested": len(BASELINE_PROTOCOLS),
        "naive_simulated_successfully": len(naive_ok),
        "naive_failures": [
            {"protocol": r["name"], "reason": r["failure_reason"]} for r in naive_fail
        ],
        "pipeline_cleared_count": len(cleared),
        "pipeline_cleared_protocols": cleared,
        "pipeline_blocked_count": len(blocked),
        "pipeline_blocked_protocols": [
            {"protocol": n, "finding_count": pipeline_results[n]["error_count"]}
            for n in blocked
        ],
    }


def build_test_suite() -> dict:
    protocols = [run_checks_on_extracted(n) for n in TEST_SUITE_PROTOCOLS]
    clean = [p for p in protocols if p["status"] == "clean"]
    clean_warn = [p for p in protocols if p["status"] == "clean_with_warnings"]
    findings = [p for p in protocols if p["status"] == "findings"]
    return {
        "description": (
            "Every real, published wet-lab protocol run through the full deterministic "
            "checker (volume capacity, source depletion, and step ordering) using its "
            "already-extracted step data, no live model call required to reproduce this."
        ),
        "total_protocols": len(protocols),
        "clean_count": len(clean),
        "clean_with_warnings_count": len(clean_warn),
        "findings_count": len(findings),
        "protocols": protocols,
    }


def build_false_alarms() -> list:
    cases = []

    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        v1, err1 = check_tip_contamination("test_protocols/protocol_01_generated.py")
    cases.append({
        "case": "The generator's normal fresh-tip pattern",
        "description": (
            "protocol_01's real generated code makes 208 separate transfer() calls, "
            "alternating between two different source reservoirs (spore stock, then "
            "media). Each transfer() call picks up its own fresh tip and drops it "
            "before the next one starts, which is the generator's default, unmodified "
            "behavior."
        ),
        "source_file": "test_protocols/protocol_01_generated.py",
        "execution_error": err1,
        "violations_found": len(v1),
        "result": "PASS: no tip contamination risk found." if not v1 else f"FAIL: {len(v1)} flagged",
    })

    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        v2, err2 = check_tip_contamination("demo/legit_same_source_demo.py")
    cases.append({
        "case": "Legitimate same-source-twice transfer",
        "description": (
            "One tip is picked up once and used to aspirate from the SAME reservoir "
            "well three separate times, dispensing into three different plate wells, "
            "before that one tip is dropped. This is normal bench practice (one "
            "reservoir feeding several wells of the same reagent) and must not be "
            "flagged as contamination."
        ),
        "source_file": "demo/legit_same_source_demo.py",
        "execution_error": err2,
        "violations_found": len(v2),
        "result": "PASS: no tip contamination risk found." if not v2 else f"FAIL: {len(v2)} flagged",
    })

    return cases


def main():
    evidence = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "baseline_comparison": build_baseline_comparison(),
        "test_suite": build_test_suite(),
        "false_alarms": build_false_alarms(),
        "scope_note": (
            "Currently validated on the Opentrons Flex only. Support for other robot "
            "platforms is a planned next step, not a current claim."
        ),
    }
    with open("evidence_results.json", "w") as f:
        json.dump(evidence, f, indent=2)
    print("Wrote evidence_results.json")
    print(json.dumps(evidence, indent=2))


if __name__ == "__main__":
    main()
