"""Keeps one `claude -p` process started and waiting, so a tech choice
doesn't pay the CLI's startup inside the game's freeze.

Started detached by decide_tech.py the first time it finds no worker running
(passing the claude argv it will ask with, so a spare starts at once), and
never by the mod. Listens on a localhost port recorded, with a random
token, in claude_worker.json beside this file. Each request carries the exact
claude argv, working directory and prompt; the reply is claude's `result`
event, the same fields `--output-format json` prints.

ONE PROCESS PER ANSWER, NEVER A CONVERSATION. The spare is started with
`--input-format stream-json`, which makes the CLI finish its whole startup and
then wait on stdin for messages; plain `-p` instead blocks on stdin partway
through startup and gives up after ~3s (docs/AI_OPPONENT_PLAN.md "Timing and
performance"). The worker writes exactly one user message and closes stdin, so
each answer comes from a fresh session that sees nothing of earlier calls -
the same prompt, token for token, that a direct `claude -p` call sends. It
returns as soon as the result event arrives, without waiting for the CLI's
~0.6s of exit, then starts the next spare.

A spare is used only if its argv and cwd match the request exactly; anything
else (a code change, a dead or never-started spare) is served by a fresh
process, which is no faster than calling claude directly but still correct.
Exits after IDLE_EXIT_SECONDS without a request, killing its spare.
"""

import hmac
import json
import os
import secrets
import socket
import subprocess
import sys
import threading
import time

WORKER_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'claude_worker.json')
IDLE_EXIT_SECONDS = 30 * 60


class _Spare(object):
    """One claude process, started now, answering one prompt later."""

    def __init__(self, argv, cwd):
        self.argv, self.cwd = argv, cwd
        self.proc = subprocess.Popen(
            argv, cwd=cwd, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL, text=True, encoding='utf-8',
            creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))

    def matches(self, argv, cwd):
        return self.proc.poll() is None and self.argv == argv and self.cwd == cwd

    def ask(self, prompt):
        message = {'type': 'user', 'message': {'role': 'user', 'content': prompt}}
        self.proc.stdin.write(json.dumps(message) + '\n')
        self.proc.stdin.close()
        for line in self.proc.stdout:
            try:
                event = json.loads(line)
            except ValueError:
                continue
            if isinstance(event, dict) and event.get('type') == 'result':
                # Let the CLI finish exiting on its own; nobody waits for it.
                threading.Thread(target=self._drain, daemon=True).start()
                return event
        raise RuntimeError('claude exited without a result (exit code %s)' % self.proc.wait())

    def _drain(self):
        self.proc.stdout.read()
        self.proc.wait()

    def kill(self):
        if self.proc.poll() is None:
            self.proc.kill()


def _write_worker_file(port, token):
    temp = WORKER_FILE + '.tmp'
    with open(temp, 'w', encoding='utf-8') as f:
        json.dump({'port': port, 'token': token, 'pid': os.getpid()}, f)
    os.replace(temp, WORKER_FILE)


def _remove_worker_file():
    """Only if it still names this process - a newer worker may own it."""
    try:
        with open(WORKER_FILE, encoding='utf-8') as f:
            if json.load(f).get('pid') == os.getpid():
                os.remove(WORKER_FILE)
    except (OSError, ValueError):
        pass


def _serve(conn, token, spare):
    """Answers one request. Returns the spare to keep for the next one."""
    reader = conn.makefile('r', encoding='utf-8')
    writer = conn.makefile('w', encoding='utf-8')
    request = json.loads(reader.readline())
    if not hmac.compare_digest(str(request.get('token', '')), token):
        return spare
    argv, cwd = request['argv'], request['cwd']
    warm = spare is not None and spare.matches(argv, cwd)
    if not warm:
        if spare is not None:
            spare.kill()
        spare = _Spare(argv, cwd)
    try:
        reply = {'ok': True, 'warm': warm, 'result': spare.ask(request['prompt'])}
    except Exception as exc:
        reply = {'ok': False, 'warm': warm, 'error': str(exc)}
    writer.write(json.dumps(reply) + '\n')
    writer.flush()
    return _Spare(argv, cwd)


def main():
    token = secrets.token_hex(16)
    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.bind(('127.0.0.1', 0))
    server.listen(1)
    server.settimeout(60)
    _write_worker_file(server.getsockname()[1], token)
    # decide_tech.py passes the argv it will ask with, so the first request
    # already finds a warm spare.
    spare = None
    if len(sys.argv) > 1:
        first = json.loads(sys.argv[1])
        spare = _Spare(first['argv'], first['cwd'])
    last_request = time.time()
    try:
        while time.time() - last_request < IDLE_EXIT_SECONDS:
            try:
                conn, _ = server.accept()
            except socket.timeout:
                continue
            last_request = time.time()
            with conn:
                conn.settimeout(300)
                try:
                    spare = _serve(conn, token, spare)
                except (OSError, ValueError, KeyError):
                    pass
    finally:
        if spare is not None:
            spare.kill()
        _remove_worker_file()
        server.close()


if __name__ == '__main__':
    sys.exit(main())
