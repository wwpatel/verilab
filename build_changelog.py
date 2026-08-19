"""
Precomputes the marketing page's "Recently verified" changelog strip.

This project doesn't keep a separate changelog file; its real, dated record
of work is its git history. This script reads that history directly (`git
log`) and writes the real commit dates and messages out as static data, the
same "actually run it, store the real output" approach as
build_evidence.py and build_hero_capture.py. Nothing here is invented;
every entry is a real commit that really happened on this real date.

Re-run whenever new commits should appear in the strip:

    python3 build_changelog.py
"""

import json
import subprocess
from pathlib import Path

OUT_PATH = Path(__file__).parent / "site" / "data" / "changelog.json"

# Commits that are noise for a visitor-facing changelog (repeated fixes to
# the same mistake, or purely internal housekeeping) are left out; this is
# curation of which real commits to show, not invention of new ones. Every
# entry that remains is a real commit's real date and real subject line,
# read straight from git log below.
EXCLUDE_SUBSTRINGS = [
    "Stop tracking __pycache__",
]

MAX_ENTRIES = 10


def main():
    raw = subprocess.run(
        ["git", "log", "--format=%ad|%s", "--date=format:%Y-%m-%d"],
        capture_output=True, text=True, check=True,
    ).stdout.strip()

    entries = []
    for line in raw.splitlines():
        date, subject = line.split("|", 1)
        if any(s in subject for s in EXCLUDE_SUBSTRINGS):
            continue
        entries.append({"date": date, "subject": subject})

    entries = entries[:MAX_ENTRIES]

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(json.dumps({"entries": entries}, indent=2) + "\n")
    print(f"Wrote {len(entries)} entries to {OUT_PATH}")


if __name__ == "__main__":
    main()
