"""Exact receiver records and run-owned process lifecycle for competition.

Requires a side-by-side iperf3 >=3.20 with JSON streaming and millisecond start
timestamps. Never substitutes sender counters or rounded text for receiver data.
"""
from copy import deepcopy
import json
import math
import os
from pathlib import Path
import re
import signal
import subprocess
import threading
import time


def _finite(value, minimum=0):
    return type(value) in (int, float) and math.isfinite(value) and value >= minimum


def require_streaming(version, help_text):
    match = re.search(r'iperf\s+(\d+)\.(\d+)', version)
    if not match or tuple(map(int, match.groups())) < (3, 20) or '--json-stream' not in help_text:
        raise ValueError('Competition requires a separate iperf3 >=3.20 with --json-stream; old Live remains supported')


def _receiver_sum(data):
    if data.get('sender') is not False:
        raise ValueError('Not an explicit receiver counter record')
    for key in ('start', 'end', 'seconds', 'jitter_ms'):
        if not _finite(data.get(key)):
            raise ValueError(f'Invalid receiver {key}')
    if data['end'] <= data['start'] or data['seconds'] <= 0:
        raise ValueError('Empty receiver interval')
    for key in ('bytes', 'packets', 'lost_packets'):
        if type(data.get(key)) is not int or data[key] < 0:
            raise ValueError(f'Invalid receiver {key}')
    if data['lost_packets'] > data['packets']:
        raise ValueError('Receiver loss exceeds packet count')
    return {'start_s': data['start'], 'end_s': data['end'],
            'duration_s': data['seconds'], 'bytes_received': data['bytes'],
            'packets': data['packets'], 'lost_packets': data['lost_packets'],
            'jitter_ms': data['jitter_ms'], 'source': 'iperf_receiver_interval'}


def parse_iperf_interval(line):
    event = json.loads(line)
    if event.get('event') != 'interval':
        return None
    data = event.get('data', {}).get('sum', {})
    if data.get('sender') is True or data.get('omitted') is True:
        return None
    return _receiver_sum(data)


def parse_ping(line):
    stamp = re.match(r'^\[(\d+\.\d+)\]', line)
    seq = re.search(r'icmp_seq[= ](\d+)', line)
    if not stamp or not seq:
        return None
    reply = re.search(r'time=(\d+(?:\.\d+)?)\s*ms', line)
    if not reply and 'no answer yet' not in line:
        return None
    return {'unix_s': float(stamp[1]), 'sequence': int(seq[1]),
            'rtt_ms': float(reply[1]) if reply else None,
            'kind': 'reply' if reply else 'unanswered'}


class FlowRecords:
    def __init__(self, origin_unix):
        self.origin_unix = origin_unix
        self.test_start_unix = None
        self.intervals, self.probes = [], {}
        self.final = None
        self.complete = False

    def receive(self, line, received_unix):
        event = json.loads(line)
        kind, data = event.get('event'), event.get('data', {})
        if kind == 'error':
            raise ValueError(f'iperf receiver error: {data}')
        if kind == 'start':
            stamp = data.get('timestamp', {}).get('timemillisecs')
            if not _finite(stamp) or data.get('test_start', {}).get('protocol') != 'UDP':
                raise ValueError('Missing millisecond receiver start timestamp or UDP protocol')
            self.test_start_unix = stamp / 1000.
        elif kind in ('interval', 'end'):
            if self.test_start_unix is None:
                raise ValueError('Receiver interval arrived before start event')
            if kind == 'interval':
                record = parse_iperf_interval(line)
                if record is None:
                    return
            else:
                record = _receiver_sum(data.get('sum_received', {}))
                record['source'] = 'iperf_receiver_final'
            offset = self.test_start_unix - self.origin_unix
            record.update(start_s=offset + record['start_s'], end_s=offset + record['end_s'],
                          collected_unix_s=received_unix, alignment='iperf_start_wall_ms',
                          timestamp_resolution_s=.001)
            if kind == 'interval':
                if self.intervals and record['start_s'] < self.intervals[-1]['end_s'] - 1e-6:
                    raise ValueError('Overlapping receiver intervals')
                self.intervals.append(record)
            else:
                self.final, self.complete = record, True

    def probe(self, line):
        record = parse_ping(line)
        if record:
            record['simulation_time_s'] = record['unix_s'] - self.origin_unix
            old = self.probes.get(record['sequence'])
            if old is None or (old['kind'] != 'reply' and record['kind'] == 'reply'):
                self.probes[record['sequence']] = record

    def ping_samples(self):
        return [self.probes[key] for key in sorted(self.probes)]


