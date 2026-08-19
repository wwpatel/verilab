"""
Precomputes the public marketing page's feature-section mockups.

Each of the four feature sections (overflow, ordering, tip contamination,
verified code generation) shows one real pipeline result. This script runs
the actual pipeline (app.py's real collect_result, the same function
/api/verify calls) against the same fixtures app.py's own EXAMPLES dict
already uses, once, offline, and stores the full result as static data.

The marketing page then renders this real captured output; it never makes a
live API call for an anonymous visitor. This is the same "run for real,
store the real output" approach as build_evidence.py and
build_hero_capture.py, not hand-typed or invented data.

Re-run whenever the underlying demo/ or test_protocols/ fixtures change, or
whenever checker.py/generator.py/tip_contamination.py output format changes:

    python3 build_marketing_examples.py
"""

import json
from datetime import datetime, timezone
from pathlib import Path

from app import EXAMPLES, collect_result, BASE_DIR

OUT_PATH = Path(__file__).parent / "site" / "data" / "marketing_examples.json"


def main():
    out = {"generated_at": datetime.now(timezone.utc).isoformat(), "examples": {}}
    for ex_id, meta in EXAMPLES.items():
        path = BASE_DIR / meta["path"]
        content = path.read_text()
        result = collect_result(content, meta["protocol_name"], meta["kind"])
        out["examples"][ex_id] = {
            "label": meta["label"],
            "protocol_name": meta["protocol_name"],
            "source_path": meta["path"],
            "source_text": content,
            "result": result,
        }
        print(f"{ex_id}: {result['overall_status']}, {result['checks']['violation_count']} violation(s)")

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(json.dumps(out, indent=2) + "\n")
    print(f"Wrote {OUT_PATH}")


if __name__ == "__main__":
    main()
