"""Autonomic goal-stack kernel (Lila's to-mama spec v0.2, 2026-07-18).

Pure bookkeeping over memory/goals.metta — no LLM tokens. The kernel runs
at wake events (boot, human-armed turn, heartbeat re-arm), NOT every loop
iteration, so a 50-turn burst counts as one wake for decay purposes.

File atoms (one per line; kernel-owned atoms marked *):
  (goal-budget 3.0)
  (goal <name> <area> sti:<0-1> lti:<0-1> vibes:(<v>*)
        blocked-by:<none|token|"text"> last-verified:<never|token> note:"<text>")
  (goal-flag <name> <stuck|saturated|cull-review>)   *
  (mood Cn:x C:x Ct:x I:x J:x A:x S:x Co:x Sp:x)     *

Streak counters and the outbound-log offset live in memory/goals_kernel.json;
dropped goals are appended to memory/goals_compost.log (nothing is ever lost).
"""

import json
import os
import re
import threading
import time

_LOCK = threading.Lock()

DECAY = 0.95            # STI backstop decay per wake
ALPHA = 0.05            # LTI consolidation rate
GAMMA = 0.9             # mood EMA retention per affect sample
STUCK_WAKES = 3         # unchanged blocked-by across this many wakes -> stuck
CULL_STI = 0.05         # sti below this AND lti below CULL_LTI -> cull-review
CULL_LTI = 0.1
DEFAULT_BUDGET = 3.0
MOOD_DIMS = ("Cn", "C", "Ct", "I", "J", "A", "S", "Co", "Sp")

# \s* after each field colon: a stray space must not reject the goal
# (cost the agent six live turns of misdiagnosis on 2026-07-18).
_GOAL_RE = re.compile(
    r'^\(goal\s+(?P<name>[^\s()"]+)\s+(?P<area>[^\s()"]+)'
    r'\s+sti:\s*(?P<sti>-?[\d.]+)\s+lti:\s*(?P<lti>-?[\d.]+)'
    r'\s+vibes:\s*\((?P<vibes>[^()]*)\)'
    r'\s+blocked-by:\s*(?P<blocked>none|"[^"]*"|[^\s()"]+)'
    r'\s+last-verified:\s*(?P<verified>[^\s()"]+)'
    r'\s+note:\s*(?:"(?P<noteq>[^"]*)"|(?P<note>[^()"]*))\)\s*$')
_FLAG_RE = re.compile(r'^\(goal-flag\s+(\S+)\s+(stuck|saturated|cull-review)\)\s*$')
_BUDGET_RE = re.compile(r'^\(goal-budget\s+([\d.]+)\)\s*$')
_MOOD_RE = re.compile(r'^\(mood\s.*\)\s*$')
_AFFECT_RE = re.compile(r'⋄⟨([^⟩]*)⟩')
_AFFECT_PAIR_RE = re.compile(r'(Cn|Ct|Co|Sp|C|I|J|A|S):(-?[\d.]+)')


def _goal_dict(m):
    """Normalized goal dict from a _GOAL_RE match (quoted or free-text note)."""
    g = m.groupdict()
    note = g.pop("noteq")
    g["note"] = note if note is not None else (g["note"] or "").strip()
    g["sti"] = min(1.0, max(0.0, float(g["sti"])))
    g["lti"] = min(1.0, max(0.0, float(g["lti"])))
    return g


def _goals_path(path=None):
    return str(path or os.environ.get(
        "METTACLAW_GOALS_PATH",
        os.path.join(os.path.dirname(os.environ.get(
            "METTACLAW_HISTORY_PATH", "memory/history.metta")), "goals.metta")))


def _kernel_path(goals_path):
    return os.path.join(os.path.dirname(goals_path), "goals_kernel.json")


def _compost_path(goals_path):
    return os.path.join(os.path.dirname(goals_path), "goals_compost.log")


def _read_lines(path):
    try:
        with open(path, encoding="utf-8") as fh:
            return fh.read().splitlines()
    except OSError:
        return None


def _write_lines(path, lines):
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines) + "\n")
    os.replace(tmp, path)


def _fmt_goal(g):
    return ('(goal {name} {area} sti:{sti} lti:{lti} vibes:({vibes}) '
            'blocked-by:{blocked} last-verified:{verified} note:"{note}")'
            .format(**g))


