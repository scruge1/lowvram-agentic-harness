"""Exact selected dependency plans and runtime/browser inventory drift controls."""
import copy
from pathlib import Path
import tempfile
import unittest
from unittest import mock

from harness import home, research_install


class ResearchInstallTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name).resolve()
        self.environment = self.root / 'envs/research'
        self.distributions = []
        for requirement in research_install.REQUIREMENTS:
            name, version = requirement.split('==')
            path = self.environment / ('lib/' + name + '/__init__.py')
            path.parent.mkdir(parents=True)
            path.write_text('# synthetic distribution inventory fixture\n')
            self.distributions.append({'name': name, 'version': version, 'files': [str(path)]})
        for name in ('chromium-1248', 'chromium_headless_shell-1248', 'ffmpeg-1013'):
            path = self.root / 'cache/playwright' / name / 'native-runtime'
            path.parent.mkdir(parents=True)
            path.write_bytes(b'synthetic browser inventory fixture')

    def test_complete_inventory_detects_changed_python_and_browser_bytes(self):
        manifest = research_install.inventory(self.root, self.distributions)
        self.assertEqual(len(manifest['files']), 19)
        self.assertIsNone(research_install.verify(self.root, manifest))
        for name in (self.distributions[0]['files'][0],
                     self.root / 'cache/playwright/chromium_headless_shell-1248/native-runtime'):
            path = Path(name)
            old = path.read_bytes()
            path.write_bytes(old + b'changed')
            self.assertIn('missing or changed', research_install.verify(self.root, manifest))
            path.write_bytes(old)
        self.assertIsNone(research_install.verify(self.root, manifest))
        self.assertEqual(manifest['network_search_acceptance'], 'not_run')

    def test_missing_empty_or_wrong_native_revision_refuses_inventory(self):
        path = self.root / 'cache/playwright/chromium-1248/native-runtime'
        path.unlink()
        with self.assertRaisesRegex(ValueError, 'empty'):
            research_install.inventory(self.root, self.distributions)
        path.parent.rename(path.parent.with_name('chromium-wrong'))
        with self.assertRaisesRegex(ValueError, 'revision is missing'):
            research_install.inventory(self.root, self.distributions)

    def test_distribution_version_missing_record_or_external_file_refuses(self):
        for change in ('version', 'empty', 'external'):
            distributions = copy.deepcopy(self.distributions)
            if change == 'version':
                distributions[0]['version'] = 'unexpected'
            elif change == 'empty':
                distributions[0]['files'] = []
            else:
                external = self.root / 'outside-environment.py'
                external.write_text('retained outside file')
                distributions[0]['files'] = [str(external)]
            with self.assertRaises(ValueError, msg=change):
                research_install.inventory(self.root, distributions)

    def test_cached_manifest_rejects_empty_plan_change_and_path_escape(self):
        manifest = research_install.inventory(self.root, self.distributions)
        for change in ('empty', 'plan', 'escape'):
            modified = copy.deepcopy(manifest)
            if change == 'empty':
                modified['files'] = []
            elif change == 'plan':
                modified['requirements'].pop()
            else:
                modified['files'][0]['path'] = '../external'
            self.assertIsNotNone(research_install.verify(self.root, modified))

    def test_selected_plan_cannot_silently_add_packages_or_change_dependencies(self):
        config = {'profile': 'agent', 'selected_packages': {key: home.PINS[key] for key in home.PROFILES['agent']},
                  'research_requirements': list(research_install.REQUIREMENTS), 'installed': {}}
        self.assertEqual(home.package_plan(config), ('pi', 'hermes', 'mempalace', 'framework', 'research'))
        for field in ('selected_packages', 'research_requirements'):
            modified = copy.deepcopy(config)
            if field == 'selected_packages':
                modified[field].pop('research')
            else:
                modified[field].pop()
            with mock.patch.object(home, 'run', side_effect=AssertionError('Must refuse before child execution')):
                with self.assertRaises(home.HomeError):
                    home.install_packages(self.root, modified)

    def test_minimal_agent_default_keeps_observer_and_labs_explicit(self):
        self.assertEqual(set(home.PROFILES['agent']), {'pi', 'hermes', 'mempalace', 'framework', 'research'})
        self.assertTrue({'harness2', 'bun', 'claude-mem', 'deepseek'} <= set(home.PROFILES['full']))
        self.assertTrue({'harness2', 'bun', 'claude-mem', 'deepseek'}.isdisjoint(home.PROFILES['agent']))


if __name__ == '__main__':
    unittest.main()
