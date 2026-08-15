"""
Deterministic reconciliation checker.

Takes the structured step list produced by the extractor node and checks it
against real labware capacities and loading order. No LLM is involved here on
purpose — this is the node that catches what the simulator silently accepts
(e.g. overflowing a well across several transfer sub-steps).

Step schema (what the extractor should produce):
{
    "action": "transfer" | "mix" | "wait",
    "volume_ul": float,        # required for transfer
    "source": "labware_id:well",
    "dest": "labware_id:well",
    "reagent": "name",         # optional, used for load-order checks
}

Labware schema:
{
    "labware_id": {
        "type": "plate" | "reservoir" | "tiprack",
        "wells": {"A1": 360, "A2": 360, ...}   # well -> max_volume_ul
    }
}
"""

from dataclasses import dataclass, field


@dataclass
class Violation:
    step_index: int
    severity: str  # "error" | "warning"
    code: str
    message: str
    suggested_fix: str = ""  # added in response to reviewer feedback --
    # a flag alone forces the reader to diagnose it themselves; a concrete
    # next step is what actually lets a scientist act on the warning


def _well_key(labware_ref: str) -> str:
    return labware_ref


def check_protocol(steps: list[dict], labware: dict) -> list[Violation]:
    violations: list[Violation] = []
    well_totals: dict[str, float] = {}
    loaded_reagents: set[str] = set()

    def capacity_of(ref: str):
        if ":" not in ref:
            return None
        labware_id, well = ref.split(":", 1)
        return labware.get(labware_id, {}).get("wells", {}).get(well)

    for i, step in enumerate(steps):
        action = step.get("action")

        if action == "transfer":
            volume = step.get("volume_ul")
            dest = step.get("dest")
            source = step.get("source")

            # volume and dest are the two fields we can't check anything
            # without. source is different: a null source usually means an
            # off-deck reagent (a stock bottle poured in by hand, never
            # placed on the robot's deck) -- that's a legitimate protocol
            # pattern, not an extraction failure, so it gets a warning and
            # the check continues rather than aborting the whole step.
            if volume is None or dest is None:
                violations.append(Violation(
                    i, "error", "MISSING_FIELD",
                    f"Step {i}: transfer missing volume_ul or dest"
                ))
                continue
            if source is None:
                violations.append(Violation(
                    i, "warning", "UNTRACKED_SOURCE",
                    f"Step {i}: no source labware given for this transfer into "
                    f"{dest} -- likely an off-deck reagent added by hand; "
                    f"destination capacity is still checked below"
                ))

            # cumulative overflow check -- this is the one the simulator misses
            well_totals[dest] = well_totals.get(dest, 0) + volume
            cap = capacity_of(dest)
            if cap is not None and well_totals[dest] > cap:
                overflow_amt = well_totals[dest] - cap
                violations.append(Violation(
                    i, "error", "WELL_OVERFLOW",
                    f"Step {i}: {dest} now holds {well_totals[dest]:.1f} uL "
                    f"cumulative, exceeds {cap:.1f} uL capacity",
                    suggested_fix=(
                        f"Reduce this transfer by at least {overflow_amt:.1f} uL, "
                        f"split the {volume:.1f} uL across two wells, or move this "
                        f"reagent to a larger container before step {i}."
                    ),
                ))

            # negative / zero volume sanity check
            if volume <= 0:
                violations.append(Violation(
                    i, "error", "INVALID_VOLUME",
                    f"Step {i}: volume {volume} uL is not positive"
                ))

            # source depletion check (reservoir/tube running dry) -- only
            # meaningful when we actually have a source to track
            if source is not None:
                src_cap = capacity_of(source)
                well_totals.setdefault(source, 0)
                # negative accumulation = amount drawn out
                well_totals[source] -= volume
                # only flag if we know the starting fill (not tracked yet -> skip
                # unless it goes further negative than the container could ever hold)
                if src_cap is not None and well_totals[source] < -src_cap:
                    violations.append(Violation(
                        i, "error", "SOURCE_DEPLETED",
                        f"Step {i}: {source} drawn beyond its capacity "
                        f"({src_cap:.1f} uL) across the protocol",
                        suggested_fix=(
                            f"Load more of this reagent into {source} before the "
                            f"protocol runs, or reduce the volume drawn in earlier steps."
                        ),
                    ))

            # NOTE: reagent tracking for real ordering checks now lives in
            # check_ordering() below -- this branch used to collect reagent
            # names into a set and never actually check anything against it,
            # which claimed a validation that wasn't real. Removed rather
            # than left in place looking functional.

        elif action == "wait":
            duration = step.get("duration_s")
            if duration is None or duration < 0:
                violations.append(Violation(
                    i, "warning", "MISSING_DURATION",
                    f"Step {i}: wait step has no valid duration_s"
                ))

        elif action == "discard":
            # Liquid actually leaving a well -- without this, a well that
            # gets filled and emptied five times (a normal wash/bind cycle)
            # looks like it fills five times with nothing ever removed,
            # which produces a false overflow that has nothing to do with
            # a real mistake in the protocol.
            source = step.get("source")
            volume = step.get("volume_ul")
            if source is None:
                violations.append(Violation(
                    i, "warning", "DISCARD_MISSING_SOURCE",
                    f"Step {i}: discard step has no source well to empty"
                ))
                continue
            if volume is None:
                # "discard the supernatant" with no stated amount means the
                # well is emptied completely, not that a specific measured
                # volume is removed -- reset rather than guess a number.
                well_totals[source] = 0.0
            else:
                well_totals[source] = max(0.0, well_totals.get(source, 0.0) - volume)

    return violations


