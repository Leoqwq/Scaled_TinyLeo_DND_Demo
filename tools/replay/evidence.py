"""Bounded asynchronous kernel-policy and queue/counter evidence collection."""
from copy import deepcopy
import json
from pathlib import Path
import queue
import re
import subprocess
import threading
import time


def evidence_commands(routing, ground_stations):
    nodes = set(ground_stations)
    nodes.update(name for pair in routing.get('gateways', {}).values() for name in pair)
    commands = {}
    for name in sorted(nodes):
        if not re.fullmatch(r'(GS[1-6]|SH1SAT(?:[1-9]|[1-8][0-9]|9[0-6]))', name):
            raise ValueError('Invalid evidence namespace')
        commands[name + '-qdisc'] = ['ip','netns','exec',name,'tc','-j','-s','qdisc','show']
        commands[name + '-links'] = ['ip','-n',name,'-j','-s','link','show']
        if name in ground_stations:
            commands[name + '-routes'] = ['ip','-n',name,'-j','-6','route','show','table','all']
    return commands


class EvidenceCollector:
    def __init__(self, output, ground_stations, runner=subprocess.run):
        self.directory = Path(output) / 'evidence'
        self.directory.mkdir(parents=True, exist_ok=True)
        self.ground_stations, self.runner = ground_stations, runner
        self.jobs = queue.Queue(maxsize=2)
        self.halt = threading.Event()
        self.errors = []
        self.worker = threading.Thread(target=self._work, daemon=True)
        self.worker.start()

    def submit(self, second, routing, reason):
        try:
            self.jobs.put_nowait((second, deepcopy(routing), reason))
        except queue.Full:
            self.errors.append(f'Evidence queue full at t={second}; sample not captured')

    def _work(self):
        while not self.halt.is_set() or not self.jobs.empty():
            try:
                second, routing, reason = self.jobs.get(timeout=.05)
            except queue.Empty:
                continue
            try:
                record = {'requested_simulation_time_s': second, 'reason': reason,
                          'collection_started_unix_s': time.time(), 'routing': routing,
                          'kernel_convergence_certified': False, 'commands': {}}
                for name, argv in evidence_commands(routing, self.ground_stations).items():
                    if self.halt.is_set():
                        record['interrupted'] = True
                        break
                    try:
                        result = self.runner(argv, capture_output=True, text=True, timeout=1)
                        record['commands'][name] = {'argv': argv, 'returncode': result.returncode,
                                                   'stdout': result.stdout, 'stderr': result.stderr}
                    except subprocess.TimeoutExpired:
                        record['commands'][name] = {'argv': argv, 'error': 'timeout'}
                record['collection_finished_unix_s'] = time.time()
                with (self.directory / f'{second}.json').open('x') as stream:
                    json.dump(record, stream, indent=2)
            except Exception as error:
                self.errors.append(f't={second}: {error}')
            finally:
                self.jobs.task_done()

    def close(self):
        # Let normal queued captures complete before stopping. Bound shutdown.
        deadline = time.monotonic() + 5
        while self.jobs.unfinished_tasks and time.monotonic() < deadline:
            time.sleep(.02)
        self.halt.set()
        self.worker.join(timeout=2)
        if self.worker.is_alive():
            self.errors.append('Evidence collector did not stop')
