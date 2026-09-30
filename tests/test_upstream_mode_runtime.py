"""Exercise real loop processes through production provider/CWP adapters."""
import http.server
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import threading
import time
import unittest

ROOT = Path(__file__).resolve().parents[1]


class Provider(http.server.BaseHTTPRequestHandler):
    requests = []
    def log_message(self, *args):
        pass
    def do_POST(self):
        value = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
        self.requests.append(value)
        if value.get('tools'):
            message = {'role': 'assistant', 'tool_calls': [
                {'id': 'fixture-nop', 'type': 'function',
                 'function': {'name': 'nop', 'arguments': '{}'}}]}
        else:
            message = {'role': 'assistant', 'content': 'pin smoke\nnop'}
        body = json.dumps({'choices': [{'message': message, 'finish_reason': 'stop'}]}).encode()
        self.send_response(200)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)


class ChannelServer:
    def __init__(self, path):
        self.server = socket.socket(socket.AF_UNIX, socket.SOCK_SEQPACKET)
        self.server.bind(str(path))
        self.server.listen()
        self.server.settimeout(.2)
        self.pending = {'fixture-input': json.dumps(['input', '1.0', 'message', 'operator',
            {'update_id': 1, 'message': {'chat': {'id': 1}, 'from': {'first_name': 'Fixture'},
                                       'text': 'remember this fixture'}}])}
        self.acks = []
        self.sends = []
        self.running = True
        self.thread = threading.Thread(target=self.run, daemon=True)
        self.thread.start()
    def run(self):
        while self.running:
            try:
                connection, _ = self.server.accept()
            except socket.timeout:
                continue
            with connection:
                packet = connection.recv(66000)
                code, n = packet[4:6]
                name, body = packet[6:6+n].decode(), packet[6+n:].decode()
                reply_code, reply_name, reply_body = 64, '', ''
                if code == 1 and not name and self.pending:
                    reply_code = 65
                    reply_name, reply_body = next(iter(self.pending.items()))
                elif code == 2:
                    reply_code = 66
                    self.pending.pop(name, None)
                    self.acks.append(name)
                elif code == 4:
                    reply_code = 66
                    self.sends.append(json.loads(body))
                connection.sendall(b'CWP1' + bytes([reply_code, len(reply_name)]) +
                                   reply_name.encode() + reply_body.encode())
    def close(self):
        self.running = False
        self.thread.join(1)
        self.server.close()


@unittest.skipUnless(os.environ.get('MODE_TEST_CETTA_BIN'), 'set MODE_TEST_CETTA_BIN for real CeTTa checks')
class ModeRuntimeTests(unittest.TestCase):
    def test_both_modes_checkpoint_restart_and_switch(self):
        with tempfile.TemporaryDirectory() as temporary:
            state = Path(temporary)
            agent = state/'agent'
            (agent/'memory').mkdir(parents=True)
            (agent/'src').symlink_to(ROOT/'src', target_is_directory=True)
            (agent/'channels').symlink_to(ROOT/'channels', target_is_directory=True)
            (state/'identity.txt').write_text('You are Fixture, a separate test identity.')
            (state/'lifecycle.json').write_text('{"schema":1,"state":"running"}')
            provider = http.server.ThreadingHTTPServer(('127.0.0.1', 0), Provider)
            threading.Thread(target=provider.serve_forever, daemon=True).start()
            channel = ChannelServer(state/'channel.sock')
            try:
                for mode in ('iter', 'omega'):
                    (agent/'memory/loop_mode.json').write_text(json.dumps({'mode': mode}))
                    environment = os.environ.copy()
                    environment.update({
                        'PYTHONPATH': str(ROOT/'src'),
                        'PYTHONHOME': sys.prefix,
                        'LD_LIBRARY_PATH': str(Path(sys.prefix)/'lib'),
                        'PYTHONDONTWRITEBYTECODE': '1',
                        'ITER_PYTHON': sys.executable,
                        'METTACLAW_MODE_STATE_ROOT': str(state/'modes'),
                        'METTACLAW_ENGINE_STATE_PATH': str(state/'engine'),
                        'METTACLAW_LIFECYCLE_PATH': str(state/'lifecycle.json'),
                        'METTACLAW_COGNITIVE_HEALTH_PATH': str(state/'health.json'),
                        'METTACLAW_MODEL_STATE_PATH': str(state/'model.metta'),
                        'METTACLAW_RECYCLE_REQUEST_PATH': str(state/'recycle'),
                        'METTACLAW_TELEGRAM_SERVICE_SOCKET': str(state/'channel.sock'),
                        'METTACLAW_TELEGRAM_PRIMARY_CHAT_ID': '1',
                        'METTACLAW_PROMPT_PATH': str(state/'identity.txt'),
                        'METTACLAW_MODE_CETTA_BIN': environment['MODE_TEST_CETTA_BIN'],
                        'PETTA_ROOT': '/unused', 'SYNTHETIC_MODEL': 'fixture-model',
                        'SYNTHETIC_BASE_URL': f'http://127.0.0.1:{provider.server_port}/v1',
                        'SYNTHETIC_API_KEY': 'fixture-only',
                    })
                    environment.pop('METTACLAW_LOOP_MODE_PATH', None)
                    command = [sys.executable, str(ROOT/'modes/launch.py'), '--repo', str(agent),
                               '--mode', mode, '--engine', 'cetta']
                    for restart in range(2):
                        trace = state/'modes'/mode/'runtime.jsonl'
                        count_before = trace.read_text().count('"kind": "boundary"') if trace.exists() else 0
                        with (state/f'{mode}-{restart}.log').open('w') as log:
                            process = subprocess.Popen(command, env=environment, stdout=log, stderr=log)
                            try:
                                deadline = time.monotonic()+45
                                while time.monotonic() < deadline:
                                    self.assertIsNone(process.poll(), (state/f'{mode}-{restart}.log').read_text())
                                    if trace.exists() and trace.read_text().count('"kind": "boundary"') > count_before+1:
                                        break
                                    time.sleep(.1)
                                else:
                                    self.fail((state/f'{mode}-{restart}.log').read_text()+'\n'+(trace.read_text() if trace.exists() else 'no trace'))
                                (state/'recycle').touch()
                                self.assertEqual(process.wait(timeout=8), 0)
                            finally:
                                if process.poll() is None:
                                    process.kill()
                                    process.wait()
                                (state/'recycle').unlink(missing_ok=True)
                        active = json.loads((state/'active-loop.json').read_text())
                        self.assertEqual(active['mode'], mode)
                        self.assertEqual(Path(active['state_directory']), state/'modes'/mode)
                    if mode == 'iter':
                        history = json.loads((state/'modes/iter/experience.json').read_text())
                        self.assertTrue(any('remember this fixture' in m.get('content','') for m in history))
                        self.assertIn('fixture-input', channel.acks)
                        channel.pending['omega-input'] = json.dumps(['input','1.0','message','operator',
                            {'message': {'chat': {'id':1},'text':'omega checkpoint fixture'}}])
                    else:
                        history = (state/'modes/omega/repos/Omega/memory/history.metta').read_text()
                        self.assertIn('omega checkpoint fixture', history)
                        self.assertIn('omega-input', channel.acks)
                native = next(r for r in Provider.requests if r.get('tools'))
                self.assertEqual(native['tool_choice'], 'required')
                self.assertTrue(any('Fixture' in m['content'] for m in native['messages']))
                self.assertTrue(any(not r.get('tools') for r in Provider.requests))
            finally:
                channel.close()
                provider.shutdown()
                provider.server_close()


if __name__ == '__main__':
    unittest.main()
