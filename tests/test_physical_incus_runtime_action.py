"""Workflow-to-installed-client contract; no native runtime or operating grant."""
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

import yaml

ROOT = Path(__file__).resolve().parents[1]
ACTION = ROOT / '.github/actions/run-incus-runtime-profile/action.yml'
CLIENT = '/usr/libexec/lightning-it/incus-runtime-client'


class PhysicalRuntimeActionTests(unittest.TestCase):
    def setUp(self):
        self.action = yaml.safe_load(ACTION.read_text())
        self.steps = self.action['runs']['steps']

    def test_no_candidate_download_engine_command_or_job_selected_endpoint(self):
        self.assertEqual(set(self.action['inputs']), {'profile', 'scenario', 'target', 'target-disposition', 'roles', 'image',
            'instance-type', 'candidate-artifact', 'source-sha', 'junit-required', 'allure-required', 'cpu-limit', 'memory-limit', 'disk-limit'})
        self.assertEqual(self.action['runs']['using'], 'composite')
        self.assertIn(CLIENT + ' check --require-capability initial-auth-idle-v1', self.steps[0]['run'])
        execution = next(step for step in self.steps if step.get('id') == 'cell')
        self.assertIn('exec ' + CLIENT + ' run-profile', execution['run'])
        expected = {'GITHUB_TOKEN': '${{ github.token }}'}
        expected.update({'QUALITY_INPUT_' + name.upper().replace('-', '_'): '${{ inputs.' + name + ' }}'
                         for name in self.action['inputs']})
        self.assertEqual(execution['env'], expected)
        text = json.dumps(self.action)
        for forbidden in ('download-artifact', 'secrets.', 'sudo ', 'docker ', 'podman ', 'incus exec',
                          '--socket', '--config', '--command', '--token', 'continue-on-error'):
            self.assertNotIn(forbidden, text)

    def test_actual_shell_forwards_quoted_locators_without_token_in_argv(self):
        # Replace the one fixed executable literal only in this private test.
        # This does not establish Root installation, real OIDC or Incus evidence.
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)
            program = path / 'client'
            output = path / 'argv.json'
            program.write_text('#!/usr/bin/env python3\nimport json,os,sys\n'
                'from pathlib import Path\n'
                'Path(os.environ["CAPTURE"]).write_text(json.dumps({"argv":sys.argv[1:],'
                '"api_token_present":bool(os.environ.get("GITHUB_TOKEN"))}))\n')
            program.chmod(0o700)
            execution = next(step for step in self.steps if step.get('id') == 'cell')
            script = execution['run'].replace(CLIENT, str(program))
            environment = dict(os.environ, CAPTURE=str(output), GITHUB_TOKEN='synthetic-not-an-api-token',
                               QUALITY_INPUT_PROFILE='heavy', QUALITY_INPUT_SCENARIO='name with spaces; echo unsafe',
                               QUALITY_INPUT_TARGET='ubuntu24')
            result = subprocess.run(['bash', '-c', script], env=environment,
                                    capture_output=True, text=True, timeout=10)
            self.assertEqual(result.returncode, 0, result.stderr)
            captured = json.loads(output.read_text())
            self.assertEqual(captured['argv'], ['run-profile', '--profile', 'heavy', '--scenario',
                                              environment['QUALITY_INPUT_SCENARIO'], '--target', 'ubuntu24'])
            self.assertTrue(captured['api_token_present'])
            self.assertNotIn(environment['GITHUB_TOKEN'], json.dumps(captured['argv']))

    def test_failure_diagnostics_upload_cannot_turn_failed_cell_into_success(self):
        upload = next(step for step in self.steps if step.get('id') == 'upload')
        self.assertIn('always()', upload['if'])
        self.assertIn("steps.cell.outputs.package-directory != ''", upload['if'])
        self.assertEqual(upload['with']['if-no-files-found'], 'error')
        final = self.steps[-1]
        self.assertEqual(final['if'], 'always()')
        for cell, artifact, recorded, state, expected in [
            ('success', 'success', 'success', 'awaiting-native-end', 0),
            ('failure', 'success', 'success', 'awaiting-native-end', 1),
            ('success', 'failure', 'skipped', 'awaiting-native-end', 1),
            ('success', 'success', 'failure', 'awaiting-native-end', 1),
            ('success', 'success', 'success', 'closed', 1),
            ('cancelled', 'skipped', 'skipped', '', 1),
        ]:
            result = subprocess.run(['bash', '-c', final['run']], capture_output=True,
                env=dict(os.environ, CELL_OUTCOME=cell, UPLOAD_OUTCOME=artifact,
                         RECORD_OUTCOME=recorded, EXECUTION_STATE=state), timeout=10)
            self.assertEqual(result.returncode, expected)

    def test_upload_is_bound_to_the_same_cell_before_native_end(self):
        record = next(step for step in self.steps if step.get('id') == 'record-upload')
        self.assertEqual(record['if'], "always() && steps.upload.outcome == 'success'")
        self.assertIn(CLIENT + ' record-upload', record['run'])
        self.assertIn('--artifact-id "$ARTIFACT_ID"', record['run'])
        self.assertIn('--artifact-digest "sha256:$ARTIFACT_DIGEST"', record['run'])
        self.assertEqual(record['env']['ARTIFACT_ID'], '${{ steps.upload.outputs.artifact-id }}')
        self.assertEqual(record['env']['ARTIFACT_DIGEST'], '${{ steps.upload.outputs.artifact-digest }}')


