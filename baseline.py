"""
Baseline: single naive prompt approach.

Takes raw protocol text, asks the model directly for Opentrons Python code
in ONE call -- no structured extraction, no reconciliation checker, no
labware resolver. This is the thing your pipeline is measured against.

Also includes a post-hoc overflow scan: parses the naive-generated code's
own transfer() calls and runs them through the SAME deterministic checker
your pipeline uses. This answers the real question -- not just "did it
simulate," but "does naive-generated code have the same class of overflow
bug the simulator itself can't catch."
"""

import ast
import os
import re
import subprocess
import sys

from anthropic import Anthropic
from checker import check_protocol, format_report

client = Anthropic(api_key=os.environ.get("ANTHROPIC_API_KEY"))

NAIVE_SYSTEM_PROMPT = """Convert the following wet-lab protocol into a working
Opentrons Flex Python protocol (API 2.20). Output ONLY the Python code, no
markdown fences, no explanation."""


def naive_generate(protocol_text: str, model: str = "claude-sonnet-4-6") -> str:
    response = client.messages.create(
        model=model,
        max_tokens=8000,
        system=NAIVE_SYSTEM_PROMPT,
        messages=[{"role": "user", "content": protocol_text}],
    )
    raw = response.content[0].text.strip()
    if raw.startswith("```"):
        raw = raw.strip("`")
        if raw.startswith("python"):
            raw = raw[6:]
    return raw.strip()


def simulate(path: str) -> tuple[bool, str]:
    result = subprocess.run(
        ["opentrons_simulate", path], capture_output=True, text=True, timeout=60
    )
    success = result.returncode == 0
    output = result.stdout if success else (result.stderr + result.stdout)
    return success, output


def run_and_analyze(path: str) -> tuple[list[dict], dict, str | None]:
    """
    Runs the generated protocol ONCE, with dispense() monkeypatched to
    record real (volume, slot, well_name) as it happens, and reads real
    well capacities from whatever Opentrons actually loaded onto the deck.

    Keyed by DECK SLOT, not catalog name -- two plates of the same catalog
    type (e.g. protocol_02's pcr_plate and dna_plate, both
    opentrons_96_wellplate_200ul_pcr_full_skirt) are different physical
    labware and must never be merged into one tracked well just because
    they share a product name. A wrong merge here would silently produce
    an incorrect overflow verdict, which is worse than no verdict.

    Returns (transfers, capacities, error). Partial results before a
    crash are still returned, since partial real data beats none.
    """
    import importlib.util
    from opentrons.protocol_api import InstrumentContext
    from opentrons.simulate import get_protocol_api

    protocol = get_protocol_api("2.20", robot_type="Flex")
    captured = []
    orig_dispense = InstrumentContext.dispense

    def slot_for(labware_obj) -> str:
        for slot, lw in protocol.loaded_labwares.items():
            if lw is labware_obj:
                return str(slot)
        return f"offdeck_{id(labware_obj)}"

    def patched_dispense(self, volume=None, location=None, rate=1.0, push_out=None):
        try:
            well = location if hasattr(location, "well_name") else getattr(location, "labware", None)
            well_name = getattr(well, "well_name", None) if well is not None else None
            parent = getattr(well, "parent", None) if well is not None else None
            if volume is not None and well_name is not None and parent is not None:
                slot = slot_for(parent)
                captured.append({
                    "action": "transfer",
                    "volume_ul": float(volume),
                    "source": None,
                    "dest": f"{slot}:{well_name}",
                })
        except Exception:
            pass  # instrumentation must never break the real run
        return orig_dispense(self, volume, location, rate, push_out)

    InstrumentContext.dispense = patched_dispense
    error = None
    try:
        spec = importlib.util.spec_from_file_location("generated_baseline", path)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        mod.run(protocol)
    except Exception as e:
        error = f"{type(e).__name__}: {e}"
    finally:
        InstrumentContext.dispense = orig_dispense

    capacities = {}
    for slot, labware in protocol.loaded_labwares.items():
        try:
            wells = {w.well_name: w.max_volume for w in labware.wells()}
            capacities[str(slot)] = {"wells": wells}
        except Exception:
            continue

    return captured, capacities, error


def run_baseline(protocol_path: str, name: str = None):
    with open(protocol_path) as f:
        protocol_text = f.read()

    name = name or protocol_path.split("/")[-1].replace(".txt", "")
    code = naive_generate(protocol_text)

    out_path = protocol_path.replace(".txt", "_baseline.py")
    with open(out_path, "w") as f:
        f.write(code)

    sim_ok, sim_output = simulate(out_path)

    transfers, capacities, exec_error = run_and_analyze(out_path)
    violations = check_protocol(transfers, capacities) if transfers and capacities else []

    print(f"\n{'='*60}")
    print(f"BASELINE (single prompt): {name}")
    print(f"{'='*60}")
    print(f"Simulator result: {'PASS' if sim_ok else 'FAIL'}")
    if not sim_ok:
        lines = [l for l in sim_output.splitlines() if l.strip()]
        for l in lines[-3:]:
            print(f"  {l}")
    print(f"\nOverflow scan (executed the real code, same checker your pipeline uses):")
    if exec_error:
        print(f"  Execution stopped early: {exec_error}")
    print(f"  {len(transfers)} real dispense call(s) captured before "
          f"{'completion' if not exec_error else 'the error above'}")
    if violations:
        print(format_report(violations))
    elif transfers:
        print("  No overflow detected in captured calls")
    else:
        print("  No dispense calls captured (protocol may have failed before any liquid handling)")
    print(f"{'='*60}\n")

    return {"simulate_pass": sim_ok, "violations": len(violations), "code_path": out_path}


if __name__ == "__main__":
    path = sys.argv[1] if len(sys.argv) > 1 else None
    if not path:
        print("Usage: python3 baseline.py test_protocols/protocol_01.txt")
        sys.exit(1)
    run_baseline(path)
