"""Actual hosted compiler entry for the closed set of exact Source parents.

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
THIRD_FAILED = "3d84e26d90cc778fb8c4f462ce481584da57fb5a"
FOURTH_FAILED = "f138a227d9eee41ea698b1a6f3b9a05f7ae3e18d"
FIFTH_FAILED_WITH_EFFECTS = "8926e7f535f158d4af89e4ac68149ff0b8ab740d"
SIXTH_FAILED_POST_CONTEXT = "086d039c8c58bc91edfeacadf508c207a03a58b5"
SEVENTH_FAILED_NATIVE_EXPIRY = "cfd2e8ca4cbcf58a1a22cf37f2a8336bba19cb85"
EIGHTH_FAILED_CATALOGUE_READER = "8345d447e65609e66eac616afbeb3b5d4bc362be"
NINTH_FAILED_PARTIAL_PREPARATION = "86f3cb46e5856c4066cac14e73f46c3cefb8453e"
TENTH_FAILED_BEFORE_LEASE = "5604f19544f97b572272496fd61f5c4949d45fba"
VERIFIED_CLOSURE = "e403e0fffa9318be82718b29e854ab7a3a6da98c"
PODMAN_REPAIR_BEFORE = "69d2ccf034dfe5c64c0fda8fc037569fc9b96ff6"
CENSUS_HELD_BEFORE = "e42b0cdd65536e3749f6c405ec23955e5aaa419b"
SEALED_INTAKE_BEFORE = "8edd19c61a8faffe10d6c570cc3ad8338750f475"
PARENTS = (HISTORICAL, FOLLOW_UP, PREAUTH_FOLLOW_UP, THIRD_FAILED, FOURTH_FAILED, FIFTH_FAILED_WITH_EFFECTS,
           SIXTH_FAILED_POST_CONTEXT, SEVENTH_FAILED_NATIVE_EXPIRY, EIGHTH_FAILED_CATALOGUE_READER,
           NINTH_FAILED_PARTIAL_PREPARATION, TENTH_FAILED_BEFORE_LEASE, VERIFIED_CLOSURE, PODMAN_REPAIR_BEFORE,
           CENSUS_HELD_BEFORE, SEALED_INTAKE_BEFORE)
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

    def test_third_failed_predecessor_admits_both_actors_and_three_cases(self):
        self.assert_admitted(THIRD_FAILED)

    def test_fourth_failed_predecessor_admits_both_actors_and_three_cases(self):
        self.assert_admitted(FOURTH_FAILED)

    def test_fifth_failed_with_effects_predecessor_admits_both_actors_and_three_cases(self):
        # Scheduling only: Root independently proves cleanup and custody.
        # No no-work classification or same-run retry authority is introduced.
        self.assert_admitted(FIFTH_FAILED_WITH_EFFECTS)

    def test_sixth_failed_post_context_predecessor_admits_both_actors_and_three_cases(self):
        # The previous seven effects are historical; hosted admission grants no
        # retry or Root authority. Fresh retirement/native verification remains mandatory.
        self.assert_admitted(SIXTH_FAILED_POST_CONTEXT)

    def test_seventh_native_expiry_predecessor_admits_both_actors_and_three_cases(self):
        # The original run failed before a lease. This scheduling boundary
        # does not replace Root's native history and preserved catalogue checks.
        self.assert_admitted(SEVENTH_FAILED_NATIVE_EXPIRY)

    def test_eighth_failed_catalogue_reader_parent_admits_both_actors_and_three_cases(self):
        # Hosted scheduling is not a retry, historical qualification, Root
        # authority, or proof that the expired original stage may be adopted.
        self.assert_admitted(EIGHTH_FAILED_CATALOGUE_READER)

    def test_original_prelease_failure_admits_both_actors_and_three_cases(self):
        self.assert_admitted(TENTH_FAILED_BEFORE_LEASE)

    def test_verified_closure_admits_both_actors_and_three_cases(self):
        self.assert_admitted(VERIFIED_CLOSURE)

    def test_podman_repair_parent_admits_both_actors_and_three_cases(self):
        self.assert_admitted(PODMAN_REPAIR_BEFORE)

    def test_census_held_parent_admits_both_actors_and_three_cases(self):
        self.assert_admitted(CENSUS_HELD_BEFORE)

    def test_sealed_intake_parent_admits_both_actors_and_three_cases(self):
        self.assert_admitted(SEALED_INTAKE_BEFORE)

    def test_ninth_partial_preparation_parent_admits_both_actors_and_three_cases(self):
        # Root must separately prove the original retained UNKNOWN and its
        # independent retirement. Hosted admission grants scheduling only.
        self.assert_admitted(NINTH_FAILED_PARTIAL_PREPARATION)

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
        changes += tuple(("CALLER_BEFORE", value) for parent in (THIRD_FAILED, FOURTH_FAILED, FIFTH_FAILED_WITH_EFFECTS,
                                                                     SIXTH_FAILED_POST_CONTEXT,
                                                                     SEVENTH_FAILED_NATIVE_EXPIRY, EIGHTH_FAILED_CATALOGUE_READER,
                                                                     NINTH_FAILED_PARTIAL_PREPARATION, VERIFIED_CLOSURE,
                                                                     PODMAN_REPAIR_BEFORE, SEALED_INTAKE_BEFORE)
                         for value in (parent.upper(), parent[:-1], parent + "0", " " + parent))
        for parent in PARENTS:
            for key, value in changes:
                with self.subTest(parent=parent, key=key, value=value):
                    result = run_entry(operating(parent) | {key: value})
                    self.assertEqual(result.returncode, 2)
                    self.assertEqual(result.stdout, "")
                    self.assertEqual(result.stderr, "Incus admission refused\n")

    def test_business_profiles_keep_the_same_routing_for_all_recorded_parents(self):
        for profile in ("heavy", "application_acceptance"):
            for parent in PARENTS:
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
