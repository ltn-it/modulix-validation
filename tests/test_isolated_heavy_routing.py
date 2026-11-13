"""Native caller rejection before restricted worker scheduling; no infrastructure mocks."""
from pathlib import Path
import json
import os
import subprocess
import sys
import unittest
import yaml

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github/workflows/collection-quality-profile-isolated.yml"


class IsolatedHeavyRoutingTests(unittest.TestCase):
    def setUp(self):
        self.workflow = yaml.safe_load(WORKFLOW.read_text())
        from test_incus_admission_compiler import environment
        self.environment = {"PATH": os.environ["PATH"], **environment(), "GITHUB_OUTPUT": os.devnull}

    def invoke(self, **changes):
        from test_incus_admission_compiler import ADMISSION
        try:
            ADMISSION.admit({**self.environment, **changes})
        except (ValueError, TypeError):
            return 1
        return 0

    def test_hosted_admission_uses_only_the_immutable_canonical_action(self):
        admission = self.workflow["jobs"]["validate-inputs"]
        self.assertEqual(admission["runs-on"], "ubuntu-latest")
        self.assertEqual(len(admission["steps"]), 1)
        step = admission["steps"][0]
        self.assertEqual(step["uses"],
                         "ltn-it/modulix-validation/.github/actions/admit-incus-profile@83fd5f34b99d379ec4952bfc26243e8856f1e26f")
        self.assertNotIn("run", step)
        self.assertNotIn("env", step)
        action = yaml.safe_load((ROOT / ".github/actions/admit-incus-profile/action.yml").read_text())
        self.assertEqual(set(step["with"]), set(action["inputs"]))
        self.assertEqual(step["with"]["matrix-json"], "${{ inputs['matrix-json'] }}")
        self.assertEqual(admission["outputs"]["matrix-json"], "${{ steps.contract.outputs.matrix-json }}")
        isolated = self.workflow["jobs"]["profile-cells"]
        self.assertEqual(isolated["needs"], "validate-inputs")
        self.assertEqual(isolated["strategy"]["matrix"],
                         "${{ fromJSON(needs.validate-inputs.outputs.matrix-json) }}")
        self.assertNotIn("fromJSON(inputs", str(isolated))
        self.assertNotIn("actions/checkout", str(admission))
        # The compiler/action closure is bound to the actual immutable source.
        for name in ("action.yml", "admission.py", "README.md"):
            path = ".github/actions/admit-incus-profile/" + name
            exact = subprocess.check_output(["git", "show", "83fd5f34b99d379ec4952bfc26243e8856f1e26f:" + path], cwd=ROOT)
            self.assertEqual(exact, (ROOT / path).read_bytes())

    def test_actual_workflow_pin_executes_the_two_recorded_successor_admissions(self):
        from test_operating_continuation import CASES, THIRD_FAILED, FOURTH_FAILED, operating
        step = self.workflow["jobs"]["validate-inputs"]["steps"][0]
        prefix = "ltn-it/modulix-validation/.github/actions/admit-incus-profile@"
        self.assertTrue(step["uses"].startswith(prefix))
        pin = step["uses"][len(prefix):]
        self.assertRegex(pin, r"^[0-9a-f]{40}$")
        subprocess.run(["git", "merge-base", "--is-ancestor", pin, "HEAD"], cwd=ROOT, check=True)
        raw = subprocess.check_output(["git", "show", pin + ":.github/actions/admit-incus-profile/admission.py"], cwd=ROOT)
        self.assertEqual(raw, (ROOT / ".github/actions/admit-incus-profile/admission.py").read_bytes())
        for parent in (THIRD_FAILED, FOURTH_FAILED):
            for actor in ("litroc", "litdeg"):
                for case in CASES:
                    with self.subTest(parent=parent, actor=actor, case=case):
                        result = subprocess.run([sys.executable, "-I", "-B", "-c", raw.decode("utf-8")],
                            env=operating(parent, actor, case), capture_output=True, text=True, timeout=10)
                        self.assertEqual(result.returncode, 0, result.stderr)
                        self.assertEqual(result.stderr, "")
                        self.assertEqual(result.stdout, "profile=operating\nmatrix-json={\"include\":[]}\n"
                            "worker-group=lit-pis-prd-supplementary-isolated\noperating-case=" + case + "\n")

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

    def test_direct_collection_main_uses_the_same_compiled_worker_boundary(self):
        from test_incus_admission_compiler import ADMISSION, supplementary_environment
        for actor in ("litroc", "litdeg"):
            for profile in ("heavy", "application_acceptance"):
                with self.subTest(actor=actor, profile=profile):
                    environment = supplementary_environment(profile, actor)
                    selected, canonical = ADMISSION.admit(environment)
                    self.assertEqual(selected, profile)
                    self.assertEqual(json.loads(canonical), json.loads(environment["MATRIX_JSON"]))
                    for event in ("pull_request", "pull_request_target", "workflow_dispatch"):
                        with self.assertRaises(ValueError):
                            ADMISSION.admit({**environment, "CALLER_EVENT": event})

    def test_fixed_group_cannot_be_replaced_by_matrix_runner_or_environment(self):
        jobs = self.workflow["jobs"]
        isolated = jobs["profile-cells"]
        self.assertEqual(isolated["runs-on"], {"group": "${{ needs.validate-inputs.outputs.worker-group }}",
                         "labels": ["self-hosted", "linux", "x64", "lit-pis", "prd", "isolated", "ciwkr01"]})
        # Routing remains stable across jobs; run identity belongs to owned
        # Incus test VMs and native admission, not a newly registered Runner VM.
        self.assertNotIn("strategy.job-index", str(isolated["runs-on"]))
        self.assertNotIn("github.run_id", str(isolated["runs-on"]))
        self.assertEqual(isolated["strategy"]["max-parallel"], 1)
        self.assertEqual(isolated["environment"]["name"], "heavy-isolated-pilot")
        self.assertEqual(set(jobs), {"validate-inputs", "profile-cells", "profile-results", "operating-cell", "operating-results"})
        self.assertEqual(isolated["if"], "needs.validate-inputs.outputs.profile != 'operating'")
        self.assertEqual(isolated["needs"], "validate-inputs")
        self.assertNotIn("secrets.", json.dumps(isolated))
        self.assertEqual(self.workflow["permissions"], {"contents": "read", "checks": "read"})
        self.assertEqual(isolated["permissions"], {"contents": "read", "checks": "read", "actions": "read", "id-token": "write"})
        self.assertEqual(len(isolated["steps"]), 1)
        action = isolated["steps"][0]
        self.assertRegex(action["uses"], r"^ltn-it/modulix-validation/\.github/actions/run-incus-runtime-profile@[0-9a-f]{40}$")
        self.assertEqual(set(action["with"]), set(yaml.safe_load((ROOT / ".github/actions/run-incus-runtime-profile/action.yml").read_text())["inputs"]))
        self.assertNotIn("actions/checkout", json.dumps(isolated))
        self.assertNotIn("actions/setup-python", json.dumps(isolated))

    def test_final_quality_is_a_distinct_native_job_after_actual_execution(self):
        jobs = self.workflow["jobs"]
        observer = jobs["profile-results"]
        self.assertEqual(observer["needs"], ["validate-inputs", "profile-cells"])
        self.assertEqual(observer["name"],
            "Final quality / ${{ inputs.profile }} / ${{ matrix.scenario }} / ${{ matrix.target }}")
        self.assertEqual(observer["runs-on"], jobs["profile-cells"]["runs-on"])
        self.assertEqual(observer["if"], "always() && needs.validate-inputs.result == 'success' && "
                         "(needs.validate-inputs.outputs.profile == 'heavy' || "
                         "needs.validate-inputs.outputs.profile == 'application_acceptance')")
        self.assertEqual(observer["strategy"]["max-parallel"], 1)
        self.assertEqual(observer["permissions"], {"contents": "read", "checks": "read", "actions": "read", "id-token": "write"})
        step = observer["steps"][0]
        self.assertEqual(step["uses"],
            "ltn-it/modulix-validation/.github/actions/observe-incus-runtime-profile@4126ba6c0c3137d3970f8d26a36f5128ad8fd563")
        self.assertEqual(set(step["with"]), {"profile", "scenario", "target"})
        self.assertEqual(jobs["validate-inputs"]["outputs"]["worker-group"],
            "${{ steps.contract.outputs.worker-group }}")
        for action in ("run-incus-runtime-profile", "observe-incus-runtime-profile"):
            path = ".github/actions/" + action + "/action.yml"
            exact = subprocess.check_output(["git", "show", "4126ba6c0c3137d3970f8d26a36f5128ad8fd563:" + path], cwd=ROOT)
            self.assertEqual(exact, (ROOT / path).read_bytes())

    def test_validation_caller_cannot_bypass_group_admission_through_legacy_mode(self):
        self.assertNotEqual(self.invoke(ISOLATED_WORKER="false", CALLER_REPOSITORY="ltn-it/fixture"), 0)
        self.assertNotEqual(self.invoke(ISOLATED_WORKER="false", CALLER_EVENT="pull_request"), 0)

    def test_operating_cases_have_distinct_native_jobs_and_never_expand_business_matrix(self):
        jobs = self.workflow["jobs"]
        execute, observe = jobs["operating-cell"], jobs["operating-results"]
        self.assertEqual(execute["name"], "Operating custody / ${{ needs.validate-inputs.outputs.operating-case }}")
        self.assertEqual(observe["name"], "Operating result / ${{ needs.validate-inputs.outputs.operating-case }}")
        self.assertEqual(execute["needs"], "validate-inputs")
        self.assertEqual(observe["needs"], ["validate-inputs", "operating-cell"])
        for name, action in (("operating-cell", "run-operating-drill"),
                             ("operating-results", "observe-operating-drill")):
            job = jobs[name]
            expected = "needs.validate-inputs.outputs.profile == 'operating'"
            if name == "operating-results":
                expected = "always() && needs.validate-inputs.result == 'success' && " + expected
            self.assertEqual(job["if"], expected)
            self.assertNotIn("strategy", job)
            self.assertEqual(job["runs-on"], jobs["profile-cells"]["runs-on"])
            self.assertEqual(job["environment"], jobs["profile-cells"]["environment"])
            self.assertFalse(job["concurrency"]["cancel-in-progress"])
            self.assertEqual(job["permissions"], {"contents": "read", "checks": "read", "actions": "read", "id-token": "write"})
            self.assertEqual(len(job["steps"]), 1)
            step = job["steps"][0]
            self.assertEqual(step["with"], {"case": "${{ needs.validate-inputs.outputs.operating-case }}"})
            self.assertEqual(step["uses"], "ltn-it/modulix-validation/.github/actions/" + action +
                             "@4126ba6c0c3137d3970f8d26a36f5128ad8fd563")
            path = ".github/actions/" + action + "/action.yml"
            exact = subprocess.check_output(["git", "show", "4126ba6c0c3137d3970f8d26a36f5128ad8fd563:" + path], cwd=ROOT)
            self.assertEqual(exact, (ROOT / path).read_bytes())
        self.assertEqual(jobs["profile-cells"]["timeout-minutes"], 90)
        inputs = self.workflow["on"]["workflow_call"]["inputs"] if "on" in self.workflow else self.workflow[True]["workflow_call"]["inputs"]
        self.assertEqual([inputs[k]["default"] for k in ("cpu-limit", "memory-limit", "disk-limit")],
                         ["4", "12GiB", "24GiB"])

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