class FinalQualityObserverTests(unittest.TestCase):
    def test_observer_has_only_fixed_read_operation_and_single_receipt_publication(self):
        action = yaml.safe_load((ACTION.parent.parent / 'observe-incus-runtime-profile/action.yml').read_text())
        self.assertEqual(set(action['inputs']), {'profile', 'scenario', 'target'})
        observe = next(step for step in action['runs']['steps'] if step.get('id') == 'observe')
        self.assertIn(CLIENT + ' observe-profile', observe['run'])
        for forbidden in ('run-profile', 'record-upload', 'sudo ', 'continue-on-error', '--lease-id'):
            self.assertNotIn(forbidden, json.dumps(action))
        upload = next(step for step in action['runs']['steps'] if step.get('id') == 'upload')
        self.assertEqual(upload['with']['path'], '${{ steps.observe.outputs.final-quality-receipt }}')
        self.assertEqual(upload['with']['name'], '${{ steps.observe.outputs.final-quality-artifact }}')
        self.assertEqual(upload['with']['if-no-files-found'], 'error')
        final = action['runs']['steps'][-1]
        for outcome, upload_outcome, code in [('success', 'success', 0), ('failure', 'success', 1),
                                               ('success', 'failure', 1), ('skipped', 'skipped', 1)]:
            result = subprocess.run(['bash', '-c', final['run']], check=False,
                env={**os.environ, 'OBSERVE_OUTCOME': outcome, 'UPLOAD_OUTCOME': upload_outcome})
            self.assertEqual(result.returncode, code)


class InitialAuthenticationContractTests(unittest.TestCase):
    RECORD = '{"authentication_idle_seconds":60,"capabilities":["initial-auth-idle-v1"],"frame_seconds":5,"operation":"check","schema":2,"state":"local-prerequisites-only"}'

    def test_all_four_actual_preflights_require_and_validate_the_closed_local_record(self):
        # Execute the actual action shell; only the installed fixed executable is
        # replaced with a private fixture. This never asserts native admission.
        actions = ('run-incus-runtime-profile', 'observe-incus-runtime-profile',
                   'run-operating-drill', 'observe-operating-drill')
        records = (('{"schema":2,"operation":"check","state":"local-prerequisites-only"}', 0, 1),
                   (self.RECORD, 0, 0),
                   (self.RECORD.replace('"frame_seconds":5', '"frame_seconds":60'), 0, 1),
                   (self.RECORD.replace('"authentication_idle_seconds":60', '"authentication_idle_seconds":600'), 0, 1),
                   (self.RECORD.replace('"schema":2', '"schema":true'), 0, 1),
                   (self.RECORD.replace('"capabilities":["initial-auth-idle-v1"]', '"capabilities":[]'), 0, 1),
                   (self.RECORD[:-1] + ',"ready":true}', 0, 1),
                   (self.RECORD[:-1] + ',"schema":2}', 0, 1),
                   (self.RECORD + ' trailing', 0, 1),
                   (self.RECORD, 2, 1), ('', 0, 1))
        for action_name in actions:
            action = yaml.safe_load((ROOT / '.github/actions' / action_name / 'action.yml').read_text())
            script = action['runs']['steps'][0]['run']
            with tempfile.TemporaryDirectory() as directory:
                path = Path(directory)
                client = path / 'client'
                capture = path / 'argv.json'
                client.write_text('#!/usr/bin/env python3\nimport json,os,sys\nfrom pathlib import Path\n'
                    'Path(os.environ["CAPTURE"]).write_text(json.dumps(sys.argv[1:]))\n'
                    'print(os.environ["RECORD"])\nsys.exit(int(os.environ["RESULT"]))\n')
                client.chmod(0o700)
                for record, result, expected in records:
                    with self.subTest(action=action_name, record=record, result=result):
                        outcome = subprocess.run(['bash', '-c', script.replace(CLIENT, str(client))],
                            env=dict(os.environ, CAPTURE=str(capture), RECORD=record, RESULT=str(result)),
                            capture_output=True, text=True, timeout=10)
                        self.assertEqual(outcome.returncode == 0, expected == 0, outcome.stderr)
                        self.assertEqual(json.loads(capture.read_text()),
                            ['check', '--require-capability', 'initial-auth-idle-v1'])
                        if record:
                            self.assertNotIn(record, outcome.stdout)
