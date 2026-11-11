"""Operating cases are a separate exact Source domain, never business coverage."""
import unittest

from test_incus_admission_compiler import ADMISSION, environment, supplementary_environment


def operating_environment(case="failure"):
    return supplementary_environment() | {
        "PROFILE": "operating", "OPERATING_CASE": case, "MATRIX_JSON": '{"include":[]}',
        "CALLER_BEFORE": ADMISSION.OPERATING_BEFORE,
    }


class OperatingAdmissionTests(unittest.TestCase):
    def test_three_cases_are_admitted_without_business_matrix_or_role_claims(self):
        for case in ("failure", "broker-cancel", "expiry-controller-loss"):
            with self.subTest(case=case):
                env = operating_environment(case)
                self.assertEqual(ADMISSION.admit(env), ("operating", '{"include":[]}'))
                self.assertEqual(ADMISSION.operating_case(env), case)
                self.assertEqual(ADMISSION.worker_group(env), "lit-pis-prd-supplementary-isolated")

    def test_case_does_not_weaken_business_or_receiver_admission(self):
        for profile in ("heavy", "application_acceptance"):
            with self.subTest(profile=profile), self.assertRaises(ValueError):
                ADMISSION.admit(supplementary_environment(profile) | {"OPERATING_CASE": "failure"})
        with self.assertRaises(ValueError):
            ADMISSION.admit(environment() | operating_environment() | ADMISSION.CALLER)

    def test_mixed_or_untyped_inputs_cannot_produce_an_operating_job(self):
        for key, value in (
            ("OPERATING_CASE", ""), ("OPERATING_CASE", "other"), ("OPERATING_CASE", True),
            ("MATRIX_JSON", '{"include":[],"case":"failure"}'),
            ("MATRIX_JSON", supplementary_environment()["MATRIX_JSON"]),
            ("CALLER_ATTEMPT", "2"), ("CALLER_EVENT", "workflow_dispatch"),
            ("CALLER_ACTOR_ID", "42"), ("CPU_LIMIT", "1"), ("MEMORY_LIMIT", "2GiB"),
            ("CALLER_BEFORE", "0" * 40), ("CALLER_BEFORE", ""),
            ("DISK_LIMIT", "6GiB"),
        ):
            with self.subTest(key=key, value=value), self.assertRaises(ValueError):
                ADMISSION.admit(operating_environment() | {key: value})

    def test_ordinary_domains_emit_no_operating_case(self):
        self.assertEqual(ADMISSION.operating_case(environment()), "")
        self.assertEqual(ADMISSION.operating_case(supplementary_environment()), "")
