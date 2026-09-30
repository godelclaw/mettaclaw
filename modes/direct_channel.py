"""Keep an existing Bot API channel/control plane outside the cognitive engine.

Agents already using the durable CWP service do not launch this adapter.
It reuses the agent's Telegram client and activity receipts unchanged.
"""
import argparse
import json
import os
from pathlib import Path
import socket
import telegram


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--socket', type=Path, required=True)
    args = parser.parse_args()
    args.socket.unlink(missing_ok=True)
    telegram.start_telegram()
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as server:
        server.bind(str(args.socket))
        os.chmod(args.socket, 0o600)
        server.listen(8)
        while True:
            connection, _ = server.accept()
            with connection:
                connection.settimeout(10)
                stream = connection.makefile('rwb')
                try:
                    request = json.loads(stream.readline(65537))
                    action = request.get('action')
                    if action == 'receive':
                        value = telegram.getActivityBatch()
                    elif action == 'commit':
                        value = telegram.ackActivityBatch()
                    elif action == 'send':
                        value = telegram.send_message(request['text'])
                    else:
                        raise ValueError('unknown channel operation')
                    response = {'ok': True, 'value': value}
                except Exception as error:
                    response = {'ok': False, 'error': type(error).__name__}
                stream.write(json.dumps(response).encode()+b'\n')
                stream.flush()


if __name__ == '__main__':
    main()
