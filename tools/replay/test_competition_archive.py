from copy import deepcopy
import unittest

from test_competition import candidate


def frames():
    return [{'nodes': {'GS1': [60., -135., 0]}, 'links': [],
             'telemetry': {'epoch': t, 'simulation_time_s': t, 'deadline_missed': False},
             'routing': {'flows': []}} for t in range(301)]


class ArchiveTests(unittest.TestCase):
    def test_physical_hash_ignores_routing_and_run_wall_times(self):
        from competition_archive import physical_digest
        a, b = frames(), frames()
        b[20]['routing'] = {'algorithm': 'qos_priority', 'flows': [{'id': 'bulk'}]}
        b[20]['telemetry']['wall_elapsed_s'] = 20.7
        self.assertEqual(physical_digest(a), physical_digest(b))
        b[20]['nodes']['GS1'][0] = 61.
        self.assertNotEqual(physical_digest(a), physical_digest(b))

    def test_v2_preserves_replay_and_marks_missing_measurements_ineligible(self):
        from competition_archive import build_competition_archive
        data = build_competition_archive('run-a', frames(), candidate(),
            {'flows': {}, 'events': {}, 'errors': []},
            {'runtime_sha256': 'a' * 64}, algorithm='shortest_path',
            boundary={'type': 'Feature', 'geometry': {'type': 'Polygon', 'coordinates': []}})
        self.assertEqual(data['schema_version'], 2)
        self.assertEqual(len(data['modes']['shortest_path']), 301)
        self.assertFalse(data['summary']['measurement_complete'])
        self.assertFalse(data['summary']['comparison_eligible'])
        self.assertEqual(data['source'], 'run-a')
        self.assertEqual(data['scenario'], candidate())

    def test_both_algorithms_share_hashes_but_rate_change_does_not(self):
        from competition_archive import build_competition_archive
        def build(config, algorithm):
            return build_competition_archive('run', frames(), config,
                {'flows': {d['id']: {'complete': True, 'intervals': [{'bytes_received': 1000}],
                                   'final': {'bytes_received': 1000}} for d in config['traffic_demands']},
                 'events': {}, 'errors': [], 'iperf_version': 'iperf 3.20'},
                {'runtime_sha256': 'a' * 64}, algorithm=algorithm, boundary={})
        a = build(candidate(), 'shortest_path')
        b = build(candidate(), 'qos_priority')
        self.assertEqual(a['provenance'], b['provenance'])
        altered = candidate()
        altered['traffic_demands'][0]['demand_gbps'] = .005
        self.assertNotEqual(a['provenance']['scenario_sha256'],
                            build(altered, 'qos_priority')['provenance']['scenario_sha256'])
        self.assertFalse(a['summary']['comparison_eligible'])  # no launch/measurement validation

    def test_failed_or_incomplete_runs_never_qualify(self):
        from competition_archive import build_competition_archive
        for fs, error in [(frames()[:10], None), (frames(), 'receiver died')]:
            data = build_competition_archive('run', fs, candidate(),
                {'flows': {}, 'errors': []}, {}, algorithm='qos_priority', boundary={}, error=error)
            self.assertFalse(data['summary']['comparison_eligible'])


if __name__ == '__main__':
    unittest.main()
