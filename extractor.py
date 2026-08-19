"""
Extractor node.

Takes raw protocol text (as copied from a paper or protocols.io) and returns
a structured JSON step list matching checker.py's schema.

This is deliberately a narrow, single-purpose call: extraction only, no code
generation, no judgment calls about feasibility. That's handled downstream.
"""

import json
import os
from anthropic import Anthropic

client = Anthropic(api_key=os.environ.get("ANTHROPIC_API_KEY"))

EXTRACTOR_SYSTEM_PROMPT = """You convert wet-lab protocol text into a structured JSON step list for liquid-handling automation.

Output ONLY a JSON object with this exact shape, no markdown fences, no commentary:

{
  "labware": {
    "<labware_id>": {
      "type": "plate" | "reservoir" | "tube_rack",
      "description": "<what it physically is>",
    }
  },
  "reagents": ["<reagent name>", ...],
  "steps": [
    {
      "action": "transfer" | "mix" | "wait" | "incubate" | "measure" | "transfer_matched" | "external_instrument" | "discard",
      "volume_ul": <number, required for transfer/transfer_matched>,
      "source": "<labware_id>:<well>",
      "dest": "<labware_id>:<well>",
      "dest_wells": ["<well>", "<well>", ...],
      "source_labware": "<labware_id>, only for transfer_matched>",
      "dest_labware": "<labware_id>, only for transfer_matched>",
      "matched_wells": ["<well>", "<well>", ...],
      "reagent": "<reagent name or null>",
      "duration_s": <number, required for wait/incubate>,
      "interval_s": <number, only for repeating "measure" actions>,
      "temperature_c": <number or null>,
      "instrument_name": "<name of the external device/robot, only for external_instrument>",
      "instrument_action": "<one sentence describing what the external device does, only for external_instrument>",
      "notes": "<one short sentence, only if something is ambiguous or assumed -- omit field entirely otherwise>"
    }
  ]
}

Rules:
- If the protocol does not specify an exact volume, well, or duration, do NOT invent a plausible-sounding number. Instead set that field to null and add a one-sentence note explaining what was missing.
- CRITICAL -- do not write one step object per well. If the SAME action (same volume, same source, same reagent) applies to many wells (e.g. "5 uL per well of a 96-well plate"), output exactly ONE step object and list every target well in "dest_wells" (e.g. ["A1","A2",...,"H12"]). Leave "dest" null when using "dest_wells". This keeps output compact -- a 96-well fill is one step with a 96-item array, never 96 separate step objects.
- CRITICAL -- distinguish two DIFFERENT patterns and never conflate them:
  (a) ONE source feeding MANY destination wells (e.g. "aliquot 5 uL per well from the stock") -> use "transfer" with "dest_wells", a single "source".
  (b) EACH destination well pulling from the CORRESPONDING well of a different labware (e.g. "add 2 uL of each sample to the corresponding well of the new plate") -> this is NOT the same source repeated. Use action "transfer_matched" with "source_labware", "dest_labware", and one "matched_wells" list (e.g. ["A1","A2",...,"H12"]) -- well A1 of source_labware maps to well A1 of dest_labware, and so on, one distinct source per destination. NEVER represent a matched well-to-well transfer as "transfer" with a single repeated "source" -- that silently claims every well pulled from the same physical spot, which is wrong.
- Only use a separate step per well when the action genuinely differs between wells (different volume, different reagent, different source) in a way "transfer_matched" doesn't already cover.
- CRITICAL -- if a step is performed by hardware OTHER than the liquid-handling robot itself (a plate reader, thermocycler, epMotion, sequencer, or any other named external instrument), represent it as exactly ONE "external_instrument" step, regardless of how many plates, wells, or samples it touches. Set "instrument_name" and a one-sentence "instrument_action". NEVER decompose an external instrument's internal operation into transfer/dest_wells/matched_wells steps -- you do not control that hardware and have no visibility into how it actually moves liquid internally, so representing it well-by-well is fabricating detail the protocol never gave you. A step transferring reagent into three 384-well plates via an automated platform is ONE step, not 1152.
- CRITICAL -- when the protocol text uses a specific well-format keyword for a labware item ("deepwell", "deep well", "PCR plate", "384-well", "flat-bottom", "V-bottom", "conical"), that exact keyword MUST appear in that labware's "description" field, verbatim. Do not paraphrase or summarize it away. These keywords are not decorative -- a deterministic step downstream matches them against a real catalog to find the labware's true volume capacity, and a deepwell plate holds roughly 5x what a standard flat plate holds. Writing "96-well elution plate" when the source text says "96-deepwell plate" silently produces a five-fold-wrong capacity number with no error raised anywhere.
- NEVER expand a periodic instrument measurement (e.g. "read OD600 every 10 minutes for 48 hours", "cycle 40 times") into one step per timepoint or cycle. Represent it as a SINGLE "measure" or "incubate" step using "duration_s" for the total run time and "interval_s" for the repeat interval. A 48-hour run at 10-minute intervals is one step, not 288.
- CRITICAL -- when the protocol removes liquid from a well without moving it to another tracked labware ("aspirate and discard the supernatant," "discard the flow-through," "remove and discard the wash buffer"), emit action "discard" with "source" set to the well being emptied and "dest_wells" (or "source_wells" for a plate-wide discard) mirroring how that same well range was filled earlier. Set "volume_ul" only if the text states a specific amount; if the text just says "discard the supernatant" with no volume given, leave "volume_ul" null -- that phrase means the well is being emptied completely, not that a specific measured amount is removed, and a null volume signals "empty this well" rather than a partial, uncertain draw. This is required for any wash, bind, or wash-and-discard cycle -- without it, a protocol that fills and empties the same well five times looks like it fills the well five times with nothing ever leaving, which is not what the protocol says.
- Do not skip real physical actions -- every transfer, wash, and incubation the text describes should appear as exactly one step (or one step with dest_wells / matched_wells, per the rules above).
- Do not resolve unit ambiguity yourself (e.g. "add buffer" with no unit) -- flag it in notes rather than guessing mL vs uL.
- Keep every "notes" value to one short sentence. Never quote the source text at length. Omit the "notes" field entirely for steps that need no comment.
- CRITICAL -- every labware ID used in "source"/"dest"/"source_labware"/"dest_labware" must be one of the exact keys you defined in the top-level "labware" object. Before finishing, check every step against your own "labware" keys and fix any mismatch. Do not invent a shorthand like "plate" if you defined the key as "cytoone_plate".
"""


