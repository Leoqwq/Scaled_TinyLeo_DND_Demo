"""Behavior tests for the real-flow scenario and physical routing adapter."""
import copy
import json
from pathlib import Path
import tempfile
import unittest
import warnings
import zipfile


HERE = Path(__file__).resolve().parent


def candidate():
    return {
        'schema_version': 1, 'name': 'canada-competition-candidate',
        'grid_config': {'rows': 11, 'cols': 11},
        'shaping': {'isl_gbps': .01, 'gsl_gbps': .1, 'queue_packets': 1000,
                    'udp_payload_bytes': 1000},
        'traffic_demands': [
            dict(id='c2-north', source=12, destination=14, source_gs='GS1',
                 destination_gs='GS3', priority=5, service_class='C2',
                 demand_gbps=.004, start_s=20, end_s=290, port=5201),
            dict(id='telemetry-east', source=13, destination=25, source_gs='GS2',
                 destination_gs='GS6', priority=3, service_class='telemetry',
                 demand_gbps=.002, start_s=20, end_s=290, port=5202),
            dict(id='bulk-cross', source=12, destination=25, source_gs='GS1',
                 destination_gs='GS6', priority=1, service_class='bulk',
                 demand_gbps=.009, start_s=80, end_s=240, port=5203),
        ],
    }


