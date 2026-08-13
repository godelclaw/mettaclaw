import datetime
import json
import os
import pathlib
import subprocess
import sys
import tempfile

import selfmod


GOV_CLI = os.environ.get("METTACLAW_GGB_GOVERNANCE_CLI", "")

def ggbGovernanceGate(action='tick'):
    try:
        if not GOV_CLI:
            return 'BLOCK'
        r = subprocess.run([sys.executable, GOV_CLI, 'gate', str(action)],
                           capture_output=True, text=True, timeout=10)
        data = json.loads(r.stdout.strip())
        return data.get('gate', 'BLOCK')
    except Exception:
        return 'BLOCK'

EV_CLI = os.environ.get("METTACLAW_GGB_EVIDENCE_CLI", "")

def ggbL3Share(agent, content, key, strength, confidence, goal, timestamp, origin):
    try:
        if not EV_CLI:
            return 'error'
        r = subprocess.run([sys.executable, EV_CLI, 'add', str(agent), str(content), str(key),
                           str(strength), str(confidence), str(goal), str(timestamp), str(origin)],
                          capture_output=True, text=True, timeout=10)
        data = json.loads(r.stdout.strip())
        return data.get('id', 'error')
    except Exception:
        return 'error'

def ggbL3Query(query_str, limit=5):
    try:
        if not EV_CLI:
            return []
        r = subprocess.run([sys.executable, EV_CLI, 'query', str(query_str), str(limit)],
                          capture_output=True, text=True, timeout=10)
        data = json.loads(r.stdout.strip())
        return data.get('results', [])
    except Exception:
        return []

def ggbL3Revise(agent):
    try:
        if not EV_CLI:
            return 'error'
        r = subprocess.run([sys.executable, EV_CLI, 'by-agent', str(agent)],
                          capture_output=True, text=True, timeout=10)
        data = json.loads(r.stdout.strip())
        return data.get('status', 'error')
    except Exception:
        return 'error'

PEER_CLI = os.environ.get("METTACLAW_GGB_PEER_CLI", "")

def ggbSendToPeer(peer, sender, subject, body):
    try:
        if not PEER_CLI:
            return 'error'
        r = subprocess.run([sys.executable, PEER_CLI, 'send', str(peer), str(sender), str(subject), str(body)],
                          capture_output=True, text=True, timeout=10)
        data = json.loads(r.stdout.strip())
        return data.get('status', 'error')
    except Exception:
        return 'error'

SELFMOD_CLI = os.environ.get("METTACLAW_GGB_SELFMOD_CLI", "")

def ggbSelfModGate(change_spec, harm=None, recip=None, unity=None):
    if not SELFMOD_CLI:
        return 'BLOCK'
    args = [sys.executable, SELFMOD_CLI, str(change_spec)]
    if harm is not None: args.append(str(harm))
    if recip is not None: args.append(str(recip))
    if unity is not None: args.append(str(unity))
    try:
        r = subprocess.run(args, capture_output=True, text=True, timeout=10)
        data = json.loads(r.stdout.strip())
        return data.get('gate', 'BLOCK')
    except Exception:
        return 'BLOCK'


def _selfmod_log_path():
    configured = os.environ.get("METTACLAW_SELFMOD_LOG", "")
    if configured:
        return pathlib.Path(configured)
    state_home = pathlib.Path(
        os.environ.get("XDG_STATE_HOME", pathlib.Path.home() / ".local" / "state")
    )
    instance = os.environ.get("METTACLAW_INSTANCE", "pettaclaw")
    return state_home / instance / "selfmod-log.jsonl"

def ggbSafeSelfMod(change_spec, action_desc='', harm=None, recip=None, unity=None):
    gate = ggbSelfModGate(change_spec, harm, recip, unity)
    entry = {
        'ts': datetime.datetime.now(datetime.timezone.utc).isoformat(),
        'change_spec': str(change_spec),
        'action_desc': str(action_desc),
        'gate': gate,
    }
    try:
        log_path = _selfmod_log_path()
        log_path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        with open(log_path, 'a', encoding='utf-8') as f:
            f.write(json.dumps(entry))
            f.write(chr(10))
    except OSError:
        pass
    return gate


def _semantic_requested():
    return os.environ.get("METTACLAW_SELFMOD_SEMANTIC_CHECK", "0").lower() in {
        "1", "true", "yes", "on"
    }


def _governance_requested():
    return os.environ.get("METTACLAW_SELFMOD_REQUIRE_GOVERNANCE", "0").lower() in {
        "1", "true", "yes", "on"
    }


def _proposal_policy(summary):
    encoded = json.dumps(summary, sort_keys=True, separators=(",", ":"))
    return ggbSafeSelfMod(
        encoded,
        action_desc="structured self-modification proposal",
    )


def _proposal_result(manifest):
    return (
        "PROPOSAL_READY id=%s target=%s sha256=%s promotion=pending"
        % (
            manifest["proposal_id"],
            manifest["target"],
            manifest["candidate_sha256"],
        )
    )


def _run_proposal(prepare):
    try:
        prepared = prepare()
        manifest = selfmod.propose(
            prepared,
            policy=_proposal_policy if _governance_requested() else None,
            semantic=_semantic_requested(),
        )
        return _proposal_result(manifest)
    except selfmod.SelfModError as exc:
        return "PROPOSAL_BLOCKED: %s" % exc


def ggbProposeWrite(filename, content, reason=''):
    return _run_proposal(
        lambda: selfmod.prepare_write(filename, content, reason=reason)
    )


def ggbProposeEdit(filename, old, new, reason=''):
    return _run_proposal(
        lambda: selfmod.prepare_edit(filename, old, new, reason=reason)
    )


def ggbProposeAppend(filename, content, reason=''):
    return _run_proposal(
        lambda: selfmod.prepare_append(filename, content, reason=reason)
    )


def ggbCheckCommandGate(_cmd_repr):
    """Compatibility shim; authority now lives at the structured file tools."""
    return 'PASS'

def ggbParseCheck(filename):
    try:
        settings = selfmod.Settings.from_env()
        parts = selfmod._target_parts(settings, filename)
        current, _ = selfmod._read_current(settings, parts)
        if current is None:
            return 'BLOCK'
        prepared = selfmod.PreparedChange(
            operation="legacy-parse-check",
            target="/".join(parts),
            candidate=current,
            candidate_sha256=selfmod._sha256(current),
            base_sha256=selfmod._sha256(current),
            base_exists=True,
            provenance={},
        )
        with tempfile.TemporaryDirectory(prefix="pettaclaw-parse-") as tmp:
            candidate = pathlib.Path(tmp) / "candidate"
            candidate.write_bytes(prepared.candidate)
            selfmod.check_syntax(prepared, candidate, settings)
        return 'PASS'
    except (OSError, UnicodeError, selfmod.SelfModError):
        return 'BLOCK'