def expand_dest_wells(steps: list[dict]) -> list[dict]:
    """
    Pure-Python fan-out: turns any step with a 'dest_wells' list into N
    individual per-well step dicts with 'dest' set, and any step with
    'matched_wells' into N individual per-well-pair transfer steps
    (source_labware:well -> dest_labware:well, same well name on each
    side). This is mechanical expansion -- deliberately done in code, not
    by the LLM, so the model never has to repeat itself well-by-well and
    never has to fake a shared "source" for what is actually a per-well
    mapping.
    """
    expanded = []
    for step in steps:
        matched = step.get("matched_wells")
        wells = step.get("dest_wells")

        if matched and step.get("action") == "transfer_matched":
            src_labware = step["source_labware"]
            dst_labware = step["dest_labware"]
            for well in matched:
                new_step = {
                    k: v for k, v in step.items()
                    if k not in ("matched_wells", "source_labware", "dest_labware", "action")
                }
                new_step["action"] = "transfer"
                new_step["source"] = f"{src_labware}:{well}"
                new_step["dest"] = f"{dst_labware}:{well}"
                expanded.append(new_step)
        elif wells:
            labware_id = step["dest"].split(":")[0] if step.get("dest") else step.get("labware_id", "plate")
            for well in wells:
                new_step = {k: v for k, v in step.items() if k != "dest_wells"}
                new_step["dest"] = f"{labware_id}:{well}" if ":" not in well else well
                expanded.append(new_step)
        elif step.get("source_wells") and step.get("action") == "discard":
            # plate-wide discard, e.g. "aspirate and discard the supernatant
            # from every well" -- mirrors dest_wells expansion above. This
            # field was added to the prompt without ever being wired up
            # here, which is exactly why real discard steps were showing up
            # with no source: the instruction existed, the code didn't.
            source_wells = step["source_wells"]
            labware_id = step.get("source", "").split(":")[0] if step.get("source") else step.get("labware_id", "plate")
            for well in source_wells:
                new_step = {k: v for k, v in step.items() if k != "source_wells"}
                new_step["source"] = f"{labware_id}:{well}" if ":" not in well else well
                expanded.append(new_step)
        else:
            expanded.append(step)
    return expanded


