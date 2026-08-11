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

def ggbL3Share(agent, content, key, strength, confidence, goal, timestamp, origin):
    return 'ok'

def ggbL3Query(query_str, limit=5):
    return []

def ggbL3Revise(agent):
    return 'ok'