def _parse(lines):
    """Split file lines into goals (ordered), flags, budget, other lines."""
    goals, flags, other = [], set(), []
    budget = None
    for line in lines:
        m = _GOAL_RE.match(line)
        if m:
            goals.append(_goal_dict(m))
            continue
        m = _FLAG_RE.match(line)
        if m:
            flags.add((m.group(1), m.group(2)))
            continue
        m = _BUDGET_RE.match(line)
        if m:
            budget = float(m.group(1))
            continue
        if _MOOD_RE.match(line):
            continue  # kernel-owned; re-emitted each pass
        other.append(line)
    return goals, flags, budget, other


def _emit(goals, flags, budget, other, mood):
    lines = list(other)
    if lines and lines[-1].strip():
        lines.append("")
    lines.append("(goal-budget %s)" % _r(budget))
    for g in goals:
        g = dict(g, sti=_r(g["sti"]), lti=_r(g["lti"]))
        lines.append(_fmt_goal(g))
    for name, flag in sorted(flags):
        lines.append("(goal-flag %s %s)" % (name, flag))
    if mood:
        lines.append("(mood %s)" % " ".join(
            "%s:%s" % (d, _r(mood[d])) for d in MOOD_DIMS))
    return lines


def _r(x):
    return ("%.4f" % float(x)).rstrip("0").rstrip(".") or "0"


def _load_kernel_state(path):
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return {}


def _mood_samples(log_path, offset):
    """Affect vectors from outbound sends appended since offset."""
    samples = []
    try:
        size = os.path.getsize(log_path)
        if offset > size:
            offset = 0
        with open(log_path, encoding="utf-8", errors="replace") as fh:
            fh.seek(offset)
            for line in fh:
                try:
                    rec = json.loads(line)
                except ValueError:
                    continue
                if rec.get("kind") != "outbound":
                    continue
                for trace in _AFFECT_RE.findall(rec.get("text", "")):
                    pairs = dict(_AFFECT_PAIR_RE.findall(trace))
                    if len(pairs) >= 6:
                        samples.append({d: float(v) for d, v in pairs.items()})
            offset = fh.tell()
    except OSError:
        pass
    return samples, offset


def kernel_pass(goals_path=None, log_path=None):
    """One autonomic wake: decay, consolidate, flag, normalize, mood-EMA."""
    with _LOCK:
        try:
            path = _goals_path(goals_path)
            lines = _read_lines(path)
            if lines is None:
                lines = [";; goal stack — syntax in SKILLS; kernel decays/flags at each wake"]
            goals, flags, budget, other = _parse(lines)
            if budget is None:
                budget = DEFAULT_BUDGET

            state = _load_kernel_state(_kernel_path(path))
            streaks = state.get("streaks", {})

            for g in goals:
                g["sti"] *= DECAY
                g["lti"] = g["lti"] + ALPHA * max(0.0, g["sti"] - g["lti"])
                prev = streaks.get(g["name"], {})
                if g["blocked"] != "none" and g["blocked"] == prev.get("blocked"):
                    streak = prev.get("streak", 0) + 1
                else:
                    streak = 0
                streaks[g["name"]] = {"blocked": g["blocked"], "streak": streak}
                if streak + 1 >= STUCK_WAKES:
                    flags.add((g["name"], "stuck"))
                else:
                    flags.discard((g["name"], "stuck"))
                if g["sti"] < CULL_STI and g["lti"] < CULL_LTI:
                    flags.add((g["name"], "cull-review"))

            total = sum(g["sti"] for g in goals)
            if total > budget > 0:
                scale = budget / total
                for g in goals:
                    g["sti"] *= scale

            names = {g["name"] for g in goals}
            flags = {(n, f) for n, f in flags if n in names}
            streaks = {n: s for n, s in streaks.items() if n in names}

            mood = {d: float(state.get("mood", {}).get(d, 0.0)) for d in MOOD_DIMS}
            have_mood = bool(state.get("mood"))
            lp = str(log_path or os.environ.get("METTACLAW_TELEGRAM_LOG_PATH", ""))
            offset = int(state.get("log_offset", 0))
            if lp:
                samples, offset = _mood_samples(lp, offset)
                for s in samples:
                    if not have_mood:
                        mood = {d: s.get(d, 0.0) for d in MOOD_DIMS}
                        have_mood = True
                    else:
                        for d in MOOD_DIMS:
                            mood[d] = GAMMA * mood[d] + (1 - GAMMA) * s.get(d, mood[d])

            _write_lines(path, _emit(goals, flags, budget, other,
                                     mood if have_mood else None))
            state = {"streaks": streaks, "log_offset": offset,
                     "mood": mood if have_mood else {}}
            with open(_kernel_path(path) + ".tmp", "w", encoding="utf-8") as fh:
                json.dump(state, fh)
            os.replace(_kernel_path(path) + ".tmp", _kernel_path(path))

            flagged = ["%s:%s" % (n, f) for n, f in sorted(flags)]
            return ("goal-kernel: %d goals, sti %s/%s%s"
                    % (len(goals), _r(sum(g["sti"] for g in goals)), _r(budget),
                       (", flags " + " ".join(flagged)) if flagged else ""))
        except Exception as exc:
            return "goal-kernel error: %s" % exc


