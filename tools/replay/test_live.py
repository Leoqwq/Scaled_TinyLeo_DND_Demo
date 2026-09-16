import importlib.util
import unittest
import sys
import json
import threading
import tempfile
import io
import zipfile
import hashlib
from urllib.request import Request, build_opener, ProxyHandler
from urllib.error import HTTPError
urlopen = build_opener(ProxyHandler({})).open
from pathlib import Path


class LiveContractTests(unittest.TestCase):
    def test_live_module_exists(self):
        self.assertTrue(Path(__file__).with_name('live.py').is_file())

    def test_algorithm_and_policy(self):
        from live import policy_from_path, validate_algorithm
        self.assertEqual(policy_from_path([23, 24, 25]), {'[3, 2]->[3, 4]': [[3, 3]]})
        self.assertEqual(validate_algorithm('qos_priority'), 'qos_priority')
        for bad in ('geographic', 'shortest', '; shutdown', None):
            with self.assertRaises(ValueError):
                validate_algorithm(bad)
        with self.assertRaises(ValueError):
            policy_from_path([23, 25])

    def test_loopback_api_access_and_start(self):
        from live_server import server_for
        class Backend:
            def snapshot(self, after):
                return {'status':'ready', 'new_frames':[]}
            def start(self, algorithm):
                from live import validate_algorithm
                return {'algorithm':validate_algorithm(algorithm)}
        server = server_for(Backend(), 'test-token', 0)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        base = f'http://127.0.0.1:{server.server_port}'
        try:
            with self.assertRaises(HTTPError) as error:
                urlopen(base + '/state', timeout=3)
            self.assertEqual(error.exception.code, 403)
            headers = {'X-TinyLEO-Token':'test-token'}
            request = Request(base + '/start', data=b'{"algorithm":"qos_priority"}', headers=headers)
            with urlopen(request, timeout=3) as response:
                self.assertEqual(response.status, 202)
                self.assertEqual(json.load(response)['algorithm'], 'qos_priority')
            request.add_header('Origin', 'https://untrusted.example')
            with self.assertRaises(HTTPError) as error:
                urlopen(request, timeout=3)
            self.assertEqual(error.exception.code, 403)
        finally:
            server.shutdown()
            server.server_close()

    def test_existing_algorithms_receive_actual_adjacency(self):
        from live import RoutingAdapter
        sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'network_orchestrator'))
        states = {
            'A': {'sat_cell':[3,2], 'isls':{'B':[]}},
            'B': {'sat_cell':[3,3], 'isls':{'A':[], 'C':[]}},
            'C': {'sat_cell':[3,4], 'isls':{'B':[]}},
        }
        for mode in ('shortest_path', 'qos_priority'):
            adapter = RoutingAdapter(Path(__file__).with_name('live-routing.json'), mode)
            policy, decision = adapter.choose(states)
            self.assertEqual(decision['path'], [23,24,25])
            self.assertEqual(policy, {'[3, 2]->[3, 4]': [[3,3]]})
            states['B']['isls'].pop('C')
            with self.assertRaises(ValueError):
                adapter.choose(states)
            states['B']['isls']['C'] = []

    def test_archive_download_integrity(self):
        from live_server import Relay
        blob = io.BytesIO()
        with zipfile.ZipFile(blob, 'w') as z:
            z.writestr('replay.json', json.dumps({'schema_version':1, 'modes': {
                'qos_priority': [{'telemetry': {'recorded_unix_s': 1788923013.377}}]}}))
        content = blob.getvalue()
        with tempfile.TemporaryDirectory() as directory:
            relay = Relay.__new__(Relay)
            relay.output = Path(directory)
            relay.lock = threading.Lock()
            relay.state = {}
            relay.request = lambda path: io.BytesIO(content)
            run = {'run_id':'a'*32, 'algorithm':'qos_priority', 'sha256':'0'*64}
            relay.download(run)
            self.assertEqual(relay.state['download'], 'failed')
            self.assertFalse((relay.output / ('a'*32+'.zip')).exists())
            run['sha256'] = hashlib.sha256(content).hexdigest()
            relay.download(run)
            self.assertEqual(relay.state['download'], 'saved')
            target = Path(relay.state['local_archive'])
            self.assertNotEqual(target.parent, relay.output)
            self.assertTrue(target.parent.name.endswith('_qos_priority'))
            self.assertEqual(json.loads(target.with_suffix('.replay.json').read_text())['schema_version'], 1)
            self.assertEqual(len(list(target.parent.iterdir())), 3)
            relay.download(run)
            self.assertEqual(Path(relay.state['local_archive']), target)
            self.assertEqual(len(list(relay.output.iterdir())), 1)

    def test_run_folders_use_recording_time_and_separate_collisions(self):
        from live_server import run_download_directory
        from zoneinfo import ZoneInfo
        replay = {'modes': {'shortest_path': [
            {'telemetry': {'recorded_unix_s': 1788923013.377}}]}}
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            first = run_download_directory(root, 'a'*32, 'shortest_path', replay,
                                           tz=ZoneInfo('America/Vancouver'))
            self.assertEqual(first.name, '2026-09-08_20-03-33_shortest_path')
            first.mkdir()
            (first / ('a'*32 + '.zip')).touch()
            second = run_download_directory(root, 'b'*32, 'shortest_path', replay,
                                            tz=ZoneInfo('America/Vancouver'))
            self.assertNotEqual(first, second)
            self.assertEqual(run_download_directory(root, 'a'*32, 'shortest_path', replay), first)
            with self.assertRaises(ValueError):
                run_download_directory(root, 'a'*32, '../../escape', replay)

    def test_unprepared_session_cannot_start(self):
        from live import Session
        session = Session(Path('/unused'), Path('/unused'), Path('/unused'))
        with self.assertRaises(ValueError):
            session.start('shortest_path')
        self.assertIsNone(session.out)
        self.assertEqual(session.state['status'], 'not_prepared')

    def test_competition_profile_is_explicit_and_legacy_default_is_unchanged(self):
        from live import Session
        from test_competition import candidate
        legacy = Session(Path('/unused'), Path('/unused'), Path('/unused'))
        self.assertIsNone(legacy.competition_config)
        with tempfile.TemporaryDirectory() as directory:
            config = Path(directory) / 'scenario.json'
            config.write_text(json.dumps(candidate()))
            session = Session(Path('/unused'), Path('/unused'), Path('/unused'),
                              competition_scenario=config, iperf_binary='/opt/tinyleo/iperf3')
            self.assertEqual(len(session.competition_config['traffic_demands']), 3)
            profile = session.profile_config({'satellite link bandwidth ("X" Gbps)': 200,
                                              'sat-ground bandwidth ("X" Gbps)': 96})
            self.assertEqual(profile['satellite link bandwidth ("X" Gbps)'], .01)
            self.assertEqual(profile['sat-ground bandwidth ("X" Gbps)'], .1)
            self.assertEqual(legacy.profile_config({'unchanged': True}), {'unchanged': True})


if __name__ == '__main__':
    unittest.main()