def check_ordering(steps: list[dict]) -> list[Violation]:
    """
    Catches steps happening in an impossible physical order: drawing from a
    well before anything was put in it, or incubating/measuring/mixing a
    well before it was ever filled.

    Design choice: this only checks wells that THIS PROTOCOL fills at some
    point (appear as a transfer's dest somewhere in the step list). A well
    that is a source but never a dest anywhere is treated as a legitimate
    pre-existing/off-deck reagent, not an ordering bug -- we have no basis
    to claim it should have been filled by this protocol. That scoping is
    what keeps this check from false-positiving on every normal stock
    reagent reference.
    """
    violations: list[Violation] = []
    filled_wells: set[str] = set()

    ever_filled: set[str] = set()
    for step in steps:
        if step.get("action") == "transfer" and step.get("dest"):
            ever_filled.add(step["dest"])

    for i, step in enumerate(steps):
        action = step.get("action")

        if action == "transfer":
            source = step.get("source")
            dest = step.get("dest")
            if source and source in ever_filled and source not in filled_wells:
                violations.append(Violation(
                    i, "error", "USED_BEFORE_FILLED",
                    f"Step {i}: draws from {source}, but this protocol doesn't "
                    f"fill {source} until a later step",
                    suggested_fix=(
                        f"Move the step that fills {source} to before step {i}, "
                        f"or confirm {source} is actually pre-filled off-deck "
                        f"and doesn't need a fill step at all."
                    ),
                ))
            if dest:
                filled_wells.add(dest)

        elif action in ("incubate", "measure", "mix"):
            target = step.get("dest")
            if target and target in ever_filled and target not in filled_wells:
                violations.append(Violation(
                    i, "error", "ACTION_BEFORE_FILL",
                    f"Step {i}: {action} references {target} before any "
                    f"transfer has filled it",
                    suggested_fix=(
                        f"Move this {action} step to after the transfer that "
                        f"fills {target}."
                    ),
                ))

    return violations



CHECKS_AGAINST = (
    "VeriLab's checker validates transfer volumes against real Opentrons "
    "container capacities (pulled from the actual labware catalog, not "
    "estimated), source depletion across a full run, and physical ordering "
    "-- a well this protocol fills can't be drawn from, incubated, measured, "
    "or mixed before that fill actually happens. "
    "It does not currently check chemical compatibility, safety rules, or "
    "prior experiment history -- those are named as future check categories, "
    "not claimed as done."
)


def format_report(violations: list[Violation]) -> str:
    if not violations:
        return "PASS: no violations found."
    lines = ["FAIL: {} violation(s) found:".format(len(violations))]
    for v in violations:
        lines.append(f"  [{v.severity.upper()}] step {v.step_index} ({v.code}): {v.message}")
        if v.suggested_fix:
            lines.append(f"      suggested fix: {v.suggested_fix}")
    return "\n".join(lines)


def resource_summary(steps: list[dict]) -> str:
    """
    Added in response to reviewer feedback (asked twice, independently):
    'I know the exact amount of stuff I'll be needing' / 'being able to pull
    the amount of reagents or tips needed would be helpful.' Sums total
    volume per reagent and counts transfers needing a fresh tip, so a
    scientist can prep the bench before running anything.
    """
    from collections import defaultdict
    reagent_totals: dict[str, float] = defaultdict(float)
    tip_count = 0

    for step in steps:
        if step.get("action") != "transfer":
            continue
        volume = step.get("volume_ul")
        reagent = step.get("reagent") or "(unspecified reagent)"
        if volume:
            reagent_totals[reagent] += volume
        if step.get("dest") and step.get("volume_ul"):
            tip_count += 1

    lines = ["Resource summary:"]
    for reagent, total in sorted(reagent_totals.items(), key=lambda x: -x[1]):
        lines.append(f"  {reagent}: {total:.1f} uL total")
    lines.append(f"  Tips needed: {tip_count} (one per transfer, default Opentrons behavior)")
    return "\n".join(lines)


if __name__ == "__main__":
    # smoke test using the exact overflow case we already confirmed the
    # opentrons simulator does NOT catch
    labware = {
        "plate": {"type": "plate", "wells": {f"A{i}": 360 for i in range(1, 13)}},
        "reservoir": {"type": "reservoir", "wells": {"A1": 15000}},
    }
    steps = [
        {"action": "transfer", "volume_ul": 200, "source": "reservoir:A1", "dest": "plate:A1", "reagent": "buffer"},
        {"action": "transfer", "volume_ul": 200, "source": "reservoir:A1", "dest": "plate:A1", "reagent": "buffer"},
        {"action": "transfer", "volume_ul": 100, "source": "reservoir:A1", "dest": "plate:A1", "reagent": "buffer"},
    ]
    print(format_report(check_protocol(steps, labware)))
    print()
    print(resource_summary(steps))
    print()
    print(CHECKS_AGAINST)
