"""Permissive, evidence-bearing action graph policy.

Known observation-sensitive effects are coordination nodes. Unknown commands
remain unspecified and execute in their original order. A chain certificate
grants extra scheduling freedom; lacking one never deletes an action.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
import hashlib
import json
from typing import Any, Iterable


COORDINATION_HEADS = {"tmux-new-shell-after", "tmux-send-observed"}
OBSERVATION_HEADS = {"tmux-windows"}


def command_parts(command: Any) -> tuple[str, list[str]]:
    if not isinstance(command, (list, tuple)) or not command:
        return "", []
    return str(command[0]), [str(value) for value in command[1:]]


@dataclass(frozen=True)
class ActionNode:
    node_id: str
    index: int
    kind: str
    depends_on_stimulus: bool
    observation_receipt: str | None
    command: str


def classify(command: Any, index: int = 0) -> ActionNode:
    head, arguments = command_parts(command)
    rendered = json.dumps(command, ensure_ascii=False, separators=(",", ":"))
    node_id = hashlib.sha256(
        (str(index) + "\0" + rendered).encode("utf-8", "replace")
    ).hexdigest()[:16]
    if head in COORDINATION_HEADS:
        kind = "coordination"
        receipt = arguments[0] if arguments else None
    elif head in OBSERVATION_HEADS:
        kind = "observation"
        receipt = None
    else:
        kind = "unspecified"
        receipt = None
    return ActionNode(
        node_id=node_id,
        index=int(index),
        kind=kind,
        depends_on_stimulus=(kind != "observation"),
        observation_receipt=receipt,
        command=rendered,
    )


def graph(commands: Iterable[Any]) -> tuple[ActionNode, ...]:
    return tuple(
        classify(command, index) for index, command in enumerate(commands)
    )


def coordination_admitted(node: ActionNode,
                          available_receipts: Iterable[str]) -> bool:
    if node.kind != "coordination":
        return True
    return bool(node.observation_receipt) and (
        node.observation_receipt in set(str(item) for item in available_receipts)
    )


def certified_chain(left: ActionNode, right: ActionNode,
                    receipt_targets: dict[str, str]) -> bool:
    """Certify the concrete commuting case currently known by the broker.

    Sends to two different exact panes have disjoint targets. This grants
    batching freedom without claiming that arbitrary shell effects commute.
    """

    if left.kind != "coordination" or right.kind != "coordination":
        return False
    left_head, _ = command_parts(json.loads(left.command))
    right_head, _ = command_parts(json.loads(right.command))
    if left_head != "tmux-send-observed" or right_head != left_head:
        return False
    left_target = receipt_targets.get(str(left.observation_receipt))
    right_target = receipt_targets.get(str(right.observation_receipt))
    return bool(left_target and right_target and left_target != right_target)


def metadata(command: Any) -> dict:
    return asdict(classify(command))


def partition_after_stimulus(commands: Iterable[Any]) -> list[list[Any]]:
    """Keep only broker-known stimulus-independent observations runnable.

    The first list may continue; the second is withheld for reconsideration.
    A model cannot grant itself independence by naming a kind.
    """

    independent = []
    dependent = []
    for command in commands:
        node = classify(command)
        (dependent if node.depends_on_stimulus else independent).append(command)
    return [independent, dependent]
