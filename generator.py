"""
Code generator node.

Takes the VERIFIED structured step list (post-extractor, post-checker) and
emits an Opentrons Flex Python protocol.

Design note: the deck layout (which labware sits in which slot) and the
pipette selection are decided HERE, in Python, not by the LLM. Slot
assignment is a bookkeeping problem with hard constraints -- there are a
fixed number of slots, each holds one item, the trash needs one -- and a
model that hallucinates a slot produces code that fails to simulate. The
LLM's job upstream was reading English; it is not needed for this.
"""

import json
import sys

from labware_resolver import resolve_labware_type

# Flex deck slots, excluding A3 which we reserve for the trash bin.
FLEX_SLOTS = ["A1", "A2", "B1", "B2", "B3", "C1", "C2", "C3", "D1", "D2", "D3"]

# Flex pipettes: (name, min_volume_ul, max_volume_ul, matching tiprack)
FLEX_PIPETTES = [
    ("flex_1channel_50", 1, 50, "opentrons_flex_96_tiprack_50ul"),
    ("flex_1channel_1000", 5, 1000, "opentrons_flex_96_tiprack_1000ul"),
]


def choose_pipette(steps: list[dict]) -> tuple[str, str]:
    """
    Pick the smallest pipette that covers every transfer volume in the
    protocol. Volumes larger than the max are handled by Opentrons itself
    (it splits them), so we select on the MINIMUM volume -- using a
    1000uL pipette to move 2uL is inaccurate, which is a real
    experimental-validity problem, not just a style choice.
    """
    volumes = [
        s["volume_ul"] for s in steps
        if s.get("action") == "transfer" and s.get("volume_ul")
    ]
    if not volumes:
        return FLEX_PIPETTES[1][0], FLEX_PIPETTES[1][3]

    smallest = min(volumes)
    for name, min_v, max_v, tiprack in FLEX_PIPETTES:
        if smallest >= min_v:
            return name, tiprack
    # nothing covers it -- fall back to the smallest pipette available
    return FLEX_PIPETTES[0][0], FLEX_PIPETTES[0][3]


def assign_deck(labware: dict) -> tuple[dict, list[str]]:
    """
    Map each labware_id -> (catalog_name, slot). Returns (assignments, warnings).
    Labware that can't be resolved to a real catalog item is reported, not
    silently dropped -- generating code that references imaginary labware
    would fail at simulation anyway, better to say so here.
    """
    assignments = {}
    warnings = []
    slot_iter = iter(FLEX_SLOTS)

    for labware_id, meta in labware.items():
        catalog_name = resolve_labware_type(meta.get("description", ""))
        if catalog_name is None:
            warnings.append(
                f"{labware_id}: no catalog match for '{meta.get('description')}' "
                f"-- omitted from generated code, human must map this manually"
            )
            continue
        try:
            slot = next(slot_iter)
        except StopIteration:
            warnings.append(f"{labware_id}: ran out of deck slots")
            continue
        assignments[labware_id] = (catalog_name, slot)

    return assignments, warnings


