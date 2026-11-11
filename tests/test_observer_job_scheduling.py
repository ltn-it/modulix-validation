"""Exercise actual job guards and admitted matrices with GitHub's default status guard.

The scheduler model covers only the literal boolean/comparison expressions in
this workflow; it does not execute GitHub or grant a Root result.
"""
import ast
import copy
import json
from pathlib import Path
import unittest

import yaml

from test_incus_admission_compiler import ADMISSION, supplementary_environment

ROOT = Path(__file__).resolve().parents[1]


def eligible(job, admission, profile, execution):
    needs = {"validate-inputs": admission,
             "profile-cells": execution, "operating-cell": execution}
    expression = job["if"]
    # GitHub adds success() when no explicit status function is present.
    if "always()" not in expression and any(needs[key] != "success" for key in job["needs"]):
        return False
    expression = expression.replace("always()", "True")
    expression = expression.replace("needs.validate-inputs.result", repr(admission))
    expression = expression.replace("needs.validate-inputs.outputs.profile", repr(profile))
    tree = ast.parse(expression.replace("&&", " and ").replace("||", " or "), mode="eval")

    def value(node):
        if isinstance(node, ast.Expression):
            return value(node.body)
        if isinstance(node, ast.Constant) and type(node.value) in (bool, str):
            return node.value
        if isinstance(node, ast.BoolOp) and isinstance(node.op, (ast.And, ast.Or)):
            values = [value(item) for item in node.values]
            return all(values) if isinstance(node.op, ast.And) else any(values)
        if isinstance(node, ast.Compare) and len(node.ops) == len(node.comparators) == 1:
            if isinstance(node.ops[0], ast.Eq):
                return value(node.left) == value(node.comparators[0])
            if isinstance(node.ops[0], ast.NotEq):
                return value(node.left) != value(node.comparators[0])
        raise AssertionError("unmodeled workflow guard: " + ast.dump(node))

    return value(tree)


class ObserverJobSchedulingTests(unittest.TestCase):
    def setUp(self):
        self.jobs = yaml.safe_load((ROOT / ".github/workflows/collection-quality-profile-isolated.yml").read_text())["jobs"]

    def test_mixed_matrix_failure_keeps_each_original_observer_cell(self):
        execute, observer = self.jobs["profile-cells"], self.jobs["profile-results"]
        self.assertEqual(observer["needs"], ["validate-inputs", "profile-cells"])
        self.assertEqual(observer["strategy"]["matrix"], execute["strategy"]["matrix"])
        self.assertEqual(observer["strategy"]["matrix"], "${{ fromJSON(needs.validate-inputs.outputs.matrix-json) }}")
        self.assertFalse(execute["strategy"]["fail-fast"])
        self.assertFalse(observer["strategy"]["fail-fast"])
        for profile in ("heavy", "application_acceptance"):
            env = supplementary_environment(profile)
            matrix = json.loads(env["MATRIX_JSON"])
            sibling = copy.deepcopy(matrix["include"][0])
            sibling["scenario"] += "-sibling"
            matrix["include"].append(sibling)
            env["MATRIX_JSON"] = json.dumps(matrix)
            admitted, canonical = ADMISSION.admit(env)
            cells = json.loads(canonical)["include"]
            self.assertEqual(len(cells), 2)
            outcomes = {cells[0]["scenario"]: "success", cells[1]["scenario"]: "failure"}
            scheduled = cells if eligible(observer, "success", admitted, "failure") else []
            self.assertEqual(scheduled, cells)
            # Scheduling the read-only observer never rewrites the raw failure.
            self.assertEqual(outcomes[cells[1]["scenario"]], "failure")

    def test_failed_execution_upload_or_cancellation_does_not_suppress_observers(self):
        for name, profile in (("profile-results", "heavy"), ("operating-results", "operating")):
            for reason, result in (("execution", "failure"), ("upload", "failure"), ("cancellation", "cancelled")):
                with self.subTest(job=name, failure=reason):
                    self.assertTrue(eligible(self.jobs[name], "success", profile, result))
                    self.assertEqual(result, "cancelled" if reason == "cancellation" else "failure")
        self.assertEqual(self.jobs["operating-results"]["needs"], ["validate-inputs", "operating-cell"])

    def test_observers_require_successful_admission_and_exact_profile_domain(self):
        for admission in ("failure", "cancelled", "skipped", ""):
            for profile in ("heavy", "application_acceptance", "operating", ""):
                for name in ("profile-results", "operating-results"):
                    self.assertFalse(eligible(self.jobs[name], admission, profile, "failure"))
        for profile in ("", "tiny", "untrusted", "operating"):
            self.assertFalse(eligible(self.jobs["profile-results"], "success", profile, "failure"))
        for profile in ("", "tiny", "heavy", "application_acceptance"):
            self.assertFalse(eligible(self.jobs["operating-results"], "success", profile, "failure"))

    def test_observer_actions_still_propagate_real_verification_and_upload_failure(self):
        for name in ("profile-results", "operating-results"):
            job = self.jobs[name]
            self.assertNotIn("continue-on-error", job)
            self.assertEqual(len(job["steps"]), 1)
            self.assertNotIn("continue-on-error", job["steps"][0])
            self.assertEqual(job["permissions"], {"contents": "read", "checks": "read", "actions": "read", "id-token": "write"})


if __name__ == "__main__":
    unittest.main()