def goals_view(goals_path=None):
    lines = _read_lines(_goals_path(goals_path))
    if not lines:
        return "(no goals yet — add one with (goal-write ...))"
    return "\n".join(lines)


def goal_write(atom, goals_path=None):
    """Add or update one goal (or the budget) from its S-expression text."""
    with _LOCK:
        path = _goals_path(goals_path)
        text = str(atom).strip()
        mb = _BUDGET_RE.match(text)
        if mb:
            budget = float(mb.group(1))
            if not 0.5 <= budget <= 10:
                return "goal-budget must be in [0.5, 10]"
        m = _GOAL_RE.match(text)
        if not (m or mb):
            return ('rejected: expected (goal <name> <area> sti:<0-1> lti:<0-1> '
                    'vibes:(..) blocked-by:<none|hyphenated-token> '
                    'last-verified:<never|timestamp> note:free text) on one '
                    'line — no quotes needed, hyphenate blocked-by')
        lines = _read_lines(path) or []
        goals, flags, old_budget, other = _parse(lines)
        state = _load_kernel_state(_kernel_path(path))
        mood = state.get("mood") or None
        if mb:
            _write_lines(path, _emit(goals, flags, budget, other, mood))
            return "budget set to %s" % _r(budget)
        g = _goal_dict(m)
        existing = [i for i, cur in enumerate(goals) if cur["name"] == g["name"]]
        if existing:
            goals[existing[0]] = g
            verdict = "goal %s updated" % g["name"]
        else:
            goals.append(g)
            verdict = "goal %s added" % g["name"]
        _write_lines(path, _emit(goals, flags,
                                 old_budget if old_budget is not None else DEFAULT_BUDGET,
                                 other, mood))
        return verdict


def goal_drop(name, reason, goals_path=None):
    """Remove a goal. Allowed only via death-review (cull-review flag) or as
    solved with a real last-verified — never-verified goals cannot be solved."""
    with _LOCK:
        path = _goals_path(goals_path)
        name, reason = str(name), str(reason)
        lines = _read_lines(path) or []
        goals, flags, budget, other = _parse(lines)
        match = [g for g in goals if g["name"] == name]
        if not match:
            return "no goal named %s" % name
        g = match[0]
        if reason == "solved":
            if g["verified"] == "never":
                return ("rejected: last-verified is 'never' — verify progress "
                        "(goal-write with a last-verified timestamp) before "
                        "claiming solved")
        elif (name, "cull-review") not in flags:
            return ("rejected: drop requires the cull-review flag (death-review) "
                    "or reason 'solved' on a verified goal")
        try:
            with open(_compost_path(path), "a", encoding="utf-8") as fh:
                fh.write("%s %s %s\n" % (
                    time.strftime("%Y-%m-%dT%H:%M:%S"), reason, _fmt_goal(g)))
        except OSError:
            pass
        goals = [x for x in goals if x["name"] != name]
        flags = {(n, f) for n, f in flags if n != name}
        state = _load_kernel_state(_kernel_path(path))
        _write_lines(path, _emit(goals, flags,
                                 budget if budget is not None else DEFAULT_BUDGET,
                                 other, state.get("mood") or None))
        return "goal %s composted (%s) — remember a compost note" % (name, reason)