def generate_protocol(result: dict, protocol_name: str = "Generated Protocol") -> tuple[str, list[str]]:
    labware = result.get("labware", {})
    steps = result.get("steps", [])

    assignments, warnings = assign_deck(labware)
    pipette_name, tiprack_name = choose_pipette(steps)

    lines = []
    lines.append("from opentrons import protocol_api")
    lines.append("")
    lines.append(f'metadata = {{"protocolName": "{protocol_name}", "author": "generated"}}')
    lines.append('requirements = {"robotType": "Flex", "apiLevel": "2.20"}')
    lines.append("")
    lines.append("")
    lines.append("def run(protocol: protocol_api.ProtocolContext):")

    # labware loading
    for labware_id, (catalog_name, slot) in assignments.items():
        lines.append(f'    {labware_id} = protocol.load_labware("{catalog_name}", "{slot}")')

    # tipracks: one 96-tip rack per ~96 transfers isn't enough if we always
    # assume exactly one -- count the real transfers needing a tip and load
    # as many racks as that requires, or the run dies partway through
    # (OutOfTipsError) on any protocol with more than 96 pipetting actions.
    countable_transfers = sum(
        1 for s in steps
        if s.get("action") == "transfer" and s.get("volume_ul") and s.get("dest") and s.get("source")
    )
    TIPS_PER_RACK = 96
    import math
    n_tipracks = max(1, math.ceil(countable_transfers / TIPS_PER_RACK)) if countable_transfers else 1

    used_slots = {slot for _, slot in assignments.values()}
    free = [s for s in FLEX_SLOTS if s not in used_slots]

    tiprack_vars = []
    for idx in range(n_tipracks):
        if idx >= len(free):
            warnings.append(
                f"only {len(free)} deck slot(s) free but {n_tipracks} tiprack(s) "
                f"needed for {countable_transfers} transfers -- protocol will run "
                f"out of tips partway through"
            )
            break
        slot = free[idx]
        var_name = f"tiprack_{idx + 1}" if n_tipracks > 1 else "tiprack"
        lines.append(f'    {var_name} = protocol.load_labware("{tiprack_name}", "{slot}")')
        tiprack_vars.append(var_name)

    lines.append('    protocol.load_trash_bin("A3")')
    tip_racks_arg = "[" + ", ".join(tiprack_vars) + "]"
    lines.append(
        f'    pipette = protocol.load_instrument("{pipette_name}", "left", tip_racks={tip_racks_arg})'
    )
    lines.append("")

    # steps
    emitted = 0
    for i, step in enumerate(steps):
        action = step.get("action")

        if action == "transfer":
            volume = step.get("volume_ul")
            source = step.get("source")
            dest = step.get("dest")

            if volume is None or dest is None:
                lines.append(f"    # SKIPPED step {i}: missing volume or destination")
                continue
            if source is None:
                lines.append(
                    f"    # MANUAL step {i}: add {volume} uL of "
                    f'{step.get("reagent") or "reagent"} to {dest} '
                    f"(off-deck reagent, not automated)"
                )
                continue

            src_lw, src_well = source.split(":", 1)
            dst_lw, dst_well = dest.split(":", 1)
            if src_lw not in assignments or dst_lw not in assignments:
                lines.append(
                    f"    # SKIPPED step {i}: {source} -> {dest} "
                    f"(labware not mapped to deck)"
                )
                continue

            lines.append(
                f'    pipette.transfer({volume}, {src_lw}["{src_well}"], '
                f'{dst_lw}["{dst_well}"])'
            )
            emitted += 1

        elif action in ("wait", "incubate"):
            duration = step.get("duration_s")
            if duration:
                lines.append(f"    protocol.delay(seconds={duration})")
                emitted += 1
            else:
                lines.append(f"    # step {i}: {action} with unspecified duration")

        elif action == "external_instrument":
            lines.append(
                f'    # EXTERNAL step {i}: {step.get("instrument_name")} -- '
                f'{step.get("instrument_action")}'
            )
            lines.append("    protocol.pause(")
            lines.append(
                f'        "Manual step: {step.get("instrument_name")}. '
                f'Resume when complete."'
            )
            lines.append("    )")
            emitted += 1

        elif action == "mix":
            lines.append(f"    # step {i}: mix (vortex/manual, not automated)")

    if emitted == 0:
        lines.append("    pass  # no automatable steps found")

    return "\n".join(lines) + "\n", warnings


if __name__ == "__main__":
    path = sys.argv[1] if len(sys.argv) > 1 else None
    if not path:
        print("Usage: python3 generator.py test_protocols/protocol_01_extracted.json")
        sys.exit(1)
    if not path.endswith("_extracted.json"):
        print(
            f"Refusing to run: '{path}' doesn't end in '_extracted.json'. "
            f"The output filename is derived by replacing that suffix -- if it's "
            f"not there, the output path would collide with the input path and "
            f"OVERWRITE your extracted data. Rename the file (or point this at "
            f"the real extractor output) and try again."
        )
        sys.exit(1)

    with open(path) as f:
        result = json.load(f)

    name = path.split("/")[-1].replace("_extracted.json", "")
    code, warnings = generate_protocol(result, protocol_name=name)

    out_path = path.replace("_extracted.json", "_generated.py")
    assert out_path != path, "internal error: output path must differ from input path"
    with open(out_path, "w") as f:
        f.write(code)

    print(f"Generated Opentrons protocol -> {out_path}")
    if warnings:
        print(f"\n{len(warnings)} generation warning(s):")
        for w in warnings:
            print(f"  WARNING: {w}")
    print(f"\nNext: opentrons_simulate {out_path}")