def extract_steps(protocol_text: str, model: str = "claude-sonnet-4-6", api_key: str | None = None) -> dict:
    # api_key is set for the authenticated product's dashboard, where each
    # signed-in user's own stored key powers their own extraction calls; a
    # fresh per-call client is used instead of the module-level one so one
    # request never touches another user's or the server's own key. Falls
    # back to the module-level client (server's own key) when omitted, which
    # is what the local console and public site still use.
    active_client = Anthropic(api_key=api_key) if api_key else client
    response = active_client.messages.create(
        model=model,
        max_tokens=12000,
        temperature=0,  # near-deterministic sampling -- extraction should be
        # the same every time for the same input; defaulting to temperature
        # 1.0 was letting two runs of the identical protocol produce two
        # different labware layouts entirely, which is its own reliability
        # problem independent of the disambiguation logic
        system=EXTRACTOR_SYSTEM_PROMPT,
        messages=[
            {"role": "user", "content": protocol_text},
        ],
    )
    raw = response.content[0].text.strip()
    # strip markdown fences if present
    if raw.startswith("```"):
        raw = raw.strip("`")
        if raw.startswith("json"):
            raw = raw[4:]
    raw = raw.strip()
    # tolerate any stray preamble/trailing text by slicing to the outermost braces
    start = raw.find("{")
    end = raw.rfind("}")
    if start != -1 and end != -1:
        raw = raw[start:end + 1]

    stop_reason = response.stop_reason
    try:
        return json.loads(raw)
    except json.JSONDecodeError as e:
        debug_path = "extractor_last_failure.txt"
        with open(debug_path, "w") as f:
            f.write(raw)
        msg = (
            f"Failed to parse model output as JSON: {e}\n"
            f"stop_reason was '{stop_reason}'"
        )
        if stop_reason == "max_tokens":
            msg += " -- the response was cut off, raise max_tokens further or shorten the input."
        msg += f"\nFull raw output saved to {debug_path} for inspection."
        raise RuntimeError(msg) from e


import re

_ORDINAL_WORDS = {
    1: "1st", 2: "2nd", 3: "3rd", 4: "4th", 5: "5th", 6: "6th",
    7: "7th", 8: "8th", 9: "9th", 10: "10th", 11: "11th", 12: "12th",
}
_DESCRIPTION_NOISE_WORDS = {
    "buffer", "solution", "reagent", "the", "a", "of", "and", "for",
    "with", "plate", "well", "wells", "slot", "nest", "deepwell", "ml",
}


def _core_keywords(text: str) -> set[str]:
    """Letters-only tokens, generic/noise words stripped. Used to compare a
    reagent name against a labware description on shared meaningful words
    (e.g. 'equilibration', 'elution') without matching on filler."""
    words = re.findall(r"[a-z]+", text.lower())
    return {w for w in words if w not in _DESCRIPTION_NOISE_WORDS and len(w) > 2}


def _reagent_ordinal(text: str) -> str | None:
    """Extracts a trailing number from a reagent name ('Wash buffer 2' -> 2)
    and returns its ORDINAL WORD form ('2nd'). Deliberately does not match
    on the bare digit -- a description like '96-well 2 mL deepwell plate'
    contains the digit '2' for a completely unrelated reason (the well
    volume), so bare-digit matching produces false positives. Only the
    written-out ordinal is specific enough to trust."""
    match = re.search(r"\b(\d{1,2})\b", text)
    if not match:
        return None
    return _ORDINAL_WORDS.get(int(match.group(1)))


