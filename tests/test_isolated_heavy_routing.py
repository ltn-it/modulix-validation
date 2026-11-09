"""Native caller rejection before restricted worker scheduling; no infrastructure mocks."""
from pathlib import Path
import json
import os
import subprocess
import unittest
import yaml

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github/workflows/collection-quality-profile-isolated.yml"


class IsolatedHeavyRoutingTests(unittest.TestCase):
    def setUp(self):
        self.workflow = yaml.safe_load(WORKFLOW.read_text())
        self.contract = self.workflow["jobs"]["validate-inputs"]["steps"][0]["run"]
        self.environment = {
            "PATH": os.environ["PATH"], "PROFILE": "heavy", "MATRIX_JSON": json.dumps({"include": [{
                "allure": True, "component": "fixture", "instance_type": "container", "junit": True,
                "roles": ["fixture"], "runner": ["untrusted-matrix-label"],
                "scenario": "fixture-heavy", "target": "ubuntu24"}]}),
            "SOURCE_REPOSITORY": "ltn-it/ansible-collection-supplementary", "SOURCE_SHA": "a" * 40,
            "ISOLATED_WORKER": "true", "CALLER_REPOSITORY": "ltn-it/modulix-validation",
            "CALLER_REPOSITORY_ID": "1269461997", "CALLER_EVENT": "workflow_dispatch",
            "CALLER_REF": "refs/heads/main", "CALLER_WORKFLOW_REF":
                "ltn-it/modulix-validation/.github/workflows/mlx90-collection-candidate-validation.yml@refs/heads/main",
            "CALLER_ACTOR": "lightning-it-release-automation[bot]", "CALLER_ACTOR_ID": "307565056",
            "CALLER_TRIGGERING_ACTOR": "lightning-it-release-automation[bot]", "CALLER_ATTEMPT": "1",
            "GITHUB_OUTPUT": os.devnull,
        }

    def invoke(self, **changes):
        environment = {**self.environment, **changes}
        return subprocess.run(["bash", "-c", self.contract], env=environment,
                              text=True, capture_output=True, timeout=10).returncode

    def test_actual_contract_admits_main_receiver_and_denies_untrusted_context(self):
        self.assertEqual(self.invoke(), 0)
        for key, value in [("CALLER_EVENT", "pull_request"), ("CALLER_EVENT", "pull_request_target"),
                           ("CALLER_REF", "refs/heads/develop"), ("CALLER_REPOSITORY_ID", "42"),
                           ("CALLER_REPOSITORY", "foreign/fork"), ("CALLER_ACTOR_ID", "42"),
                           ("CALLER_ACTOR", "litroc"), ("CALLER_TRIGGERING_ACTOR", "litroc"),
                           ("CALLER_WORKFLOW_REF", "ltn-it/modulix-validation/.github/workflows/other.yml@refs/heads/main"),
                           ("CALLER_ATTEMPT", "2"), ("SOURCE_SHA", "main")]:
            with self.subTest(key=key, value=value):
                self.assertNotEqual(self.invoke(**{key: value}), 0)

    def test_fixed_group_cannot_be_replaced_by_matrix_runner_or_environment(self):
        jobs = self.workflow["jobs"]
        isolated = jobs["profile-cells"]
        self.assertEqual(isolated["runs-on"], {"group": "lit-pis-prd-isolated",
                         "labels": ["self-hosted", "linux", "x64", "lit-pis", "prd", "isolated",
                                    "${{ format('lit-heavy-{0}-{1}-{2}-{3}', github.run_id, github.run_attempt, inputs.profile, strategy.job-index) }}"]})
        self.assertEqual(isolated["strategy"]["max-parallel"], 1)
        self.assertEqual(isolated["environment"]["name"], "heavy-isolated-pilot")
        self.assertEqual(set(jobs), {"validate-inputs", "profile-cells"})
        self.assertNotIn("if", isolated)
        self.assertEqual(isolated["needs"], "validate-inputs")
        self.assertNotIn("secrets.", json.dumps(isolated))
        self.assertEqual(self.workflow["permissions"], {"contents": "read"})

    def test_validation_caller_cannot_bypass_group_admission_through_legacy_mode(self):
        self.assertNotEqual(self.invoke(ISOLATED_WORKER="false", CALLER_REPOSITORY="ltn-it/fixture"), 0)
        self.assertNotEqual(self.invoke(ISOLATED_WORKER="false", CALLER_EVENT="pull_request"), 0)

    def test_existing_legacy_caller_does_not_acquire_isolated_authority(self):
        legacy = yaml.safe_load((ROOT / ".github/workflows/collection-quality-profile.yml").read_text())
        self.assertNotIn("lit-pis-prd-isolated", json.dumps(legacy))
        self.assertNotIn("if", legacy["jobs"]["profile-cells"])
        contract = legacy["jobs"]["validate-inputs"]["steps"][0]["run"]
        environment = {**self.environment, "CALLER_REPOSITORY": "ltn-it/fixture"}
        result = subprocess.run(["bash", "-c", contract], env=environment, timeout=10)
        self.assertEqual(result.returncode, 0)


if __name__ == "__main__":
    unittest.main()
