import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest

HERE = Path(__file__).resolve().parent


class MeasurementTests(unittest.TestCase):
    def test_receiver_intervals_have_exact_bytes_not_rounded_text(self):
        from traffic import parse_iperf_interval
        lines = (HERE / 'fixtures/iperf320-receiver.jsonl').read_text().splitlines()
        a = parse_iperf_interval(lines[1])
        self.assertEqual(a['bytes_received'], 126000)
        self.assertEqual(a['packets'], 126)
        self.assertEqual(a['lost_packets'], 0)
        self.assertEqual(a['start_s'], 0)
        self.assertEqual(a['end_s'], 1.005056)
        self.assertEqual(a['source'], 'iperf_receiver_interval')
        self.assertIsNone(parse_iperf_interval(lines[0]))
        self.assertIsNone(parse_iperf_interval(lines[-1]))

    def test_sender_or_bad_intervals_are_never_receiver_measurements(self):
        from traffic import parse_iperf_interval
        event = json.loads((HERE / 'fixtures/iperf320-receiver.jsonl').read_text().splitlines()[1])
        event['data']['sum']['sender'] = True
        self.assertIsNone(parse_iperf_interval(json.dumps(event)))
        event['data']['sum']['sender'] = False
        for key, value in [('bytes', -1), ('packets', 1.5), ('seconds', 0),
                           ('lost_packets', 127), ('end', float('nan'))]:
            changed = json.loads(json.dumps(event))
            changed['data']['sum'][key] = value
            with self.subTest(key=key), self.assertRaises(ValueError):
                parse_iperf_interval(json.dumps(changed))
        with self.assertRaises(ValueError):
            parse_iperf_interval('{partial')

    def test_ping_tracks_replies_and_unanswered_sequences(self):
        from traffic import parse_ping
        reply = parse_ping('[1788919000.123456] 64 bytes from ce:2:ce:4:3::3: icmp_seq=7 ttl=61 time=42.5 ms')
        self.assertEqual(reply, {'unix_s': 1788919000.123456, 'sequence': 7, 'rtt_ms': 42.5, 'kind': 'reply'})
        missing = parse_ping('[1788919001.100000] no answer yet for icmp_seq=8')
        self.assertEqual(missing['kind'], 'unanswered')
        self.assertIsNone(missing['rtt_ms'])
        self.assertIsNone(parse_ping('10 packets transmitted, 9 received, 10% packet loss'))

    def test_unsupported_iperf_rejected_before_launch(self):
        from traffic import require_streaming
        require_streaming('iperf 3.20', '--json-stream --timestamps --forceflush')
        for version, help_text in [('iperf 3.9', '--forceflush'), ('iperf 3.17', '--json-stream')]:
            with self.assertRaises(ValueError):
                require_streaming(version, help_text)

    def test_receiver_clock_and_end_record(self):
        from traffic import FlowRecords
        records = FlowRecords(1788919020.0)
        for line in (HERE / 'fixtures/iperf320-receiver.jsonl').read_text().splitlines():
            records.receive(line, 1788919044.)
        self.assertAlmostEqual(records.intervals[0]['start_s'], 20.598, places=5)
        self.assertEqual(records.final['bytes_received'], 251000)
        self.assertEqual(records.final['packets'], 251)
        self.assertTrue(records.complete)
        records.probe('[1788919041.0] no answer yet for icmp_seq=1')
        records.probe('[1788919041.1] 64 bytes from ::1: icmp_seq=1 ttl=64 time=50 ms')
        self.assertEqual(len(records.ping_samples()), 1)
        self.assertEqual(records.ping_samples()[0]['rtt_ms'], 50)


