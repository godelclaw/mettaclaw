import subprocess, json

GOV_CLI = '/home/oruzi/repos/godelclaw/bridges/ggb_l4_governance_cli.py'

def ggbGovernanceGate(action='tick'):
    try:
        r = subprocess.run(['python3', GOV_CLI, 'gate', str(action)],
                           capture_output=True, text=True, timeout=10)
        data = json.loads(r.stdout.strip())
        return data.get('gate', 'BLOCK')
    except Exception as e:
        return 'BLOCK'

EV_CLI = '/home/oruzi/repos/godelclaw/bridges/ggb_ev_cli.py'

def ggbL3Share(agent, content, key, strength, confidence, goal, timestamp, origin):
    try:
        r = subprocess.run(['python3', EV_CLI, 'add', str(agent), str(content), str(key),
                           str(strength), str(confidence), str(goal), str(timestamp), str(origin)],
                          capture_output=True, text=True, timeout=10)
        data = json.loads(r.stdout.strip())
        return data.get('id', 'error')
    except Exception:
        return 'error'

def ggbL3Query(query_str, limit=5):
    try:
        r = subprocess.run(['python3', EV_CLI, 'query', str(query_str), str(limit)],
                          capture_output=True, text=True, timeout=10)
        data = json.loads(r.stdout.strip())
        return data.get('results', [])
    except Exception:
        return []

def ggbL3Revise(agent):
    try:
        r = subprocess.run(['python3', EV_CLI, 'by-agent', str(agent)],
                          capture_output=True, text=True, timeout=10)
        data = json.loads(r.stdout.strip())
        return data.get('status', 'error')
    except Exception:
        return 'error'

PEER_CLI = '/home/oruzi/repos/godelclaw/bridges/ggb_peer_cli.py'

def ggbSendToPeer(peer, sender, subject, body):
    try:
        r = subprocess.run(['python3', PEER_CLI, 'send', str(peer), str(sender), str(subject), str(body)],
                          capture_output=True, text=True, timeout=10)
        data = json.loads(r.stdout.strip())
        return data.get('status', 'error')
    except Exception:
        return 'error'
