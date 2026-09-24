"""Background jobs: run a long command without blocking the turn.

Modelled on the background tasks of coding agents.  A job gets an id and an
output file at once; the runtime watches it, and when it ends a runtime event
with its exit status, duration and output tail arrives as ordinary activity
that also ends a rest.  Output can be read at any time, and a job can be
stopped.  Jobs are children of the agent process, so a service restart ends
them, and their records then say so.
"""

import json
import os
import signal
import subprocess
import threading
import time

TAIL_BYTES = 1500
OUTPUT_BYTES = 8000

_LOCK = threading.RLock()
_RUNNING = {}
_STOPPING = set()
_WATCHER = None


def _root():
    path = os.environ.get("METTACLAW_JOBS_DIR",
                          os.path.join("memory", "jobs"))
    os.makedirs(path, exist_ok=True)
    return path


def _record_path(job_id):
    return os.path.join(_root(), "%s.json" % job_id)


def _load(job_id):
    try:
        with open(_record_path(job_id), encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return None


def _save(record):
    path = _record_path(record["id"])
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(record, fh, ensure_ascii=False)
    os.replace(tmp, path)


def _records():
    found = []
    for name in os.listdir(_root()):
        if name.endswith(".json"):
            record = _load(name[:-len(".json")])
            if record:
                found.append(record)
    return sorted(found, key=lambda record: record.get("started", 0))


def _duration(seconds):
    import helper
    return helper._duration(seconds)


def _tail(path, limit):
    try:
        with open(path, "rb") as fh:
            fh.seek(0, os.SEEK_END)
            size = fh.tell()
            fh.seek(max(0, size - limit))
            text = fh.read().decode("utf-8", "replace")
    except OSError:
        return "", 0
    return ("…" if size > limit else "") + text, size


def _alive(pid):
    try:
        os.kill(int(pid), 0)
    except (OSError, ValueError, TypeError):
        return False
    return True


def start(command):
    """Start command under bash in its own session; return at once."""
    command = str(command).strip()
    if not command:
        return "background: empty command, nothing started"
    with _LOCK:
        numbers = [int(record["id"]) for record in _records()
                   if str(record.get("id", "")).isdigit()]
        job_id = str(max(numbers, default=0) + 1)
        log = os.path.abspath(os.path.join(_root(), "%s.log" % job_id))
        with open(log, "wb") as out:
            process = subprocess.Popen(
                ["bash", "-c", command], stdin=subprocess.DEVNULL,
                stdout=out, stderr=subprocess.STDOUT,
                start_new_session=True)
        _save({"id": job_id, "command": command, "pid": process.pid,
               "started": time.time(), "log": log, "state": "running"})
        _RUNNING[job_id] = process
        _ensure_watcher()
    return ("job %s started (pid %d); output: %s; you will be woken when "
            "it ends" % (job_id, process.pid, log))


def _ensure_watcher():
    global _WATCHER
    with _LOCK:
        if _WATCHER is None or not _WATCHER.is_alive():
            _WATCHER = threading.Thread(
                target=_watch, name="background-jobs", daemon=True)
            _WATCHER.start()


def _watch():
    while True:
        time.sleep(1)
        with _LOCK:
            finished = [(job_id, process)
                        for job_id, process in _RUNNING.items()
                        if process.poll() is not None]
            for job_id, _ in finished:
                del _RUNNING[job_id]
        for job_id, process in finished:
            _finish(job_id, process.returncode)


def _finish(job_id, code):
    with _LOCK:
        stopped = job_id in _STOPPING
        _STOPPING.discard(job_id)
    record = _load(job_id) or {"id": job_id}
    ended = time.time()
    record.update(state="stopped" if stopped else "done", exit=code,
                  ended=ended)
    _save(record)
    tail, size = _tail(record.get("log", ""), TAIL_BYTES)
    event = "job %s %s with exit %s after %s: %s\noutput %d bytes%s" % (
        job_id, "was stopped" if stopped else "finished", code,
        _duration(ended - record.get("started", ended)),
        record.get("command", "")[:300], size,
        (", tail:\n" + tail) if tail else "")
    try:
        import telegram
        telegram.enqueue_runtime_event(event, "job %s finished" % job_id)
    except Exception as exc:  # noqa: BLE001 - the record on disk remains
        print("[jobs] completion event not delivered:", type(exc).__name__)


def status():
    """Recent jobs, newest last: id, state, age or exit, command."""
    now = time.time()
    lines = []
    for record in _records()[-20:]:
        job_id = str(record.get("id"))
        with _LOCK:
            watched = job_id in _RUNNING
        state = record.get("state")
        if state == "running" and not watched:
            state = ("running, not watched since restart"
                     if _alive(record.get("pid")) else
                     "ended while the runtime was down, exit unknown")
        if record.get("state") == "running":
            timing = "for %s" % _duration(now - record.get("started", now))
        else:
            timing = "exit %s after %s" % (record.get("exit"), _duration(
                record.get("ended", now) - record.get("started", now)))
        lines.append("job %s %s %s: %s" % (
            job_id, state, timing, record.get("command", "")[:120]))
    return "\n".join(lines) if lines else "no background jobs"


def output(job_id, limit=OUTPUT_BYTES):
    """The end of a job's output, with its total size."""
    record = _load(str(job_id))
    if not record:
        return "job-output: no job %s" % job_id
    try:
        limit = max(1, int(limit))
    except (TypeError, ValueError):
        limit = OUTPUT_BYTES
    tail, size = _tail(record.get("log", ""), limit)
    return "job %s output, %d bytes%s:\n%s" % (
        job_id, size, " (tail)" if size > limit else "", tail)


def stop(job_id):
    """Terminate a running job and everything it started."""
    job_id = str(job_id)
    with _LOCK:
        process = _RUNNING.get(job_id)
        if process is None:
            return "job-stop: job %s is not running here" % job_id
        _STOPPING.add(job_id)
    try:
        os.killpg(process.pid, signal.SIGTERM)
    except OSError as exc:
        return "job-stop: could not signal job %s: %s" % (job_id, exc)
    return "job %s stopping; you will be woken when it has ended" % job_id


def running_count():
    with _LOCK:
        return len(_RUNNING)
