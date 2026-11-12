"""Actual hosted compiler entry: three exact Source parents, no generic retry route.

GitHub-provided environment is modeled; no native assignment or Root grant is
asserted. The unchanged Root verifier still independently qualifies every job.
"""
from __future__ import annotations

import subprocess
import sys
import unittest

from test_incus_admission_compiler import ACTION, supplementary_environment

HISTORICAL = "90e7216b5d085ca4ac6238e44dcdbaa51e847d5f"
FOLLOW_UP = "14e3abd5d1fa0cfad14d52ec83483b761de207f0"
PREAUTH_FOLLOW_UP = "f27c1d4edff75377f285275cec9bfec6bc3081f6"
CASES = ("failure", "broker-cancel", "expiry-controller-loss")


def operating(parent, actor="litroc", case="failure"):
    return supplementary_environment(actor=actor) | {
        "PROFILE": "operating",
        "OPERATING_CASE": case,
        "MATRIX_JSON": '{"include":[]}',
        "CALLER_BEFORE": parent,
    }


def run_entry(environment):
    return subprocess.run(
        [sys.executable, "-I", "-B", str(ACTION / "admission.py")],
        env=environment,
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )


class OperatingContinuationEntryTests(unittest.TestCase):
    def assert_admitted(self, parent):
        for actor in ("litroc", "litdeg"):
            for case in CASES:
                with self.subTest(parent=parent, actor=actor, case=case):
                    result = run_entry(operating(parent, actor, case))
                    self.assertEqual(result.returncode, 0, result.stderr)
                    self.assertEqual(result.stderr, "")
                    self.assertEqual(
                        result.stdout,
                        "profile=operating\nmatrix-json={\"include\":[]}\n"
                        "worker-group=lit-pis-prd-supplementary-isolated\n"
                        "operating-case=" + case + "\n",
                    )

    def test_original_parent_still_admits_both_actors_and_three_cases(self):
        self.assert_admitted(HISTORICAL)

    def test_exact_follow_up_parent_admits_both_actors_and_three_cases(self):
        self.assert_admitted(FOLLOW_UP)

    def test_exact_preauth_follow_up_admits_both_actors_and_three_cases(self):
        self.assert_admitted(PREAUTH_FOLLOW_UP)

    def test_follow_up_does_not_admit_neighboring_source_or_native_domains(self):
        changes = (
            ("CALLER_BEFORE", "0" * 40),
            ("CALLER_BEFORE", "f" * 40),
            ("CALLER_BEFORE", ""),
            ("CALLER_BEFORE", FOLLOW_UP.upper()),
            ("CALLER_BEFORE", FOLLOW_UP[:-1]),
            ("CALLER_BEFORE", FOLLOW_UP + "0"),
            ("CALLER_BEFORE", "a" * 40),
            ("CALLER_ATTEMPT", "2"),
            ("CALLER_EVENT", "workflow_dispatch"),
            ("CALLER_EVENT", "pull_request"),
            ("CALLER_EVENT", "pull_request_target"),
            ("CALLER_REF", "refs/heads/develop"),
            ("CALLER_REF_PROTECTED", "false"),
            ("CALLER_REPOSITORY", "ltn-it/modulix-validation"),
            ("CALLER_REPOSITORY_ID", "1269461997"),
            ("CALLER_REPOSITORY_OWNER_ID", "42"),
            ("CALLER_WORKFLOW_REF", "ltn-it/ansible-collection-supplementary/.github/workflows/other.yml@refs/heads/main"),
            ("CALLER_ACTOR", "unknown"),
            ("CALLER_ACTOR_ID", "42"),
            ("CALLER_ACTOR_TYPE", "Bot"),
            ("CALLER_TRIGGERING_ACTOR", "litdeg"),
            ("CALLER_SHA", "b" * 40),
            ("SOURCE_SHA", "b" * 40),
            ("CANDIDATE_ARTIFACT", "collection-candidate-" + "b" * 40),
            ("CPU_LIMIT", "1"),
            ("MEMORY_LIMIT", "2GiB"),
            ("DISK_LIMIT", "6GiB"),
            ("OPERATING_CASE", "other"),
            ("MATRIX_JSON", '{"include":[],"retry":true}'),
        )
        for key, value in changes:
            with self.subTest(key=key, value=value):
                result = run_entry(operating(FOLLOW_UP) | {key: value})
                self.assertEqual(result.returncode, 2)
                self.assertEqual(result.stdout, "")
                self.assertEqual(result.stderr, "Incus admission refused\n")

    def test_business_profiles_keep_the_same_routing_for_all_three_parents(self):
        for profile in ("heavy", "application_acceptance"):
            for parent in (HISTORICAL, FOLLOW_UP, PREAUTH_FOLLOW_UP):
                with self.subTest(profile=profile, parent=parent):
                    result = run_entry(
                        supplementary_environment(profile) | {"CALLER_BEFORE": parent}
                    )
                    self.assertEqual(result.returncode, 0, result.stderr)
                    self.assertIn("profile=" + profile + "\n", result.stdout)
                    self.assertIn(
                        "worker-group=lit-pis-prd-supplementary-isolated\n",
                        result.stdout,
                    )
                    self.assertTrue(result.stdout.endswith("operating-case=\n"))
