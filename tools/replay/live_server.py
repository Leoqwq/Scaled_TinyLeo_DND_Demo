"""Loopback-only VM API / local relay. Connect endpoints using an SSH tunnel."""
import argparse
from datetime import datetime
import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import re
import secrets
import socketserver
import threading
import time
from urllib.parse import urlsplit, parse_qs
from urllib.request import Request, build_opener, ProxyHandler
import zipfile

from live import Session, validate_algorithm


def run_download_directory(output, run_id, algorithm, replay, tz=None):
    """Reuse a run's folder; label new folders with the first recorded local time."""
    if not re.fullmatch('[a-f0-9]{32}', run_id):
        raise ValueError('Invalid remote run id')
    validate_algorithm(algorithm)
    existing = sorted(output.glob(f'*/{run_id}.*'))
    if existing:
        return existing[0].parent
    frames = replay.get('modes', {}).get(algorithm, [])
    recorded = frames[0].get('telemetry', {}).get('recorded_unix_s') if frames else None
    # Failures before the first frame have no recorded time: use receipt time.
    stamp = datetime.fromtimestamp(recorded if recorded is not None else time.time(), tz).strftime('%Y-%m-%d_%H-%M-%S')
    target = output / f'{stamp}_{algorithm}'
    if target.exists():
        target = output / f'{stamp}_{algorithm}_{run_id}'
    return target


class Relay:
    def __init__(self, remote, token, output):
        parsed = urlsplit(remote)
        if parsed.scheme != 'http' or parsed.hostname != '127.0.0.1' or parsed.path not in ('', '/'):
            raise ValueError('Remote must be an HTTP SSH tunnel endpoint on 127.0.0.1')
        self.remote, self.token, self.output = remote.rstrip('/'), token, output
        output.mkdir(parents=True, exist_ok=True)
        self.lock = threading.Lock()
        self.state = dict(status='connecting', frames=0)
        self.frames = []
        self.stopped = threading.Event()
        threading.Thread(target=self.watch, daemon=True).start()

    def request(self, path, body=None):
        req = Request(self.remote + path, data=json.dumps(body).encode() if body is not None else None,
                      headers={'X-TinyLEO-Token':self.token, 'Content-Type':'application/json'})
        return build_opener(ProxyHandler({})).open(req, timeout=30)

    def start(self, algorithm):
        validate_algorithm(algorithm)
        with self.lock:
            if self.state.get('status') in ('completed', 'failed') and self.state.get('download') != 'saved':
                raise ValueError('Wait for the previous archive to finish downloading')
        with self.request('/start', dict(algorithm=algorithm)) as response:
            return json.load(response)

    def snapshot(self, after=-1):
        with self.lock:
            return dict(self.state, new_frames=self.frames[max(0,after+1):])

    def watch(self):
        while not self.stopped.is_set():
            try:
                with self.lock:
                    cursor, previous_id = len(self.frames)-1, self.state.get('run_id')
                with self.request('/state?after=' + str(cursor)) as response:
                    value = json.load(response)
                if value.get('run_id') != previous_id:
                    with self.request('/state?after=-1') as response:
                        value = json.load(response)
                    frames = value.pop('new_frames')
                else:
                    frames = self.frames + value.pop('new_frames')
                with self.lock:
                    old = self.state
                    if old.get('run_id') == value.get('run_id'):
                        for k in ('download', 'local_archive', 'download_error'):
                            if k in old:
                                value[k] = old[k]
                    self.frames, self.state = frames, value
                if value.get('sha256') and value.get('download') != 'saved':
                    self.download(value)
            except Exception as error:
                with self.lock:
                    self.state['connection_error'] = str(error)
            self.stopped.wait(1)

    def download(self, state):
        run_id = state['run_id']
        if not re.fullmatch('[a-f0-9]{32}', run_id):
            raise ValueError('Invalid remote run id')
        partial = self.output / f'.{run_id}.zip.partial'
        with self.lock:
            self.state['download'] = 'downloading'
        try:
            digest = hashlib.sha256()
            with self.request('/archive?run_id=' + run_id) as response, partial.open('wb') as stream:
                while chunk := response.read(1024*1024):
                    digest.update(chunk)
                    stream.write(chunk)
            if digest.hexdigest() != state['sha256']:
                raise ValueError('Archive SHA-256 mismatch; partial file retained, retrying')
            with zipfile.ZipFile(partial) as z:
                replay = z.read('replay.json')
                data = json.loads(replay)
            folder = run_download_directory(self.output, run_id, state['algorithm'], data)
            folder.mkdir(parents=True, exist_ok=True)
            target = folder / f'{run_id}.zip'
            os.replace(partial, target)
            replay_target = target.with_suffix('.replay.json')
            temporary = replay_target.with_suffix('.partial')
            temporary.write_bytes(replay)
            os.replace(temporary, replay_target)
            target.with_suffix('.sha256').write_text(state['sha256'] + '  ' + target.name + '\n')
            with self.lock:
                self.state.update(download='saved', local_archive=str(target))
                self.state.pop('download_error', None)
        except Exception as error:
            with self.lock:
                self.state.update(download='failed', download_error=str(error))


