"""
Tip contamination checker.

Same technique as baseline.py's dispense tracer: run the generated code for
real, with the relevant pipette methods intercepted, and watch what actually
happens. This lives at the code-execution level rather than the structured
step schema, on purpose -- tip identity (which physical tip is currently on
the pipette, whether it's been dropped) isn't something the extractor's JSON
represents at all. It only exists once code runs.

The rule: one physical tip aspirating from two DIFFERENT source locations
before being dropped is a real contamination risk, regardless of what the
two reagents are called. The same tip touching the same source twice (e.g.
one tip distributing from a single reservoir to many wells) is normal and
must not be flagged -- that distinction is the whole point of tracking
location identity rather than just counting aspirate calls.
"""

import importlib.util
from dataclasses import dataclass


@dataclass
class TipViolation:
    severity: str
    code: str
    message: str
    suggested_fix: str = ""


def check_tip_contamination(path: str) -> tuple[list[TipViolation], str | None]:
    from opentrons.protocol_api import InstrumentContext
    from opentrons.simulate import get_protocol_api

    violations: list[TipViolation] = []
    protocol = get_protocol_api("2.20", robot_type="Flex")

    # state, keyed by pipette instance id since a protocol may use more than one
    current_tip: dict[int, str] = {}          # pipette id -> tip identity (rack:well)
    sources_since_pickup: dict[int, set] = {}  # pipette id -> set of source locations touched

    orig_pick_up = InstrumentContext.pick_up_tip
    orig_drop = InstrumentContext.drop_tip
    orig_aspirate = InstrumentContext.aspirate

    def location_key(loc):
        try:
            well_name = getattr(loc, "well_name", None)
            parent = getattr(loc, "parent", None)
            parent_name = getattr(parent, "load_name", None) or str(id(parent))
            if well_name:
                return f"{parent_name}:{well_name}"
        except Exception:
            pass
        return str(loc)

    def patched_pick_up_tip(self, *args, **kwargs):
        sources_since_pickup[id(self)] = set()
        return orig_pick_up(self, *args, **kwargs)

    def patched_drop_tip(self, *args, **kwargs):
        sources_since_pickup[id(self)] = set()
        return orig_drop(self, *args, **kwargs)

    def patched_aspirate(self, volume=None, location=None, rate=1.0):
        try:
            if location is not None:
                key = location_key(location)
                touched = sources_since_pickup.setdefault(id(self), set())
                if touched and key not in touched:
                    prior = next(iter(touched))
                    violations.append(TipViolation(
                        "error", "TIP_CONTAMINATION_RISK",
                        f"The same tip aspirated from {prior} and then from {key} "
                        f"without being dropped in between",
                        suggested_fix=(
                            f"Add a drop_tip() and pick_up_tip() between the "
                            f"transfer from {prior} and the transfer from {key}, "
                            f"or confirm both locations intentionally hold the "
                            f"same reagent."
                        ),
                    ))
                touched.add(key)
        except Exception:
            pass  # instrumentation must never break the real run
        return orig_aspirate(self, volume, location, rate)

    InstrumentContext.pick_up_tip = patched_pick_up_tip
    InstrumentContext.drop_tip = patched_drop_tip
    InstrumentContext.aspirate = patched_aspirate

    error = None
    try:
        spec = importlib.util.spec_from_file_location("tip_check_target", path)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        mod.run(protocol)
    except Exception as e:
        error = f"{type(e).__name__}: {e}"
    finally:
        InstrumentContext.pick_up_tip = orig_pick_up
        InstrumentContext.drop_tip = orig_drop
        InstrumentContext.aspirate = orig_aspirate

    return violations, error


def format_tip_report(violations: list[TipViolation]) -> str:
    if not violations:
        return "PASS: no tip contamination risk found."
    lines = [f"FAIL: {len(violations)} tip contamination risk(s) found:"]
    for v in violations:
        lines.append(f"  [{v.severity.upper()}] {v.code}: {v.message}")
        if v.suggested_fix:
            lines.append(f"      suggested fix: {v.suggested_fix}")
    return "\n".join(lines)


if __name__ == "__main__":
    import sys
    path = sys.argv[1] if len(sys.argv) > 1 else None
    if not path:
        print("Usage: python3 tip_contamination.py demo/some_protocol.py")
        sys.exit(1)
    violations, error = check_tip_contamination(path)
    if error:
        print(f"Execution stopped: {error}")
    print(format_tip_report(violations))
