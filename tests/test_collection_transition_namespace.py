"""Exercise the actual transition receiver shell without network or acceptance."""
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

import yaml

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / '.github/workflows/collection-release-transition.yml'
COLLECTIONS = {'foundational': 1103405635, 'supplementary': 1103407173,
               'rhel': 1103411913, 'ubuntu': 1268102957,
               'ocp': 1103410706, 'cloud': 1318852819}


class CollectionTransitionNamespaceTests(unittest.TestCase):
    def run_identity(self, repository, identifier, *, target='1269461997', digest='b' * 64):
        workflow = yaml.safe_load(WORKFLOW.read_text())
        step = workflow['jobs']['transition-noop']['steps'][0]
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            gh = root / 'gh'
            gh.write_text('#!/bin/sh\nprintf "%s\\n" "$*" > "$TEST_CALL"\nprintf "%s\\n" "$TEST_REPOSITORY_ID"\n')
            gh.chmod(0o755)
            output = root / 'output'
            call = root / 'call'
            env = {**os.environ, 'PATH': str(root) + os.pathsep + os.environ['PATH'],
                   'SOURCE_REPOSITORY': repository, 'SOURCE_SHA': 'a' * 40,
                   'VERSION': '1.38.0', 'ARTIFACT_SHA256': digest,
                   'ARTIFACT_NAME': 'lit-foundational-1.38.0.tar.gz',
                   'GITHUB_REPOSITORY_ID': target, 'GITHUB_OUTPUT': str(output),
                   'TEST_CALL': str(call), 'TEST_REPOSITORY_ID': str(identifier)}
            result = subprocess.run(['bash', '-c', step['run']], env=env,
                                    capture_output=True, text=True, check=False)
            return result.returncode, output.read_text() if output.exists() else '', call.read_text() if call.exists() else ''

    def test_current_and_historical_names_resolve_to_the_same_fixed_objects(self):
        for owner in ('ltn-it', 'lightning-it'):
            for name, identifier in COLLECTIONS.items():
                repository = f'{owner}/ansible-collection-{name}'
                with self.subTest(repository=repository):
                    code, output, call = self.run_identity(repository, identifier)
                    self.assertEqual(code, 0)
                    self.assertEqual(output, f'repository_id={identifier}\n')
                    self.assertEqual(call, f'api repos/{repository} --jq .id\n')

    def test_reused_name_or_wrong_destination_cannot_produce_transition_evidence(self):
        code, output, _ = self.run_identity('ltn-it/ansible-collection-foundational', 999)
        self.assertNotEqual(code, 0)
        self.assertEqual(output, '')
        code, output, call = self.run_identity('ltn-it/ansible-collection-foundational', 1103405635, target='999')
        self.assertNotEqual(code, 0)
        self.assertEqual((output, call), ('', ''))

    def test_unknown_source_or_malformed_digest_fails_before_metadata_lookup(self):
        for repository, digest in (('foreign/ansible-collection-foundational', 'b' * 64),
                                   ('ltn-it/ansible-collection-unknown', 'b' * 64),
                                   ('ltn-it/ansible-collection-foundational\n', 'b' * 64),
                                   ('ltn-it/ansible-collection-foundational', 'b' * 63)):
            with self.subTest(repository=repository, digest=digest):
                code, output, call = self.run_identity(repository, 1103405635, digest=digest)
                self.assertNotEqual(code, 0)
                self.assertEqual((output, call), ('', ''))

    def test_receiver_preserves_existing_nonreview_runner_and_noop_acceptance_flags(self):
        text = WORKFLOW.read_text()
        workflow = yaml.safe_load(text)
        self.assertEqual(workflow['jobs']['transition-noop']['runs-on'], 'ubuntu-latest')
        for name in ('heavy_executed', 'application_acceptance_executed',
                     'galaxy_publication_executed', 'release_eligible', 'validated'):
            self.assertIn(f'"{name}": False', text)


if __name__ == '__main__':
    unittest.main()
