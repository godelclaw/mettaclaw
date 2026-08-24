"""Full-path Gödel qualification against a disposable effect world.

Each model response is parsed by PeTTa's ``sread`` and executed by the same
``run-command-batch-once`` predicate as a live cognitive turn.  Only the final
effect provider is replaced.  This makes historical-failure replay useful as
an agent test rather than merely a test of a parallel JSON controller.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import tempfile
import uuid
from typing import Any

from tmux_qualification import IsolatedTmux


ROOT = Path(__file__).resolve().parents[1]
LAUNCH_COMMAND = (
    "python3 -u -c \"input('TRUST_PROMPT>'); "
    "print('SERVER_SELECTION>'); input(); print('CLAUDE_IDLE')\""
)


class FullShadow:
    """One isolated world plus the real MeTTa parse/dispatch boundary."""

    def __init__(self, auto_stop_after_first_effect: bool = False,
                 backend_selector: str | None = "tmux-shadow",
                 prompt_timeout: float = 5.0):
        self.temporary = tempfile.TemporaryDirectory(
            prefix="godel-full-shadow-"
        )
        self.directory = Path(self.temporary.name)
        self.state_path = self.directory / "state.json"
        self.socket_name = "godel-full-shadow-%s" % uuid.uuid4().hex[:12]
        self.world = IsolatedTmux(self.socket_name)
        self.auto_stop = auto_stop_after_first_effect
        self.backend_selector = backend_selector
        self.prompt_timeout = float(prompt_timeout)
        self.started = False

    def __enter__(self):
        self.start()
        return self

    def __exit__(self, _kind, _value, _traceback):
        self.stop()

    def start(self) -> None:
        if self.started:
            return
        self.world.start("shadow")
        self.world.run("rename-window", "-t", "shadow:left", "code-log")
        self.world.create_shell_window_after("shadow:code-log", "pleatta")
        self._write_state({
            "version": 1,
            "socket_name": self.socket_name,
            "room_name": "claude-room",
            "launch_command": LAUNCH_COMMAND,
            "phase": "need-create",
            "serial": 0,
            "receipts": {},
            "trace": [],
            "effects": 0,
            "finished": False,
            "operator_epoch": 0,
            "initial_operator_epoch": 0,
            "auto_stop_after_first_effect": self.auto_stop,
            "prompt_timeout": self.prompt_timeout,
        })
        self.started = True

    def stop(self) -> None:
        if self.started:
            self.world.stop()
            self.started = False
        self.temporary.cleanup()

    def _write_state(self, value: dict[str, Any]) -> None:
        self.state_path.write_text(
            json.dumps(value, ensure_ascii=False, sort_keys=True) + "\n",
            encoding="utf-8",
        )

    def state(self) -> dict[str, Any]:
        return json.loads(self.state_path.read_text(encoding="utf-8"))

    def environment(self) -> dict[str, str]:
        environment = dict(os.environ)
        python_paths = [str(ROOT / "src"), str(ROOT / "channels")]
        library = ROOT / "repos" / "petta_lib_chromadb"
        if library.is_dir():
            python_paths.append(str(library))
        environment.update({
            "PYTHONPATH": os.pathsep.join(python_paths),
            "METTACLAW_SKIP_INITIALIZE": "1",
            "METTACLAW_ENGINE": "petta",
            "METTACLAW_EFFECT_BACKEND_STATE": str(self.state_path),
            "METTACLAW_ENGINE_STATE_PATH": str(
                self.directory / "engine-selection"
            ),
            "METTACLAW_HISTORY_PATH": str(self.directory / "history.metta"),
            "METTACLAW_WORKING_SET_PATH": str(
                self.directory / "working-set.json"
            ),
            "METTACLAW_LOOP_MODE_PATH": str(self.directory / "loop-mode.json"),
            "METTACLAW_FUEL_MODE_PATH": str(self.directory / "fuel-mode.json"),
            "METTACLAW_ENERGY_PATH": str(self.directory / "energy.json"),
            "METTACLAW_PINS_PATH": str(self.directory / "pins.txt"),
            "METTACLAW_GOALS_PATH": str(self.directory / "goals.metta"),
            "METTACLAW_TELEGRAM_OFFSET_PATH": str(
                self.directory / "telegram-offset"
            ),
            "METTACLAW_TELEGRAM_LOG_PATH": str(
                self.directory / "telegram-updates.jsonl"
            ),
            "METTACLAW_EFFECT_RECEIPT_PATH": str(
                self.directory / "effect-receipts.jsonl"
            ),
        })
        if self.backend_selector is None:
            environment.pop("METTACLAW_EFFECT_BACKEND", None)
        else:
            environment["METTACLAW_EFFECT_BACKEND"] = self.backend_selector
        python_environment = Path(os.environ.get(
            "PETTA_PY_ENV", Path.home() / "miniforge3" / "envs" / "petta"
        ))
        if python_environment.is_dir():
            environment["PATH"] = os.pathsep.join((
                str(python_environment / "bin"),
                environment.get("PATH", ""),
            ))
            environment["LD_LIBRARY_PATH"] = os.pathsep.join((
                str(python_environment / "lib"),
                environment.get("LD_LIBRARY_PATH", ""),
            ))
            environment["PYTHONHOME"] = str(python_environment)
            environment["PYTHONNOUSERSITE"] = "1"
        return environment

    def _probe_source(self, response: str, turn: int,
                      batch_limit: int, begin_frontier: bool = True) -> str:
        # This is the live parser expression from cognitiveTurn, with only
        # logging/history removed. The same explicit quote crosses into the
        # same deterministic Prolog dispatcher.
        literal = json.dumps(str(response), ensure_ascii=False)
        frontier = (
            "!(println! (addition-effect-turn-begin %d))\n" % turn
            if begin_frontier else ""
        )
        return (
            "!(import! &self (library lib_import))\n"
            "!(import! &self ./src/utils)\n"
            "!(import! &self ./src/skills)\n"
            "!(import! &self ./src/command_pipeline)\n"
            "!(import! &self ./src/turn_additions)\n"
            "%s"
            "!(let* ("
            "($respi %s) "
            "($resp (addition-balance-response $respi)) "
            "($response (addition-envelope-response $resp)) "
            "($parsed (addition-read-response $response)) "
            "($sexpr (addition-command-sequence $parsed)) "
            "($records (addition-effect-broker %d %d (quote $sexpr)))) "
            "(println! (FULL_SHADOW_RECORDS: $records)))\n"
        ) % (frontier, literal, turn, batch_limit)

    def execute_response(self, response: str, turn: int,
                         batch_limit: int = 5,
                         begin_frontier: bool = True
                         ) -> subprocess.CompletedProcess:
        probe = self.directory / ("turn-%04d.metta" % turn)
        probe.write_text(
            self._probe_source(
                response, turn, batch_limit, begin_frontier=begin_frontier
            ),
            encoding="utf-8",
        )
        petta_root = Path(os.environ.get(
            "PETTA_ROOT", Path.home() / "repos" / "PeTTa"
        ))
        if not (petta_root / "run.sh").is_file():
            raise FileNotFoundError("PeTTa run.sh is unavailable")
        return subprocess.run(
            ["bash", str(petta_root / "run.sh"), str(probe)],
            cwd=ROOT,
            env=self.environment(),
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            timeout=30,
        )

    def world_state_projection(self) -> str:
        state = self.state()
        stop = (
            int(state.get("operator_epoch", 0))
            != int(state.get("initial_operator_epoch", 0))
        )
        return (
            "phase=%s effects=%s operator_stop=%s finished=%s"
            % (state.get("phase"), state.get("effects"),
               str(stop).lower(), str(bool(state.get("finished"))).lower())
        )