def ladder():
    states = {}
    for cell, count in [(12, 2), (13, 3), (14, 2), (23, 2), (24, 3), (25, 2)]:
        for index in range(count):
            states[f'S{cell}_{index}'] = {'sat_cell': [cell // 11 + 1, cell % 11 + 1], 'isls': {}}
    for a, b in [(12, 13), (13, 14), (23, 24), (24, 25), (12, 23), (13, 24), (14, 25)]:
        states[f'S{a}_0']['isls'][f'S{b}_0'] = []
        states[f'S{b}_0']['isls'][f'S{a}_0'] = []
    return states


class ScenarioTests(unittest.TestCase):
    def test_active_demands_use_half_open_intervals_and_copy_input(self):
        from scenario import active_demands, validate_scenario
        config = candidate()
        original = copy.deepcopy(config)
        checked = validate_scenario(config)
        self.assertEqual(active_demands(checked, 19), [])
        self.assertEqual([d['id'] for d in active_demands(checked, 20)],
                         ['c2-north', 'telemetry-east'])
        self.assertEqual(len(active_demands(checked, 80)), 3)
        self.assertEqual(len(active_demands(checked, 240)), 2)
        self.assertEqual(active_demands(checked, 290), [])
        active_demands(checked, 80)[0]['priority'] = 1
        self.assertEqual(config, original)
        self.assertEqual(checked['traffic_demands'][0]['priority'], 5)

    def test_phase_boundaries(self):
        from scenario import phase_at
        for second, phase in [(0, 'warmup'), (19, 'warmup'), (20, 'baseline'),
                              (79, 'baseline'), (80, 'competition'),
                              (239, 'competition'), (240, 'recovery'),
                              (289, 'recovery'), (290, 'drain'), (300, 'drain')]:
            with self.subTest(second=second):
                self.assertEqual(phase_at(second), phase)
        for invalid in [-1, 301, float('nan'), True]:
            with self.assertRaises(ValueError):
                phase_at(invalid)

    def test_invalid_demand_and_shaping_are_rejected(self):
        from scenario import validate_scenario
        changes = [dict(priority=0), dict(priority=6), dict(priority=True),
                   dict(source_gs='GS4'), dict(source=23), dict(id='bad id'),
                   dict(demand_gbps=0), dict(demand_gbps=float('nan')),
                   dict(demand_gbps=float('inf')), dict(start_s=290),
                   dict(end_s=301), dict(port=22), dict(alpha=100),
                   dict(start_s=20.5)]
        for change in changes:
            config = candidate()
            config['traffic_demands'][0].update(change)
            with self.subTest(change=change), self.assertRaises(ValueError):
                validate_scenario(config)
        for key, value in [('isl_gbps', 0), ('gsl_gbps', -1),
                           ('queue_packets', 0), ('udp_payload_bytes', 65535)]:
            config = candidate()
            config['shaping'][key] = value
            with self.subTest(key=key), self.assertRaises(ValueError):
                validate_scenario(config)

    def test_duplicate_ids_ports_and_reverse_policies_rejected(self):
        from scenario import validate_scenario
        for change in [dict(id='c2-north'), dict(port=5201),
                       dict(source=14, destination=12, source_gs='GS3', destination_gs='GS1')]:
            config = candidate()
            config['traffic_demands'][1].update(change)
            with self.subTest(change=change), self.assertRaises(ValueError):
                validate_scenario(config)

    def test_candidate_file_matches_validated_design(self):
        from scenario import validate_scenario
        data = json.loads((HERE / 'competition-routing.json').read_text())
        checked = validate_scenario(data)
        self.assertEqual([d['demand_gbps'] for d in checked['traffic_demands']],
                         [.004, .002, .009])
        self.assertEqual([d['priority'] for d in checked['traffic_demands']], [5, 3, 1])


class RoutingTests(unittest.TestCase):
    def test_out_of_region_satellites_have_empty_cell_lists(self):
        from competition import PhysicalGraph
        states = ladder()
        states['outside'] = {'sat_cell': [], 'isls': {}}
        graph = PhysicalGraph(states, .01)
        self.assertEqual(sum(graph.density.values()), 14)
        self.assertEqual(graph.capacity(12, 13), .01)

    def test_real_capacity_not_satellite_count(self):
        from competition import PhysicalGraph
        graph = PhysicalGraph(ladder(), .01)
        self.assertEqual(graph.density[13], 3)
        self.assertEqual(graph.capacity(12, 13), .01)
        self.assertEqual(graph.capacity(13, 12), .01)
        self.assertEqual(graph.capacity(12, 25), 0)

    def test_unverified_parallel_or_asymmetric_links_rejected(self):
        from competition import PhysicalGraph
        states = ladder()
        del states['S13_0']['isls']['S12_0']
        with self.assertRaisesRegex(ValueError, 'symmetric'):
            PhysicalGraph(states, .01)
        states = ladder()
        states['S12_1']['isls']['S13_1'] = []
        states['S13_1']['isls']['S12_1'] = []
        with self.assertRaisesRegex(ValueError, 'gateway'):
            PhysicalGraph(states, .01)

    def test_existing_algorithms_produce_distinct_bulk_policies(self):
        from competition import CompetitionRouter
        config = candidate()
        config['traffic_demands'].pop(1)  # two-flow feasibility before telemetry
        before = copy.deepcopy(config)
        shortest = CompetitionRouter(config, 'shortest_path').choose(ladder(), 80)
        qos = CompetitionRouter(config, 'qos_priority').choose(ladder(), 80)
        sp = {d['id']: d for d in shortest['flows']}
        qp = {d['id']: d for d in qos['flows']}
        self.assertEqual(sp['c2-north']['path'], [12, 13, 14])
        self.assertEqual(qp['c2-north']['path'], [12, 13, 14])
        # Existing shortest_path weights density: the middle crossing costs
        # 1.5833 + 1.5 + 1.5833, less than 3 * 1.5833 on the top corridor.
        self.assertEqual(sp['bulk-cross']['path'], [12, 13, 24, 25])
        self.assertEqual(qp['bulk-cross']['path'], [12, 23, 24, 25])
        self.assertFalse(qp['bulk-cross']['qos_status']['used_fallback'])
        self.assertEqual(qos['policy'], {
            '[2, 2]->[2, 4]': [[2, 3]], '[2, 2]->[3, 4]': [[3, 2], [3, 3]]})
        self.assertAlmostEqual(shortest['directed_load_gbps']['12->13'], .013)
        self.assertAlmostEqual(qos['directed_load_gbps']['12->13'], .004)
        self.assertEqual(config, before)

    def test_no_reservations_before_start_and_after_end(self):
        from competition import CompetitionRouter
        router = CompetitionRouter(candidate(), 'qos_priority')
        self.assertEqual(router.choose(ladder(), 0)['flows'], [])
        self.assertEqual(len(router.choose(ladder(), 80)['flows']), 3)
        final = router.choose(ladder(), 300)
        self.assertEqual(final['flows'], [])
        self.assertEqual(final['directed_load_gbps'], {})
        self.assertEqual(final['policy'], {})

    def test_ended_flow_keeps_forwarding_until_receiver_finishes(self):
        from competition import CompetitionRouter, retain_draining_routes
        router=CompetitionRouter(candidate(), 'shortest_path')
        previous=router.choose(ladder(),239)
        current=router.choose(ladder(),240)
        retain_draining_routes(current,previous,{},240)
        self.assertIn('[2, 2]->[3, 4]',current['policy'])
        self.assertEqual([f['id'] for f in current['draining_flows']],['bulk-cross'])
        self.assertNotIn('bulk-cross',[f['id'] for f in current['flows']])
        finished=router.choose(ladder(),241)
        retain_draining_routes(finished,current,{'bulk-cross':True},241)
        self.assertNotIn('[2, 2]->[3, 4]',finished['policy'])

    def test_missing_path_fails_instead_of_reusing_old_policy(self):
        from competition import CompetitionRouter
        router = CompetitionRouter(candidate(), 'qos_priority')
        router.choose(ladder(), 80)
        states = ladder()
        for node in states.values():
            node['isls'] = {}
        with self.assertRaisesRegex(ValueError, 'No physical path'):
            router.choose(states, 81)

    def test_opposite_direction_reservations_are_not_real_contention(self):
        from competition import validate_directions
        with self.assertRaisesRegex(ValueError, 'opposite'):
            validate_directions([{'path': [12, 13, 14]}, {'path': [25, 14, 13]}])
        validate_directions([{'path': [12, 13, 14]}, {'path': [13, 14, 25]}])

    def test_unknown_algorithm_rejected(self):
        from competition import CompetitionRouter
        with self.assertRaises(ValueError):
            CompetitionRouter(candidate(), 'geographic')


class FeasibilityTests(unittest.TestCase):
    def make_archive(self, path, epochs=range(301), duplicate=False):
        with zipfile.ZipFile(path, 'w', zipfile.ZIP_DEFLATED) as archive:
            payload = json.dumps(ladder())
            for epoch in epochs:
                archive.writestr(f'snapshots/{epoch}.json', payload)
            if duplicate:
                with warnings.catch_warnings():
                    warnings.simplefilter('ignore', UserWarning)
                    archive.writestr('snapshots/0.json', payload)

    def test_thresholds_use_fixed_competition_denominator(self):
        from check_competition import gate_result
        self.assertTrue(gate_result(160, 128, 80, 1, 0)['passed'])
        self.assertFalse(gate_result(160, 127, 80, 1, 0)['passed'])
        self.assertFalse(gate_result(160, 128, 79, 1, 0)['passed'])
        self.assertFalse(gate_result(160, 128, 80, 1, 1)['passed'])
        self.assertFalse(gate_result(160, 128, 80, 0, 0)['passed'])

    def test_complete_fixture_proves_only_model_feasibility(self):
        from check_competition import check_archive
        config = candidate()
        config['traffic_demands'].pop(1)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'input.zip'
            self.make_archive(path)
            report = check_archive(path, config)
        self.assertEqual(report['evaluated_epochs'], 301)
        self.assertEqual(report['competition_epochs'], 160)
        self.assertEqual(report['lower_priority_difference_epochs'], 160)
        self.assertEqual(report['alternate_corridor_epochs'], 160)
        self.assertEqual(report['relieved_bottleneck_epochs'], 160)
        self.assertTrue(report['gate']['passed'])
        self.assertFalse(report['real_performance_validated'])
        self.assertEqual(len(report['frames']), 301)
        self.assertEqual(report['frames'][80]['decisions']['shortest_path']['flows'][1]['path'],
                         [12, 13, 24, 25])

    def test_missing_and_duplicate_epochs_rejected(self):
        from check_competition import check_archive
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'input.zip'
            self.make_archive(path, range(300))
            with self.assertRaisesRegex(ValueError, '301'):
                check_archive(path, candidate())
            self.make_archive(path, duplicate=True)
            with self.assertRaisesRegex(ValueError, 'Duplicate'):
                check_archive(path, candidate())

    def test_bad_physical_epoch_recorded_and_blocks_gate(self):
        from check_competition import check_archive
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'input.zip'
            with zipfile.ZipFile(path, 'w', zipfile.ZIP_DEFLATED) as archive:
                for epoch in range(301):
                    state = ladder()
                    if epoch == 80:
                        del state['S12_0']['isls']['S13_0']
                    archive.writestr(f'snapshots/{epoch}.json', json.dumps(state))
            report = check_archive(path, candidate())
        self.assertFalse(report['gate']['passed'])
        self.assertEqual(report['error_epochs'], 1)
        self.assertIn('symmetric', report['frames'][80]['error'])


if __name__ == '__main__':
    unittest.main()
