"""Closed native identity selects capacity; no caller-selected group."""
import unittest
import os
import subprocess
import sys

from test_incus_admission_compiler import ACTION, ADMISSION, environment, supplementary_environment


class CustodyGroupSelectionTests(unittest.TestCase):
    def test_complete_admitted_domains_select_only_their_owned_group(self):
        self.assertEqual(ADMISSION.worker_group(environment()), "lit-pis-prd-isolated")
        for actor in ("litroc", "litdeg"):
            for profile in ("heavy", "application_acceptance"):
                self.assertEqual(
                    ADMISSION.worker_group(supplementary_environment(profile, actor)),
                    "lit-pis-prd-supplementary-isolated",
                )

    def test_untrusted_or_mixed_domain_cannot_emit_a_group(self):
        original = supplementary_environment()
        for changes in (
            {"CALLER_REPOSITORY_ID": "1269461997"},
            {"CALLER_EVENT": "workflow_dispatch"},
            {"CALLER_REF_PROTECTED": "false"},
            {"CALLER_ACTOR_ID": "307565056"},
            {"MATRIX_JSON": '{"include":[]}'},
        ):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                ADMISSION.worker_group({**original, **changes})

    def test_unbound_group_field_never_selects_capacity(self):
        for group in ("lit-pis-prd-isolated", "foreign-group", ""):
            env = supplementary_environment() | {"RUNNER_GROUP": group}
            self.assertEqual(ADMISSION.worker_group(env), "lit-pis-prd-supplementary-isolated")

    def test_actual_compiler_publishes_group_only_after_complete_admission(self):
        for env, group in (
            (environment(), "lit-pis-prd-isolated"),
            (supplementary_environment(), "lit-pis-prd-supplementary-isolated"),
        ):
            result = subprocess.run(
                [sys.executable, str(ACTION / "admission.py")],
                env={"PATH": os.environ["PATH"], **env},
                capture_output=True, text=True, check=False,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("worker-group=" + group, result.stdout.splitlines())
            denied = subprocess.run(
                [sys.executable, str(ACTION / "admission.py")],
                env={"PATH": os.environ["PATH"], **env, "CALLER_ATTEMPT": "2"},
                capture_output=True, text=True, check=False,
            )
            self.assertEqual(denied.returncode, 2)
            self.assertEqual(denied.stdout, "")
