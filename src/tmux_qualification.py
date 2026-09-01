"""Disposable tmux qualification world for agent policies.

This module never addresses the default tmux server.  Callers must supply a
dedicated socket name, and every command is routed through ``tmux -L``.  It is
a qualification harness, not the live agent bridge.

The guarded operation is deliberately stronger than ``tmux_bridge.send``: an
observation contains an exact pane id and a screen fingerprint, and a send is
withheld if either changed.  Raw tmux cannot make screen capture and input one
atomic server operation, so this is a detectable-staleness prototype rather
than a complete concurrent terminal broker.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import os
from pathlib import Path
import re
import subprocess
import time
from typing import Callable


_SOCKET = re.compile(r"^[A-Za-z0-9_.-]+$")


@dataclass(frozen=True)
class PaneObservation:
    target: str
    pane_id: str
    pane_pid: int
    window_id: str
    window_name: str
    current_command: str
    fingerprint: str
    content: str


@dataclass(frozen=True)
class GuardedResult:
    status: str
    detail: str


class IsolatedTmux:
    def __init__(self, socket_name: str):
        if not _SOCKET.fullmatch(socket_name):
            raise ValueError("tmux qualification socket has unsafe characters")
        self.socket_name = socket_name
        self._environment = dict(os.environ)
        self._environment.pop("TMUX", None)

    def run(self, *arguments: str, check: bool = True) -> subprocess.CompletedProcess:
        result = subprocess.run(
            ["tmux", "-L", self.socket_name, "-f", "/dev/null", *arguments],
            capture_output=True,
            text=True,
            timeout=10,
            env=self._environment,
        )
        if check and result.returncode != 0:
            raise RuntimeError(
                "tmux %s failed: %s"
                % (" ".join(arguments), (result.stderr or result.stdout).strip())
            )
        return result

    def start(self, session: str = "qualification") -> None:
        self.run(
            "new-session", "-d", "-s", session, "-n", "left",
            "bash", "--noprofile", "--norc",
        )

    def stop(self) -> None:
        self.run("kill-server", check=False)
        socket_root = Path(self._environment.get("TMUX_TMPDIR", "/tmp"))
        socket_path = socket_root / ("tmux-%d" % os.getuid()) / self.socket_name
        try:
            socket_path.unlink()
        except FileNotFoundError:
            pass

    def create_shell_window_after(
        self, anchor: str, name: str
    ) -> PaneObservation:
        self.run(
            "new-window", "-d", "-a", "-t", anchor, "-n", name,
            "bash", "--noprofile", "--norc",
        )
        return self.observe(name)

    def list_windows(self) -> list[str]:
        output = self.run(
            "list-windows", "-a", "-F",
            "#{session_name}:#{window_index}:#{window_name}",
        ).stdout
        return [line for line in output.splitlines() if line]

    def observe(self, target: str) -> PaneObservation:
        metadata = self.run(
            "display-message", "-p", "-t", target, "-F",
            "#{session_name}:#{window_index}.#{pane_index}|"
            "#{pane_id}|#{pane_pid}|#{window_id}|#{window_name}|"
            "#{cursor_x}|#{cursor_y}|#{history_size}|#{pane_current_command}",
        ).stdout.strip()
        fields = metadata.split("|", 8)
        if (len(fields) != 9 or not fields[0] or not fields[1]
                or not fields[2] or not fields[3]):
            raise RuntimeError("tmux returned malformed pane metadata")
        exact, pane_id, pane_pid, window_id = fields[:4]
        content = self.run(
            "capture-pane", "-p", "-J", "-S", "-200", "-t", pane_id
        ).stdout
        fingerprint = hashlib.sha256(
            (metadata + "\0" + content).encode("utf-8")
        ).hexdigest()
        return PaneObservation(
            target=exact,
            pane_id=pane_id,
            pane_pid=int(pane_pid),
            window_id=window_id,
            window_name=fields[4],
            current_command=fields[8],
            fingerprint=fingerprint,
            content=content,
        )

    def observe_all(self) -> list[PaneObservation]:
        pane_ids = self.run(
            "list-panes", "-a", "-F", "#{pane_id}"
        ).stdout.splitlines()
        return [self.observe(pane_id) for pane_id in pane_ids if pane_id]

    def guarded_send(
        self, observed: PaneObservation, text: str
    ) -> GuardedResult:
        if not text:
            return GuardedResult("rejected", "empty-input")
        try:
            current = self.observe(observed.pane_id)
        except RuntimeError:
            return GuardedResult("withheld", "target-no-longer-exists")
        if current.pane_id != observed.pane_id:
            return GuardedResult("withheld", "target-identity-changed")
        if current.fingerprint != observed.fingerprint:
            return GuardedResult("withheld", "pane-changed-since-observation")
        result = self.run(
            "send-keys", "-l", "-t", observed.pane_id, "--", text,
            ";", "send-keys", "-t", observed.pane_id, "Enter",
            check=False,
        )
        if result.returncode != 0:
            return GuardedResult(
                "failed", (result.stderr or result.stdout).strip()
            )
        return GuardedResult("sent", observed.pane_id)

    def unchecked_send(self, target: str, text: str) -> None:
        self.run(
            "send-keys", "-l", "-t", target, "--", text,
            ";", "send-keys", "-t", target, "Enter",
        )

    def wait_until(
        self,
        target: str,
        predicate: Callable[[PaneObservation], bool],
        timeout: float = 5.0,
    ) -> PaneObservation:
        deadline = time.monotonic() + timeout
        last = None
        while time.monotonic() < deadline:
            last = self.observe(target)
            if predicate(last):
                return last
            time.sleep(0.02)
        raise TimeoutError(
            "terminal predicate did not become true; last observation=%r"
            % (last,)
        )

    def wait_for_text(
        self, target: str, marker: str, timeout: float = 5.0
    ) -> PaneObservation:
        return self.wait_until(
            target, lambda observation: marker in observation.content, timeout
        )

    def wait_for_stable_text(
        self, target: str, marker: str, timeout: float = 5.0
    ) -> PaneObservation:
        """Wait for a named screen and one unchanged re-observation.

        Seeing the first byte of a prompt is not yet evidence that its process
        has entered the corresponding input state.  Stability replaces a
        guessed multi-second sleep with a witnessed quiescent boundary.
        """

        deadline = time.monotonic() + timeout
        previous = self.wait_for_text(target, marker, timeout)
        while time.monotonic() < deadline:
            time.sleep(0.02)
            current = self.observe(target)
            if (marker in current.content
                    and current.fingerprint == previous.fingerprint):
                return current
            previous = current
        raise TimeoutError("terminal screen did not become stable: %s" % marker)

    def wait_until_stable(
        self, target: str, timeout: float = 5.0
    ) -> PaneObservation:
        deadline = time.monotonic() + timeout
        previous = self.observe(target)
        while time.monotonic() < deadline:
            time.sleep(0.02)
            current = self.observe(target)
            if current.fingerprint == previous.fingerprint:
                return current
            previous = current
        raise TimeoutError("terminal pane did not become stable")
