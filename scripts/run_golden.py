"""Run the golden questions against an already-running agent service.

Use this to check any deployment path with the same questions, e.g. MAVROS (milestone 7) or the
onboard profile (milestone 9): replay the tlog into the link with scripts/tlog_to_udp.py, point
the vehicle service at it with the profile under test, start the agent, then:

    python scripts/run_golden.py --agent-url http://127.0.0.1:8701
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tests"))

from golden import ask, check, load_questions  # noqa: E402


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--agent-url", default="http://127.0.0.1:8701")
    p.add_argument("--only", nargs="*", help="question ids")
    args = p.parse_args()
    failures = 0
    for q in load_questions():
        if args.only and q["id"] not in args.only:
            continue
        result = ask(args.agent_url, q["question"])
        problems = check(q, result)
        status = "PASS" if not problems else "FAIL"
        failures += bool(problems)
        print(f"[{status}] {q['id']}: tools={result['tools']}")
        for prob in problems:
            print(f"    - {prob}")
        if problems:
            print("    answer:", result["answer"].replace("\n", "\n            "))
    print(f"{failures} failed")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