def normalize_labware_refs(result: dict) -> tuple[dict, list[str]]:
    """
    The model doesn't reliably keep its own labware IDs self-consistent --
    it tends to fall back to a generic word ("plate", "reservoir", "tube")
    even when the labware dict defines a more specific key like
    "cytoone_plate". Rather than keep tightening the prompt, fix this
    deterministically: if a step references an undefined ID, and exactly
    one declared labware entry has a matching "type", remap to that ID.

    Returns (result, notes) where notes describes every remap made, so
    the correction is visible rather than silent.
    """
    labware = result.get("labware", {})
    known_ids = set(labware.keys())
    # generic word -> the "type" value it should match
    generic_type_hints = {
        "plate": "plate",
        "reservoir": "reservoir",
        "tube": "tube_rack",
        "tube_rack": "tube_rack",
    }
    notes = []

    # Pre-scan: which labware IDs does the model explicitly name as a SOURCE
    # somewhere? A plate that is explicitly drawn FROM elsewhere is almost
    # never the unnamed plate being dispensed INTO -- that asymmetry is what
    # lets us break a type tie without asking the model to be self-consistent.
    explicit_sources = set()
    explicit_dests = set()
    for step in result.get("steps", []):
        for field, bucket in (("source", explicit_sources), ("dest", explicit_dests)):
            ref = step.get(field)
            if ref and ":" in ref:
                lw = ref.split(":", 1)[0]
                if lw in known_ids:
                    bucket.add(lw)
        if step.get("source_labware") in known_ids:
            explicit_sources.add(step["source_labware"])
        if step.get("dest_labware") in known_ids:
            explicit_dests.add(step["dest_labware"])

    # Pre-scan 2: build a reagent -> labware affinity map from steps that
    # ALREADY have a valid, unambiguous reference. On a large protocol with
    # many same-type plates, type + role narrowing alone can still leave
    # 3+ candidates -- but the protocol usually contains plenty of steps
    # that already got it right, and those are real ground truth: if
    # "Enzymatic Fragmentation Master Mix" was correctly sent to
    # sample_plate somewhere, any other step moving that same reagent is
    # almost certainly going to the same physical plate.
    reagent_affinity: dict[str, set[str]] = {}
    for step in result.get("steps", []):
        reagent = (step.get("reagent") or "").strip().lower()
        if not reagent:
            continue
        for field in ("source", "dest"):
            ref = step.get(field)
            if ref and ":" in ref:
                lw = ref.split(":", 1)[0]
                if lw in known_ids:
                    reagent_affinity.setdefault(reagent, set()).add(lw)

    for step in result.get("steps", []):
        for field in ("source", "dest"):
            ref = step.get(field)
            if not ref or ":" not in ref:
                continue
            labware_id, well = ref.split(":", 1)
            if labware_id in known_ids:
                continue

            target_type = generic_type_hints.get(labware_id)
            candidates = [
                lw_id for lw_id, meta in labware.items()
                if meta.get("type") == target_type
            ] if target_type else []

            reason = f"matched by type '{target_type}'"

            # Tie-break 1: role (never a source / never a dest elsewhere).
            if len(candidates) > 1:
                if field == "dest":
                    narrowed = [c for c in candidates if c not in explicit_sources]
                else:
                    narrowed = [c for c in candidates if c not in explicit_dests]
                if len(narrowed) == 1:
                    candidates = narrowed
                    reason = (
                        f"matched by type '{target_type}' and disambiguated by role "
                        f"(only candidate never used explicitly as "
                        f"{'a source' if field == 'dest' else 'a destination'})"
                    )
                elif len(narrowed) > 1:
                    candidates = narrowed  # still narrow the field for the next tiebreaker

            # Tie-break 2: reagent affinity, using other steps' already-valid
            # references as ground truth. Only fires when it narrows to
            # exactly one candidate that's also still in the role-narrowed set.
            if len(candidates) > 1:
                reagent = (step.get("reagent") or "").strip().lower()
                affinity_ids = reagent_affinity.get(reagent, set())
                narrowed = [c for c in candidates if c in affinity_ids]
                if len(narrowed) == 1:
                    candidates = narrowed
                    reason = (
                        f"disambiguated by reagent affinity (other steps in this "
                        f"protocol send '{reagent}' only to {narrowed[0]})"
                    )
            # Tie-break 3: match the reagent name against each remaining
            # candidate's own description text. This is the only tiebreaker
            # that works when NO step anywhere has a valid reference to learn
            # from (tie-break 2 needs ground truth; this one doesn't, it uses
            # the labware's own declared description instead).
            if len(candidates) > 1:
                reagent_text = step.get("reagent") or ""
                reagent_kw = _core_keywords(reagent_text)
                ordinal = _reagent_ordinal(reagent_text)
                scored = []
                for c in candidates:
                    desc = labware.get(c, {}).get("description", "")
                    desc_kw = _core_keywords(desc)
                    keyword_overlap = bool(reagent_kw & desc_kw)
                    ordinal_ok = (ordinal is None) or (ordinal in desc.lower())
                    if keyword_overlap and ordinal_ok:
                        scored.append(c)
                if len(scored) == 1:
                    candidates = scored
                    reason = (
                        f"disambiguated by matching '{reagent_text}' against "
                        f"{scored[0]}'s own description"
                    )

            if len(candidates) == 1:
                new_ref = f"{candidates[0]}:{well}"
                step[field] = new_ref
                notes.append(f"remapped '{ref}' -> '{new_ref}' ({reason})")
            elif len(candidates) > 1:
                notes.append(
                    f"could not auto-remap '{ref}': multiple labware entries "
                    f"have type '{target_type}' ({candidates}) -- ambiguous "
                    f"even after role analysis"
                )
            else:
                notes.append(
                    f"could not auto-remap '{ref}': no labware entry with type "
                    f"'{target_type}'"
                )

    return result, notes


