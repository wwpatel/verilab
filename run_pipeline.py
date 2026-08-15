"""
Pipeline runner: extracted JSON -> resolved capacities -> checker report.

Usage:
    python3 run_pipeline.py test_protocols/protocol_01_extracted.json
"""

import json
import sys

from checker import check_protocol, format_report
from labware_resolver import build_capacity_table


def run_pipeline(extracted_path: str):
    with open(extracted_path) as f:
        result = json.load(f)

    # 1. resolve real well capacities from the Opentrons catalog
    #    (suppress opentrons' own noisy stdout during simulation setup)
    import io, contextlib
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        capacity_table = build_capacity_table(result.get("labware", {}))

    unresolved = [lw_id for lw_id, wells in capacity_table.items() if wells.get("_unresolved")]
    if unresolved:
        print(f"NOTE: {len(unresolved)} labware entr{'y' if len(unresolved)==1 else 'ies'} "
              f"could not be matched to a real catalog item, so overflow checks are skipped for them:")
        for lw_id in unresolved:
            print(f"  - {lw_id}: {capacity_table[lw_id]['_reason']}")

    # 2. reshape into what checker.py expects: {labware_id: {"wells": {well: cap}}}
    labware_for_checker = {}
    for lw_id, wells in capacity_table.items():
        if wells.get("_unresolved"):
            continue
        clean_wells = {k: v for k, v in wells.items() if not k.startswith("_")}
        labware_for_checker[lw_id] = {"wells": clean_wells}

    # 3. flatten external_instrument / non-liquid-handling steps out before checking
    #    (checker only understands transfer/wait actions; opaque steps pass through untouched)
    checkable_steps = [s for s in result.get("steps", []) if s.get("action") in ("transfer", "wait", "discard")]
    skipped = len(result.get("steps", [])) - len(checkable_steps)

    # 4. run the actual deterministic check
    violations = check_protocol(checkable_steps, labware_for_checker)

    print(f"\n{'='*60}")
    print(f"Protocol: {extracted_path}")
    print(f"{len(checkable_steps)} liquid-handling steps checked "
          f"({skipped} non-liquid-handling steps skipped)")
    print(format_report(violations))
    print(f"{'='*60}\n")

    return violations


if __name__ == "__main__":
    path = sys.argv[1] if len(sys.argv) > 1 else None
    if not path:
        print("Usage: python3 run_pipeline.py test_protocols/protocol_01_extracted.json")
        sys.exit(1)
    run_pipeline(path)