class OwnedProcessTests(unittest.TestCase):
    def test_close_stops_owned_child_only_and_keeps_raw_output(self):
        from traffic import ProcessOwner
        unrelated = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(20)'])
        try:
            with tempfile.TemporaryDirectory() as directory:
                lines = []
                owner = ProcessOwner(Path(directory))
                child = owner.spawn('probe', [sys.executable, '-u', '-c',
                    'import time; print("ready"); time.sleep(20)'], lines.append)
                deadline = time.monotonic() + 3
                while not lines and time.monotonic() < deadline:
                    time.sleep(.01)
                self.assertEqual(lines, ['ready\n'])
                owner.close()
                owner.close()
                self.assertIsNotNone(child.poll())
                self.assertIsNone(unrelated.poll())
                self.assertTrue((Path(directory) / 'probe.log').read_text().startswith('ready\n'))
        finally:
            unrelated.terminate()
            unrelated.wait(timeout=3)

    def test_callback_failure_and_child_exit_are_reported(self):
        from traffic import ProcessOwner
        with tempfile.TemporaryDirectory() as directory:
            owner = ProcessOwner(Path(directory))
            def reject(line):
                raise ValueError('bad receiver record')
            child = owner.spawn('receiver', [sys.executable, '-c', 'print("bad")'], reject)
            child.wait(timeout=3)
            owner.close()
            self.assertIn('bad receiver record', '\n'.join(owner.errors))
            with self.assertRaisesRegex(ValueError, 'exited'):
                owner.require_alive('receiver')

    def test_existing_raw_log_is_not_overwritten_or_spawned_over(self):
        from traffic import ProcessOwner
        with tempfile.TemporaryDirectory() as directory:
            (Path(directory) / 'receiver.log').write_text('old evidence')
            owner = ProcessOwner(Path(directory))
            with self.assertRaises(FileExistsError):
                owner.spawn('receiver', [sys.executable, '-c', 'print("new")'])
            self.assertEqual(owner.processes, {})


class ScheduleTests(unittest.TestCase):
    def test_session_advance_is_nonblocking_and_errors_remain_visible(self):
        from traffic import TrafficSession
        from test_competition import candidate
        with tempfile.TemporaryDirectory() as directory:
            session = TrafficSession(candidate(), Path(directory), '/unused')
            # Before start there are no process side effects, and requests fail closed.
            with self.assertRaisesRegex(ValueError, 'not started'):
                session.advance(0)
            self.assertEqual(session.owner.processes, {})
            session.owner.errors.append('receiver failed')
            self.assertIn('receiver failed', session.snapshot()['errors'])
            session.close()
            session.close()

    def test_command_uses_gs_namespace_real_receiver_and_bounded_udp(self):
        from traffic import traffic_commands
        from test_competition import candidate
        config = candidate()
        commands = traffic_commands(config['traffic_demands'][0], config['shaping'], '/opt/iperf3')
        self.assertEqual(commands['receiver'][:4], ['ip', 'netns', 'exec', 'GS3'])
        self.assertIn('--json-stream', commands['receiver'])
        self.assertIn('ce:2:ce:4:3::3', commands['sender'])
        self.assertEqual(commands['sender'][commands['sender'].index('-b') + 1], '4000000')
        self.assertEqual(commands['sender'][commands['sender'].index('-t') + 1], '270')
        self.assertNotIn('--dscp', commands['sender'])
        self.assertEqual(commands['probe'][:4], ['ip', 'netns', 'exec', 'GS1'])

    def test_schedule_tracks_late_start_and_no_duplicate_launch(self):
        from traffic import due_actions
        from test_competition import candidate
        config = candidate()
        events = {}
        self.assertEqual(due_actions(config, events, 19), [])
        self.assertEqual(due_actions(config, events, 21), [('start', 'c2-north'), ('start', 'telemetry-east')])
        events = {'c2-north': {'started_s': 21}, 'telemetry-east': {'started_s': 21}}
        self.assertEqual(due_actions(config, events, 22), [])
        self.assertEqual(due_actions(config, events, 80), [('start', 'bulk-cross')])
        events['bulk-cross'] = {'started_s': 80}
        self.assertEqual(due_actions(config, events, 240), [('stop', 'bulk-cross')])
        events['bulk-cross']['stopped_s'] = 240
        self.assertEqual(due_actions(config, events, 241), [])


if __name__ == '__main__':
    unittest.main()
