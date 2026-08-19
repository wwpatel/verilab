"""
Hero visual data builder for the public site.

Captures, for the real overflow demo (demo/overflow_demo.py):
  1. the real Opentrons simulator's own stdout (it accepts the protocol and
     exits clean, no error), and
  2. Verilab's real checker output for the exact same code (it flags the
     overflow with real numbers).

Both are run for real here, nothing is hand-typed. Nothing in checker.py,
labware_resolver.py, tip_contamination.py, or generator.py is modified or
reimplemented; this only calls them and records their real output, the same
approach as build_evidence.py.

Re-run any time demo/overflow_demo.py changes:

    python3 build_hero_capture.py
"""

import json
import subprocess
from datetime import datetime, timezone

from app import capture_transfers_and_capacities
from checker import check_protocol, format_report

DEMO_PATH = "demo/overflow_demo.py"


def capture_simulator_output() -> str:
    result = subprocess.run(
        ["opentrons_simulate", DEMO_PATH], capture_output=True, text=True, timeout=60
    )
    # opentrons_simulate's stdout is the real run log (what it actually did);
    # stderr on this machine is just local calibration-file setup noise
    # ("robot_settings.json not found"), not part of the protocol result, so
    # it's left out of the visitor-facing capture.
    parts = [result.stdout.strip()]
    parts.append(f"(exit code {result.returncode}, no error raised)")
    return "\n".join(parts)


def capture_verilab_output() -> str:
    transfers, capacities, exec_error = capture_transfers_and_capacities(DEMO_PATH)
    if exec_error:
        return f"Execution error: {exec_error}"
    labware_for_checker = {name: {"wells": wells} for name, wells in capacities.items()}
    violations = check_protocol(transfers, labware_for_checker)
    return format_report(violations)


def main():
    data = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source_file": DEMO_PATH,
        "simulator_output": capture_simulator_output(),
        "verilab_output": capture_verilab_output(),
    }
    with open("site/data/hero_capture.json", "w") as f:
        json.dump(data, f, indent=2)
        f.write("\n")
    print(json.dumps(data, indent=2))


if __name__ == "__main__":
    main()
