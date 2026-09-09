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
            z.writestr('replay.json', '{"schema_version":1}')
        content = blob.getvalue()
        with tempfile.TemporaryDirectory() as directory:
            relay = Relay.__new__(Relay)
            relay.output = Path(directory)
            relay.lock = threading.Lock()
            relay.state = {}
            relay.request = lambda path: io.BytesIO(content)
            run = {'run_id':'a'*32, 'sha256':'0'*64}
            relay.download(run)
            self.assertEqual(relay.state['download'], 'failed')
            self.assertFalse((relay.output / ('a'*32+'.zip')).exists())
            run['sha256'] = hashlib.sha256(content).hexdigest()
            relay.download(run)
            self.assertEqual(relay.state['download'], 'saved')
            self.assertEqual(json.loads((relay.output / ('a'*32+'.replay.json')).read_text()), {'schema_version':1})

    def test_unprepared_session_cannot_start(self):
        from live import Session
        session = Session(Path('/unused'), Path('/unused'), Path('/unused'))
        with self.assertRaises(ValueError):
            session.start('shortest_path')
        self.assertIsNone(session.out)
        self.assertEqual(session.state['status'], 'not_prepared')


if __name__ == '__main__':
    unittest.main()
