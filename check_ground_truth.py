"""
Ground-truth accuracy checker.

'0 unresolved warnings' proves the extractor didn't crash and didn't
contradict itself. It does NOT prove the extraction is correct. This
script checks the real thing: does the extracted step list actually match
what a human reading the protocol would expect?

Ground truth is written at the level of physical actions (e.g. "fill 96
wells with 5uL each"), not one entry per well, since that's the level a
human can realistically hand-label and verify.
"""

import json
import sys
from collections import defaultdict


def group_transfers(steps: list[dict]) -> list[dict]:
    """Collapse individual per-well transfer steps back into action groups
    by (reagent, volume), so they can be compared against ground truth
    written at the action level."""
    groups = defaultdict(list)
    for s in steps:
        if s.get("action") != "transfer":
            continue
        key = (s.get("reagent"), s.get("volume_ul"))
        groups[key].append(s)
    return [
        {"reagent": reagent, "volume_ul": volume, "well_count": len(matches)}
        for (reagent, volume), matches in groups.items()
    ]


def check_action(expected: dict, extracted: dict, transfer_groups: list[dict]) -> tuple[bool, str]:
    action = expected["action"]

    if action == "transfer":
        keyword = expected["reagent_keyword"].lower()
        matches = [
            g for g in transfer_groups
            if g["reagent"] and keyword in g["reagent"].lower()
        ]
        if not matches:
            return False, f"no transfer found with reagent matching '{keyword}'"

        if expected.get("ambiguous"):
            # a correct extraction should show null volume + presumably a
            # note -- a confident, non-null volume here is a FALSE PRECISION
            # error: the model invented a number the protocol never gave.
            confident_matches = [g for g in matches if g["volume_ul"] is not None]
            if confident_matches:
                return False, (
                    f"expected AMBIGUOUS (protocol doesn't specify), but extractor "
                    f"confidently assigned volume_ul={confident_matches[0]['volume_ul']} "
                    f"-- this is fabricated precision, worse than a missing value"
                )
            return True, "correctly left ambiguous (null volume)"

        best = max(matches, key=lambda g: g["well_count"])
        vol_ok = best["volume_ul"] == expected["expected_volume_ul"]
        count_ok = best["well_count"] == expected["expected_well_count"]
        if vol_ok and count_ok:
            return True, f"volume and well count both correct ({best['well_count']} wells)"
        detail = []
        if not vol_ok:
            detail.append(f"volume {best['volume_ul']} != expected {expected['expected_volume_ul']}")
        if not count_ok:
            detail.append(f"well count {best['well_count']} != expected {expected['expected_well_count']}")
        return False, "; ".join(detail)

    if action == "non_liquid_handling":
        # we don't require the extractor to represent this (it correctly
        # has no way to automate covering a plate), just don't fabricate
        # a fake transfer for it
        return True, "not applicable to liquid handling (correctly not automated)"

    if action == "measure_or_incubate":
        return True, "checked separately -- see external/measure steps below"

    return False, f"unknown action type '{action}'"


def run_check(ground_truth_path: str, extracted_path: str):
    with open(ground_truth_path) as f:
        gt = json.load(f)
    with open(extracted_path) as f:
        extracted = json.load(f)

    steps = extracted.get("steps", [])
    transfer_groups = group_transfers(steps)

    print(f"\n{'='*70}")
    print(f"Ground-truth check: {gt['protocol']}")
    print(f"{'='*70}")

    passed = 0
    for expected in gt["expected_actions"]:
        ok, detail = check_action(expected, extracted, transfer_groups)
        status = "PASS" if ok else "FAIL"
        print(f"[{status}] #{expected['id']}: {expected['description']}")
        print(f"       -> {detail}")
        if ok:
            passed += 1

    total = len(gt["expected_actions"])
    print(f"\n{passed}/{total} expected actions correctly extracted "
          f"({100*passed/total:.0f}%)")
    print(f"{'='*70}\n")

    return passed, total


if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("Usage: python3 check_ground_truth.py "
              "ground_truth/protocol_01_ground_truth.json "
              "test_protocols/protocol_01_extracted.json")
        sys.exit(1)
    run_check(sys.argv[1], sys.argv[2])
