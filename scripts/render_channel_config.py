#!/usr/bin/env python3
"""Render the literal MeTTa channel specialization used by every launcher."""

from __future__ import annotations

import argparse


CHANNEL_KINDS = ("telegram", "irc", "mattermost")


def render(kind: str) -> str:
    if kind not in CHANNEL_KINDS:
        raise ValueError("unsupported channel kind: %s" % kind)
    return (
        ";; Generated from config/local.toml [channel] kind. Do not edit.\n"
        "(= (configureChannel) (configure commchannel %s))\n" % kind
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("kind", choices=CHANNEL_KINDS)
    arguments = parser.parse_args()
    print(render(arguments.kind), end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
