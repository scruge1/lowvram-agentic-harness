"""Runtime journals retain stage identity and block unresolved update work."""
import json
from pathlib import Path
import tempfile
import unittest

from harness import maintenance


class MaintenanceHistoryTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.home = Path(self.temporary.name).resolve()
        self.operation = self.home / 'state/updates/source-a'
        self.operation.mkdir(parents=True)
        self.admission = self.operation / 'admission.json'
        self.admission.write_text(json.dumps({'schema': maintenance.SCHEMA, 'status': 'staged_not_active'}))
        self.original = self.admission.read_bytes()
        self.sidecar = {'schema': 'agent-home-runtime-update/v1', 'home': str(self.home),
                        'operation': self.operation.name, 'stage_receipt_sha256': maintenance.digest(self.admission),
                        'status': 'accepted'}

    def write(self, value):
        (self.operation / 'runtime-update.json').write_text(json.dumps(value))

    def test_only_exact_bound_terminal_history_permits_next_stage(self):
        self.assertTrue(maintenance.pending_operations(self.home))
        for status in ('accepted', 'rolled_back', 'recovered_predecessor'):
            self.write({**self.sidecar, 'status': status})
            self.assertEqual(maintenance.pending_operations(self.home), [])
            self.assertEqual(self.admission.read_bytes(), self.original)

    def test_terminal_label_with_foreign_or_changed_binding_stays_pending(self):
        for key, value in (('home', str(self.home / 'foreign')), ('operation', 'foreign'),
                           ('stage_receipt_sha256', '0' * 64), ('schema', 'unknown')):
            with self.subTest(field=key):
                self.write({**self.sidecar, key: value})
                self.assertTrue(maintenance.pending_operations(self.home))
        self.write(self.sidecar)
        self.admission.write_bytes(self.original + b' ')
        self.assertTrue(maintenance.pending_operations(self.home))

    def test_unaccepted_or_incomplete_generation_is_not_retired_as_history(self):
        statuses = ('activation_incomplete', 'rollback_incomplete', 'activated_pending_consumer_acceptance',
                    'consumer_verification_failed', 'recovered_pending_consumer_acceptance',
                    'rolled_back_pending_consumer_acceptance', 'unknown')
        for status in statuses:
            with self.subTest(status=status):
                self.write({**self.sidecar, 'status': status})
                self.assertTrue(maintenance.pending_operations(self.home))

    def test_damaged_and_wrong_shape_journals_stay_pending(self):
        for value in (None, [], {}, 'unexpected'):
            self.write(value)
            self.assertTrue(maintenance.pending_operations(self.home))
        (self.operation / 'runtime-update.json').write_text('{')
        self.assertTrue(maintenance.pending_operations(self.home))

    def test_pending_activation_presence_blocks_even_with_terminal_history(self):
        self.write(self.sidecar)
        pending = self.home / 'state/updates/pending-activation.json'
        pending.write_text('{')
        self.assertIn('pending activation requires recovery', maintenance.pending_operations(self.home))


if __name__ == '__main__':
    unittest.main()
