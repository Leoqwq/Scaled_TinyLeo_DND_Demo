import json
from pathlib import Path
import tempfile
import unittest


class EvidenceTests(unittest.TestCase):
    def test_evidence_commands_are_readonly_scoped_to_involved_nodes(self):
        from evidence import evidence_commands
        routes = {'gateways': {'12<->13': ['SH1SAT1','SH1SAT2']}}
        commands = evidence_commands(routes, ['GS1','GS3'])
        self.assertIn(['ip','-n','GS1','-j','-6','route','show','table','all'],commands.values())
        self.assertIn(['ip','netns','exec','SH1SAT1','tc','-j','-s','qdisc','show'],commands.values())
        self.assertFalse(any('SH1SAT96' in argv for argv in commands.values()))
        self.assertFalse(any('change' in argv or 'replace' in argv for argv in commands.values()))

    def test_collector_preserves_errors_without_claiming_convergence(self):
        from evidence import EvidenceCollector
        class Completed:
            returncode = 1
            stdout = ''
            stderr = 'namespace unavailable'
        with tempfile.TemporaryDirectory() as directory:
            collector=EvidenceCollector(Path(directory), ['GS1'], runner=lambda argv,**kw:Completed())
            collector.submit(80, {'gateways':{},'policy':{'x':[]}}, 'phase')
            collector.close()
            data=json.loads((Path(directory)/'evidence/80.json').read_text())
            self.assertFalse(data['kernel_convergence_certified'])
            self.assertEqual(data['requested_simulation_time_s'],80)
            self.assertTrue(any(v['returncode']==1 for v in data['commands'].values()))


if __name__=='__main__':unittest.main()
