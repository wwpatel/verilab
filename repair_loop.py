"""
Simulate-and-repair loop.

Takes generated Opentrons code, runs it through the real simulator. If it
fails, sends the actual code + actual error message back to the LLM and
asks for a corrected version. Retries up to MAX_RETRIES times before
giving up and escalating to a human.

This is the piece that closes the loop: extraction and generation are
upstream guesses (probabilistic), but THIS step is grounded in a real,
external, non-negotiable check -- the simulator either accepts the code
or it doesn't. That's what makes retrying meaningful instead of just
asking the model to try again blindly.
"""

import os
import subprocess
import sys

from anthropic import Anthropic

client = Anthropic(api_key=os.environ.get("ANTHROPIC_API_KEY"))

MAX_RETRIES = 3

REPAIR_SYSTEM_PROMPT = """You are given an Opentrons Flex protocol (Python, API 2.20) that
failed to simulate, along with the exact simulator error.

Fix ONLY what the error describes. Do not rewrite unrelated parts of the
protocol, rename variables, or change labware/pipette choices unless the
error specifically requires it. Output ONLY the corrected Python file, no
markdown fences, no commentary, no explanation before or after the code.
"""


def simulate(path: str) -> tuple[bool, str]:
    """Runs opentrons_simulate on a file. Returns (success, output)."""
    result = subprocess.run(
        ["opentrons_simulate", path],
        capture_output=True,
        text=True,
        timeout=60,
    )
    success = result.returncode == 0
    # simulator writes calibration warnings to stderr even on success --
    # only stdout + a nonzero exit code indicate an actual failure
    output = result.stdout if success else (result.stderr + result.stdout)
    return success, output


def repair_code(code: str, error_output: str, model: str = "claude-sonnet-4-6") -> str:
    prompt = (
        f"PROTOCOL CODE:\n```python\n{code}\n```\n\n"
        f"SIMULATOR ERROR:\n```\n{error_output}\n```\n\n"
        f"Fix the code so it simulates successfully."
    )
    response = client.messages.create(
        model=model,
        max_tokens=8000,
        system=REPAIR_SYSTEM_PROMPT,
        messages=[{"role": "user", "content": prompt}],
    )
    raw = response.content[0].text.strip()
    if raw.startswith("```"):
        raw = raw.strip("`")
        if raw.startswith("python"):
            raw = raw[6:]
    return raw.strip()


def simulate_and_repair(path: str) -> dict:
    """
    Returns a report dict: {"success": bool, "attempts": int, "log": [...]}
    Overwrites the file in place with each repaired version, so the final
    state on disk is always the last attempt (successful or not).
    """
    log = []
    for attempt in range(1, MAX_RETRIES + 2):  # initial try + MAX_RETRIES repairs
        success, output = simulate(path)
        log.append({"attempt": attempt, "success": success, "output": output[:2000]})

        if success:
            return {"success": True, "attempts": attempt, "log": log}

        if attempt > MAX_RETRIES:
            break

        with open(path) as f:
            code = f.read()
        fixed_code = repair_code(code, output)
        with open(path, "w") as f:
            f.write(fixed_code)

    return {"success": False, "attempts": len(log), "log": log}


if __name__ == "__main__":
    path = sys.argv[1] if len(sys.argv) > 1 else None
    if not path:
        print("Usage: python3 repair_loop.py test_protocols/protocol_01_generated.py")
        sys.exit(1)

    report = simulate_and_repair(path)

    print(f"\n{'='*60}")
    for entry in report["log"]:
        status = "PASS" if entry["success"] else "FAIL"
        print(f"Attempt {entry['attempt']}: {status}")
        if not entry["success"]:
            # print just the most relevant error line, not the full traceback
            lines = [l for l in entry["output"].splitlines() if l.strip()]
            for l in lines[-3:]:
                print(f"    {l}")

    print(f"\nFinal result: {'SUCCESS' if report['success'] else 'FAILED'} "
          f"after {report['attempts']} attempt(s)")
    print(f"{'='*60}\n")