def validate_labware_ids(result: dict) -> list[str]:
    """Returns a list of warning strings for any step referencing a labware
    ID that wasn't defined in the top-level 'labware' object."""
    known_ids = set(result.get("labware", {}).keys())
    warnings = []
    for i, step in enumerate(result.get("steps", [])):
        for field in ("source", "dest"):
            ref = step.get(field)
            if ref and ":" in ref:
                labware_id = ref.split(":")[0]
                if labware_id not in known_ids:
                    warnings.append(
                        f"step {i}: '{field}' references undefined labware "
                        f"id '{labware_id}' (known ids: {sorted(known_ids)})"
                    )
    return warnings


def summarize_warnings(warnings: list[str]) -> list[str]:
    """Collapse repeated warnings (same missing id, same known ids) into a
    single line with a count, instead of printing one line per step."""
    from collections import Counter
    import re

    pattern = re.compile(r"step \d+: '(\w+)' references undefined labware id '(\w+)' \(known ids: (\[.*\])\)")
    counts = Counter()
    for w in warnings:
        m = pattern.match(w)
        if m:
            field, missing_id, known = m.groups()
            counts[(field, missing_id, known)] += 1
        else:
            counts[(w, "", "")] += 1

    summary = []
    for (field, missing_id, known), count in counts.items():
        if known:
            summary.append(
                f"{count}x steps use undefined labware id '{missing_id}' in '{field}' "
                f"(known ids: {known})"
            )
        else:
            summary.append(f"{count}x: {field}")
    return summary


if __name__ == "__main__":
    import sys
    path = sys.argv[1] if len(sys.argv) > 1 else None
    if not path:
        print("Usage: python3 extractor.py test_protocols/protocol_01.txt")
        sys.exit(1)
    with open(path) as f:
        text = f.read()
    result = extract_steps(text)
    result["steps"] = expand_dest_wells(result["steps"])
    result, remap_notes = normalize_labware_refs(result)
    warnings = validate_labware_ids(result)

    # save full output to a file instead of dumping it to the terminal
    out_path = path.rsplit(".", 1)[0] + "_extracted.json"
    with open(out_path, "w") as f:
        json.dump(result, f, indent=2)

    print(f"Saved {len(result['steps'])} steps to {out_path}")
    if remap_notes:
        print(f"\n{len(remap_notes)} labware ID auto-remap note(s):")
        for n in remap_notes[:10]:
            print(f"  NOTE: {n}")
        if len(remap_notes) > 10:
            print(f"  ...and {len(remap_notes) - 10} more (see notes if needed)")
    if warnings:
        summary = summarize_warnings(warnings)
        print(f"\n{len(warnings)} labware ID warning(s), summarized:")
        for s in summary:
            print(f"  WARNING: {s}")
        print(f"\nFix: open {out_path}, decide which real labware each ambiguous "
              f"reference means, and do a find-and-replace on that id.")
    else:
        print("0 unresolved labware ID warnings.")