class ProcessOwner:
    """Own only explicitly spawned process groups; preserve raw stdout/stderr."""
    def __init__(self, directory):
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=True)
        self.processes, self.readers, self.errors = {}, [], []
        self.closed = False

    def spawn(self, label, argv, callback=None):
        if self.closed or label in self.processes or not re.fullmatch(r'[a-z0-9-]+', label):
            raise ValueError('Invalid or duplicate owned process label')
        stream = (self.directory / f'{label}.log').open('x')
        try:
            process = subprocess.Popen(argv, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                       text=True, bufsize=1, start_new_session=True,
                                       env=dict(os.environ, LC_ALL='C'))
        except Exception:
            stream.close()
            raise
        self.processes[label] = process
        def read():
            with stream:
                try:
                    for line in process.stdout:
                        stream.write(line)
                        stream.flush()
                        if callback:
                            try:
                                callback(line)
                            except Exception as error:
                                self.errors.append(f'{label}: {error}')
                finally:
                    process.stdout.close()
        reader = threading.Thread(target=read, daemon=True)
        reader.start()
        self.readers.append(reader)
        return process

    def require_alive(self, label):
        if self.processes[label].poll() is not None:
            raise ValueError(f'{label} exited: {self.processes[label].returncode}')

    def stop(self, label):
        process = self.processes.get(label)
        if process and process.poll() is None:
            try:
                os.killpg(process.pid, signal.SIGINT)
            except ProcessLookupError:
                pass

    def close(self):
        if self.closed:
            return
        self.closed = True
        for label in self.processes:
            self.stop(label)
        for process in self.processes.values():
            try:
                process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                try:
                    os.killpg(process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                process.wait(timeout=3)
        for reader in self.readers:
            reader.join(timeout=2)
            if reader.is_alive():
                self.errors.append('Reader did not stop; raw measurements incomplete')


def traffic_commands(demand, shaping, binary):
    cell, gs = demand['destination'], demand['destination_gs']
    row, col, index = cell // 11 + 1, cell % 11 + 1, int(gs[2:])
    address = f'ce:{row}:ce:{col}:{index}::{index}'
    receiver = ['ip', 'netns', 'exec', gs, str(binary), '-s', '-1', '-6',
                '-B', address, '-p', str(demand['port']), '-i', '1', '--json-stream', '--forceflush']
    prefix = ['ip', 'netns', 'exec', demand['source_gs']]
    sender = prefix + [str(binary), '-c', address, '-6', '-p', str(demand['port']),
                       '-u', '-b', str(round(demand['demand_gbps'] * 1e9)),
                       '-l', str(shaping['udp_payload_bytes']),
                       '-t', str(demand['end_s'] - demand['start_s']),
                       '--connect-timeout', '3000', '--json-stream', '--forceflush']
    probe = prefix + ['ping', '-6', '-n', '-D', '-O', '-i', '1', address]
    return {'receiver': receiver, 'sender': sender, 'probe': probe}


def due_actions(config, events, second):
    actions = []
    for d in config['traffic_demands']:
        state = events.get(d['id'], {})
        if d['start_s'] <= second < d['end_s'] and 'started_s' not in state:
            actions.append(('start', d['id']))
        elif second >= d['end_s'] and 'started_s' in state and 'stopped_s' not in state:
            actions.append(('stop', d['id']))
    return actions


class TrafficSession:
    """Worker-owned traffic, with a nonblocking applied-epoch notification.

    `start` is pre-run setup. `advance` is called after each topology update;
    it does no subprocess I/O. Traffic starts only after the relevant policy
    was applied, and actual start/end deviations are retained in the archive.
    """
    def __init__(self, config, output, binary):
        from scenario import validate_scenario
        self.config = validate_scenario(config)
        self.binary = str(binary)
        self.owner = ProcessOwner(Path(output) / 'traffic')
        self.lock = threading.RLock()
        self.wake, self.halt = threading.Event(), threading.Event()
        self.started, self.second = False, -1
        self.origin_unix = self.origin_mono = None
        self.records, self.events = {}, {}
        self.worker = None
        self.version = ''

    def start(self):
        if self.started or self.owner.closed:
            raise ValueError('Traffic session cannot be restarted')
        self.version = subprocess.check_output([self.binary, '--version'], text=True, timeout=5).splitlines()[0]
        help_text = subprocess.check_output([self.binary, '--help'], text=True, timeout=5)
        require_streaming(self.version, help_text)
        try:
            for d in self.config['traffic_demands']:
                flow_id = d['id']
                self.records[flow_id] = FlowRecords(0.)
                commands = traffic_commands(d, self.config['shaping'], self.binary)
                def receive(line, key=flow_id):
                    with self.lock:
                        self.records[key].receive(line, time.time())
                self.owner.spawn(flow_id + '-receiver', commands['receiver'], receive)
            # Bound readiness checks before the one-second topology clock starts.
            deadline = time.monotonic() + 5
            pending = list(self.config['traffic_demands'])
            while pending:
                for d in pending[:]:
                    self.owner.require_alive(d['id'] + '-receiver')
                    listening = subprocess.check_output(
                        ['ip', 'netns', 'exec', d['destination_gs'], 'ss', '-H', '-ltn',
                         'sport', '=', ':' + str(d['port'])], text=True, timeout=1)
                    if listening.strip():
                        pending.remove(d)
                if time.monotonic() >= deadline:
                    raise ValueError('Receiver readiness timeout')
                if pending:
                    time.sleep(.05)
            self.started = True
            self.worker = threading.Thread(target=self._work, daemon=True)
            self.worker.start()
        except Exception:
            self.owner.close()
            raise

    def advance(self, second, origin_unix=None, origin_mono=None):
        if not self.started or self.halt.is_set():
            raise ValueError('Traffic session is not started')
        with self.lock:
            if self.owner.errors:
                raise ValueError('; '.join(self.owner.errors))
            if self.origin_unix is None:
                self.origin_unix = origin_unix if origin_unix is not None else time.time() - second
                self.origin_mono = origin_mono if origin_mono is not None else time.monotonic() - second
                for records in self.records.values():
                    records.origin_unix = self.origin_unix
            self.second = second
        self.wake.set()

    def _work(self):
        try:
            while not self.halt.is_set():
                self.wake.wait(.05)
                self.wake.clear()
                with self.lock:
                    if self.second < 0:
                        continue
                    second = self.second
                    elapsed = time.monotonic() - self.origin_mono
                    demands = {d['id']: d for d in self.config['traffic_demands']}
                    for action, key in due_actions(self.config, self.events, second):
                        d = demands[key]
                        if action == 'start':
                            commands = traffic_commands(d, self.config['shaping'], self.binary)
                            def probe(line, flow_id=key):
                                with self.lock:
                                    self.records[flow_id].probe(line)
                            self.owner.spawn(key + '-probe', commands['probe'], probe)
                            self.owner.spawn(key + '-sender', commands['sender'])
                            self.events[key] = {'scheduled_start_s': d['start_s'],
                                                'started_s': elapsed,
                                                'start_deviation_s': elapsed - d['start_s']}
                        else:
                            # Let the bounded iperf duration finish and produce its
                            # final receiver record. This small tail is reported.
                            self.events[key]['stopped_s'] = elapsed
                            self.events[key]['scheduled_end_s'] = d['end_s']
                    for key, event in self.events.items():
                        record = self.records[key]
                        sender = self.owner.processes[key + '-sender']
                        receiver = self.owner.processes[key + '-receiver']
                        d = demands[key]
                        if record.complete:
                            event['receiver_end_s'] = record.final['end_s']
                            self.owner.stop(key + '-probe')
                        elif elapsed > d['end_s'] + 5:
                            raise ValueError(f'{key}: missing final receiver record')
                        if sender.poll() not in (None, 0):
                            raise ValueError(f'{key}: sender failed ({sender.returncode})')
                        if receiver.poll() not in (None, 0):
                            raise ValueError(f'{key}: receiver failed ({receiver.returncode})')
                        if sender.poll() == 0 and elapsed < d['end_s'] - 1:
                            raise ValueError(f'{key}: sender exited before scheduled completion')
        except Exception as error:
            self.owner.errors.append(str(error))
            self.halt.set()

    def snapshot(self):
        with self.lock:
            return deepcopy({'iperf_version': self.version, 'origin_unix_s': self.origin_unix,
                             'errors': list(self.owner.errors), 'events': self.events,
                             'flows': {key: {'intervals': record.intervals,
                                             'ping': record.ping_samples(),
                                             'final': record.final, 'complete': record.complete}
                                       for key, record in self.records.items()}})

    def close(self):
        self.halt.set()
        self.wake.set()
        if self.worker:
            self.worker.join(timeout=3)
            if self.worker.is_alive():
                self.owner.errors.append('Traffic scheduler did not stop')
        self.owner.close()
