"""Native caller rejection before restricted worker scheduling; no infrastructure mocks."""
from pathlib import Path
import ast
import json
import os
import subprocess
import tempfile
import unittest
import yaml

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github/workflows/collection-quality-profile-isolated.yml"


class IsolatedHeavyRoutingTests(unittest.TestCase):
    def setUp(self):
        self.workflow = yaml.safe_load(WORKFLOW.read_text())
        self.launcher = self.workflow["jobs"]["validate-inputs"]["steps"][0]["run"]
        self.contract = self.launcher.split("<<'CONTRACT'\n", 1)[1].removesuffix("CONTRACT\n")
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

    def test_hosted_admission_uses_exact_central_pinned_offline_container(self):
        # Observe the actual dispatcher argv without requiring an inner daemon.
        # Semantic contract tests below execute within the outer pinned test EE.
        tree = ast.parse((ROOT / "scripts/lit-push-ready.py").read_text())
        image = next(ast.literal_eval(node.value) for node in tree.body
                     if isinstance(node, ast.Assign)
                     and any(isinstance(target, ast.Name) and target.id == "COPILOT_DEVTOOL_IMAGE"
                             for target in node.targets))
        forwarded = ["PROFILE", "MATRIX_JSON", "CALLER_REPOSITORY", "SOURCE_REPOSITORY", "SOURCE_SHA",
                     "CALLER_REPOSITORY_ID", "CALLER_EVENT", "CALLER_REF", "CALLER_WORKFLOW_REF",
                     "CALLER_ACTOR", "CALLER_ACTOR_ID", "CALLER_TRIGGERING_ACTOR", "CALLER_ATTEMPT"]
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            environment = {**self.environment, "GITHUB_OUTPUT": str(root / "outputs"),
                           "ADMISSION_ARGV": str(root / "argv"), "ADMISSION_STDIN": str(root / "stdin")}
            harness = """
docker() {
    printf '%s\\n' "$@" > "$ADMISSION_ARGV"
    cat > "$ADMISSION_STDIN"
}
export -f docker
exec bash -c "$1"
"""
            result = subprocess.run(["bash", "-c", harness, "admission-test", self.launcher],
                                    env=environment, text=True, capture_output=True, timeout=10)
            self.assertEqual(result.returncode, 0, result.stderr)
            expected = ["run", "--rm", "--interactive", "--entrypoint", "", "--read-only", "--network", "none",
                        "--user", "1000:1000", "--cap-drop", "ALL", "--security-opt", "no-new-privileges=true",
                        "--pids-limit", "128", "--tmpfs", "/tmp:rw,nosuid,nodev,noexec,size=64m"]
            for name in forwarded:
                expected.extend(["-e", name])
            expected.extend([image, "bash", "-euo", "pipefail", "-s"])
            self.assertEqual((root / "argv").read_text().splitlines(), expected)
            self.assertEqual((root / "stdin").read_text(), self.contract)
        admission = self.workflow["jobs"]["validate-inputs"]
        self.assertEqual(admission["runs-on"], "ubuntu-latest")
        self.assertEqual(len(admission["steps"]), 1)
        self.assertEqual(self.workflow["jobs"]["profile-cells"]["needs"], "validate-inputs")
        # The host segment contains no language validator or checkout before admission.
        host = self.launcher.split("<<'CONTRACT'\n", 1)[0]
        self.assertNotIn("python", host)
        self.assertNotIn("actions/checkout", str(admission))

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
                         "labels": ["self-hosted", "linux", "x64", "lit-pis", "prd", "isolated", "ciwkr01"]})
        # Routing remains stable across jobs; run identity belongs to owned
        # Incus test VMs and native admission, not a newly registered Runner VM.
        self.assertNotIn("strategy.job-index", str(isolated["runs-on"]))
        self.assertNotIn("github.run_id", str(isolated["runs-on"]))
        self.assertEqual(isolated["strategy"]["max-parallel"], 1)
        self.assertEqual(isolated["environment"]["name"], "heavy-isolated-pilot")
        self.assertEqual(set(jobs), {"validate-inputs", "profile-cells"})
        self.assertNotIn("if", isolated)
        self.assertEqual(isolated["needs"], "validate-inputs")
        self.assertNotIn("secrets.", json.dumps(isolated))
        self.assertEqual(self.workflow["permissions"], {"contents": "read"})
        self.assertEqual(isolated["permissions"], {"contents": "read", "actions": "read", "id-token": "write"})
        self.assertEqual(len(isolated["steps"]), 1)
        action = isolated["steps"][0]
        self.assertRegex(action["uses"], r"^ltn-it/modulix-validation/\.github/actions/run-incus-runtime-profile@[0-9a-f]{40}$")
        self.assertEqual(set(action["with"]), set(yaml.safe_load((ROOT / ".github/actions/run-incus-runtime-profile/action.yml").read_text())["inputs"]))
        self.assertNotIn("actions/checkout", json.dumps(isolated))
        self.assertNotIn("actions/setup-python", json.dumps(isolated))

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