def server_for(backend, token, port, html=None):
    class LoopbackServer(ThreadingHTTPServer):
        def server_bind(self):
            socketserver.TCPServer.server_bind(self)
            self.server_name, self.server_port = self.server_address

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def send(self, code, value, content_type='application/json'):
            payload = json.dumps(value).encode() if content_type == 'application/json' else value
            self.send_response(code)
            self.send_header('Content-Type', content_type)
            self.send_header('Content-Length', str(len(payload)))
            self.send_header('Cache-Control', 'no-store')
            self.send_header('X-Content-Type-Options', 'nosniff')
            self.send_header('Content-Security-Policy', "frame-ancestors 'none'")
            self.end_headers()
            self.wfile.write(payload)

        def trusted(self, token_required=True):
            expected = f'127.0.0.1:{self.server.server_port}'
            # VM requests arrive through SSH forwarding with the tunnel's Host;
            # authenticated non-browser requests can use any loopback port only.
            host = self.headers.get('Host', '')
            if not re.fullmatch(r'127\.0\.0\.1:\d+', host) or (html and host != expected):
                return False
            origin = self.headers.get('Origin')
            if origin and origin != 'http://' + expected:
                return False
            return not token_required or secrets.compare_digest(self.headers.get('X-TinyLEO-Token',''), token)

        def do_GET(self):
            url = urlsplit(self.path)
            if url.path == '/' and html and self.trusted(False):
                page = html.read_text().replace('__LIVE_TOKEN__', token)
                return self.send(200, page.encode(), 'text/html; charset=utf-8')
            if not self.trusted():
                return self.send(403, {'error':'Forbidden'})
            try:
                if url.path == '/state':
                    after = int(parse_qs(url.query).get('after',['-1'])[0])
                    return self.send(200, backend.snapshot(after))
                if url.path == '/archive' and isinstance(backend, Session):
                    run_id = parse_qs(url.query).get('run_id',[''])[0]
                    with backend.lock:
                        if run_id != backend.state.get('run_id') or backend.archive is None:
                            raise ValueError('Archive unavailable for requested run')
                        archive = backend.archive
                    return self.send(200, archive.read_bytes(), 'application/zip')
                if url.path == '/replay' and isinstance(backend, Relay):
                    state = backend.snapshot()
                    if state.get('download') != 'saved':
                        raise ValueError('Replay archive not downloaded yet')
                    path = Path(state['local_archive']).with_suffix('.replay.json')
                    return self.send(200, path.read_bytes(), 'application/octet-stream')
                self.send(404, {'error':'Not found'})
            except (ValueError, OSError) as error:
                self.send(409, {'error':str(error)})

        def do_POST(self):
            if not self.trusted():
                return self.send(403, {'error':'Forbidden'})
            try:
                length = int(self.headers.get('Content-Length','0'))
                if not 0 < length <= 1024 or self.headers.get('Transfer-Encoding'):
                    raise ValueError('Invalid body length')
                if self.path != '/start':
                    return self.send(404, {'error':'Not found'})
                data = json.loads(self.rfile.read(length))
                if not isinstance(data, dict) or set(data) != {'algorithm'}:
                    raise ValueError('Only algorithm may be specified')
                self.send(202, backend.start(data['algorithm']))
            except Exception as error:
                self.send(409, {'error':str(error)})
    return LoopbackServer(('127.0.0.1', port), Handler)


def parse_args(argv=None):
    repo = Path(__file__).resolve().parents[2]
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command', required=True)
    vm = sub.add_parser('prepare-vm', help='MANUAL: creates nodes before serving Live requests')
    vm.add_argument('--root', type=Path, required=True)
    vm.add_argument('--template', type=Path, required=True)
    vm.add_argument('--routing-config', type=Path, required=True)
    vm.add_argument('--token-file', type=Path, required=True)
    vm.add_argument('--port', type=int, default=8766)
    vm.add_argument('--competition-scenario', type=Path, help='Explicit multi-flow profile; requires manual node re-preparation')
    vm.add_argument('--iperf-binary', default='iperf3', help='Competition requires a separate iperf3 >=3.20')
    local = sub.add_parser('local')
    local.add_argument('--remote', default='http://127.0.0.1:8767')
    local.add_argument('--token-file', type=Path, required=True)
    local.add_argument('--output', type=Path, default=repo / 'data',
                       help='Recording directory (default: repository data/)')
    local.add_argument('--html', type=Path, default=repo / 'replay.html',
                       help='Browser frontend (default: repository replay.html)')
    local.add_argument('--port', type=int, default=8765)
    return parser.parse_args(argv)


def main():
    args = parse_args()
    if args.command == 'prepare-vm':
        if args.token_file.exists():
            raise ValueError('Choose a new token file for this manually prepared session')
        token = secrets.token_urlsafe(32)
        fd = os.open(args.token_file, os.O_WRONLY|os.O_CREAT|os.O_EXCL, 0o600)
        with os.fdopen(fd, 'w') as f:
            f.write(token)
        backend = Session(args.root.resolve(), args.template.resolve(), args.routing_config.resolve(),
                          competition_scenario=args.competition_scenario, iperf_binary=args.iperf_binary)
        backend.prepare()
        server = server_for(backend, token, args.port)
    else:
        remote_token = args.token_file.read_text().strip()
        backend = Relay(args.remote, remote_token, args.output.resolve())
        server = server_for(backend, secrets.token_urlsafe(32), args.port, args.html.resolve())
    print(f'Ready: http://127.0.0.1:{args.port}', flush=True)
    server.serve_forever()


if __name__ == '__main__':
    main()
