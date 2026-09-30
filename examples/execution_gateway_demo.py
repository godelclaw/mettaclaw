"""Measure independent local gateways without touching an agent or network."""

import json
import os
from pathlib import Path
import statistics
import subprocess
import sys
import tempfile
import time

from execution_gateway import Client
from execution_gateway.store import TERMINAL

ROOT = Path(__file__).resolve().parents[1]


def wait(client, request_id):
    until = time.monotonic() + 5
    while time.monotonic() < until:
        receipt = client.status(request_id)
        if receipt and receipt["state"] in TERMINAL:
            return receipt
        time.sleep(0.005)
    raise RuntimeError("demo request did not finish")


def main():
    workers = []
    with tempfile.TemporaryDirectory(prefix="gateway-demo-") as directory:
        clients = {}
        try:
            for agent in ("alpha", "beta"):
                root = Path(directory) / agent
                root.mkdir()
                config = {"agent": agent, "state_directory": str(root), "tools": {
                    name: {"command": [sys.executable,
                            str(ROOT / "tests/fixtures/gateway_tool.py"), name],
                           "effect": "read", "result_format": "json"}
                    for name in ("echo", "delay", "crash")}}
                path = root / "config.json"
                path.write_text(json.dumps(config))
                process = subprocess.Popen(
                    [sys.executable, "-m", "execution_gateway", "--config", str(path)],
                    cwd=ROOT, env=dict(os.environ, PYTHONPATH=str(ROOT / "src")),
                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                    start_new_session=True)
                workers.append(process)
                client = Client(root / "gateway.sock", agent)
                until = time.monotonic() + 5
                while True:
                    if process.poll() is not None or time.monotonic() >= until:
                        raise RuntimeError("demo gateway failed to start")
                    try:
                        client.status("readiness")
                        break
                    except OSError:
                        time.sleep(0.01)
                clients[agent] = client
            alpha, beta = clients["alpha"], clients["beta"]
            start = time.monotonic()
            alpha.submit("slow", "delay", input={"seconds": 1})
            submission_ms = 1000 * (time.monotonic() - start)
            latencies = []
            for _ in range(25):
                start = time.monotonic()
                receipt = alpha.status("slow")
                latencies.append(1000 * (time.monotonic() - start))
                assert receipt["state"] not in TERMINAL
            start = time.monotonic()
            beta.submit("independent", "echo", input="not blocked")
            assert wait(beta, "independent")["state"] == "succeeded"
            other_agent_ms = 1000 * (time.monotonic() - start)
            assert alpha.status("slow")["state"] not in TERMINAL
            assert wait(alpha, "slow")["state"] == "succeeded"
            alpha.submit("crash", "crash")
            assert wait(alpha, "crash")["state"] == "failed"
            alpha.submit("after-crash", "echo", input="still usable")
            assert wait(alpha, "after-crash")["state"] == "succeeded"
            print(json.dumps({
                "slow_tool_seconds": 1,
                "submission_ms": round(submission_ms, 2),
                "status_median_ms": round(statistics.median(latencies), 2),
                "status_max_ms": round(max(latencies), 2),
                "other_agent_completion_ms": round(other_agent_ms, 2),
                "tool_crash_contained": True,
            }, indent=2))
        finally:
            for process in workers:
                if process.poll() is None:
                    process.terminate()
                    try:
                        process.wait(timeout=5)
                    except subprocess.TimeoutExpired:
                        process.kill()
                        process.wait()


if __name__ == "__main__":
    main()
