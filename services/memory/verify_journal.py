#!/usr/bin/env python3
"""Verify a memory journal without reading or changing its derived index."""

import argparse
import json

from .journal import verify_journal


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("journal")
    args = parser.parse_args(argv)
    result = verify_journal(args.journal)
    print(json.dumps(result.as_dict(), sort_keys=True))
    return 0 if result.valid else 1


if __name__ == "__main__":
    raise SystemExit(main())
