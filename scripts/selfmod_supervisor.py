#!/usr/bin/env python3
"""Verify and atomically promote a PettaClaw self-modification proposal.

Run this outside the agent sandbox with a writable protected-root mount.  The
agent runtime should see that same root read-only and must not possess this
process's filesystem authority.
"""

import argparse
import json
import pathlib
import sys


ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import selfmod  # noqa: E402


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=("verify", "promote"))
    parser.add_argument("proposal_id")
    parser.add_argument("--root", required=True)
    parser.add_argument("--store", required=True)
    parser.add_argument("--semantic", action="store_true")
    args = parser.parse_args(argv)
    try:
        settings = selfmod.Settings.from_env(root=args.root, store=args.store)
        verified = selfmod.verify_proposal(
            args.proposal_id, settings=settings, semantic=args.semantic
        )
        if args.action == "verify":
            result = {
                "state": "verified",
                "proposal_id": verified.proposal_id,
                "target": verified.manifest["target"],
                "candidate_sha256": verified.manifest["candidate_sha256"],
            }
        else:
            result = selfmod.atomic_promote(verified, settings=settings)
        print(json.dumps(result, sort_keys=True))
        return 0
    except selfmod.SelfModError as exc:
        print(json.dumps({"state": "blocked", "reason": str(exc)}))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
