import json
import re
import shutil
import subprocess
import unittest
from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[1]
PROFILE = ROOT / "scripts" / "lit-ci-profile.sh"
PROFILE_COMMAND = "scripts/lit-ci-profile.sh repository-quality"


class CiProfileContractTests(unittest.TestCase):
    def test_push_ready_and_required_jobs_use_one_exact_profile(self):
        config = json.loads(
            (ROOT / ".lit" / "push-ready.json").read_text(encoding="utf-8")
        )
        self.assertEqual(
            [
                {
                    "name": "repository-quality-profile",
                    "command": [
                        "scripts/lit-ci-profile.sh",
                        "repository-quality",
                    ],
                }
            ],
            config["checks"],
        )
        workflow = yaml.safe_load(
            (ROOT / ".github/workflows/repository-quality.yml").read_text(
                encoding="utf-8"
            )
        )
        quality = workflow["jobs"]["quality"]
        self.assertEqual(30, quality["timeout-minutes"])
        self.assertEqual(0, quality["steps"][0]["with"]["fetch-depth"])
        self.assertEqual(
            "develop",
            workflow.get("env", {}).get("AUTHORITATIVE_BASE_BRANCH"),
        )
        self.assertIn(
            "refs/heads/${AUTHORITATIVE_BASE_BRANCH}:"
            "refs/remotes/origin/${AUTHORITATIVE_BASE_BRANCH}",
            quality["steps"][1]["run"],
        )
        self.assertIn(
            'echo "::add-mask::$auth_header"',
            quality["steps"][1]["run"],
        )
        quality_runs = [
            step["run"] for step in quality["steps"] if "run" in step
        ]
        self.assertEqual(PROFILE_COMMAND, quality_runs[-1])

        contracts = yaml.safe_load(
            (ROOT / ".github/workflows/validation-contracts.yml").read_text(
                encoding="utf-8"
            )
        )["jobs"]["contracts"]
        self.assertEqual(30, contracts["timeout-minutes"])
        self.assertEqual(0, contracts["steps"][0]["with"]["fetch-depth"])
        self.assertFalse(
            contracts["steps"][0]["with"]["persist-credentials"]
        )
        self.assertIn(
            "refs/heads/develop:refs/remotes/origin/develop",
            contracts["steps"][1]["run"],
        )
        self.assertIn(
            'echo "::add-mask::$auth_header"',
            contracts["steps"][1]["run"],
        )
        contract_runs = [
            step["run"] for step in contracts["steps"] if "run" in step
        ]
        self.assertEqual(PROFILE_COMMAND, contract_runs[-1])

    def test_profile_is_fail_closed_and_hash_lock_bound(self):
        profile = PROFILE.read_text(encoding="utf-8")
        for contract in (
            'readonly PROFILE_NAME="repository-quality"',
            'WUNDER_DEVTOOLS_DOCKER_SOCKET=disabled',
            'WUNDER_DEVTOOLS_RUN_AS_HOST_UID=1',
            'WUNDER_DEVTOOLS_WORKSPACE_MODE=ro',
            'WUNDER_DEVTOOLS_PRIVILEGED=0',
            'WUNDER_DEVTOOLS_NETWORK="$network_mode"',
            "--require-hashes",
            "requirements-validation.lock",
            ".github/requirements/collection-quality-profile.lock",
            "scripts/lit-push-ready.py instructions",
            "scripts/lit-repository-quality.py",
            "python -m unittest discover",
            "shellcheck",
            "actionlint --version",
            "actionlint",
            'git diff --check "$merge_base"...HEAD --',
        ):
            with self.subTest(contract=contract):
                self.assertIn(contract, profile)
        self.assertNotIn("mapfile", profile)
        self.assertNotIn("readarray", profile)
        self.assertRegex(
            (ROOT / "requirements-validation.lock").read_text(encoding="utf-8"),
            re.compile(r"(?m)^PyYAML==6\.0\.3 \\$"),
        )

    def test_remote_gaps_are_structured_and_unique(self):
        gaps = json.loads(
            (ROOT / ".lit" / "push-ready.json").read_text(encoding="utf-8")
        )["remote_only_checks"]
        self.assertEqual(len(gaps), len({gap["id"] for gap in gaps}))
        for gap in gaps:
            self.assertEqual(
                {"id", "workflow", "job", "reason", "owner"},
                set(gap),
            )

    def test_collection_release_transition_is_an_explicit_noop(self):
        workflow_path = (
            ROOT / ".github/workflows/collection-release-transition.yml"
        )
        workflow = workflow_path.read_text(encoding="utf-8")
        self.assertIn('"mode": "transition-noop"', workflow)
        self.assertIn('"release_eligible": False', workflow)
        self.assertIn('"heavy_executed": False', workflow)
        self.assertIn('"galaxy_publication_executed": False', workflow)
        self.assertIn(
            '[[ "$VERSION" =~ ^[0-9]+\\.[0-9]+\\.[0-9]+'
            '(-[0-9A-Za-z-]+(\\.[0-9A-Za-z-]+)*)?$ ]]',
            workflow,
        )
        workflow_document = yaml.safe_load(workflow)
        publish_lines = [
            line.strip()
            for job in workflow_document["jobs"].values()
            for step in job.get("steps", [])
            for line in step.get("run", "").splitlines()
            if "ansible-galaxy collection publish" in line
        ]
        self.assertEqual(
            [
                'echo "ansible-galaxy collection publish '
                "'${ARTIFACT_NAME}' --server production\""
            ],
            publish_lines,
        )
        self.assertNotIn("collection-quality-profile.yml", workflow)

    def test_collection_release_transition_validates_artifact_names_in_bash(self):
        bash = shutil.which("bash")
        self.assertIsNotNone(bash, "bash is required for workflow contract tests")
        workflow = yaml.safe_load(
            (
                ROOT / ".github/workflows/collection-release-transition.yml"
            ).read_text(encoding="utf-8")
        )
        validation = workflow["jobs"]["transition-noop"]["steps"][0]["run"]
        # Isolate artifact validation from the public repository metadata lookup.
        validation = "gh() { printf '%s\\n' '1103407173'; }\n" + validation
        base_env = {
            "SOURCE_REPOSITORY": "lightning-it/ansible-collection-supplementary",
            "SOURCE_SHA": "f" * 40,
            "ARTIFACT_SHA256": "a" * 64,
            "GITHUB_REPOSITORY_ID": "1269461997",
            "GITHUB_OUTPUT": "/dev/null",
        }

        for version, artifact_name in (
            ("3.2.2", "lit-supplementary-3.2.2.tar.gz"),
            ("3.2.2-rc.1", "lit-supplementary-3.2.2-rc.1.tar.gz"),
        ):
            with self.subTest(version=version, artifact_name=artifact_name):
                completed = subprocess.run(
                    [bash, "-c", validation],
                    check=False,
                    capture_output=True,
                    env={
                        **base_env,
                        "VERSION": version,
                        "ARTIFACT_NAME": artifact_name,
                    },
                    text=True,
                )
                self.assertEqual(0, completed.returncode, completed.stderr)

        for artifact_name in (
            "lit-supplementary-3.2.1.tar.gz",
            "lit-supplementary-extra-3.2.2.tar.gz",
            "../lit-supplementary-3.2.2.tar.gz",
        ):
            with self.subTest(artifact_name=artifact_name):
                completed = subprocess.run(
                    [bash, "-c", validation],
                    check=False,
                    capture_output=True,
                    env={
                        **base_env,
                        "VERSION": "3.2.2",
                        "ARTIFACT_NAME": artifact_name,
                    },
                    text=True,
                )
                self.assertNotEqual(0, completed.returncode)


if __name__ == "__main__":
    unittest.main()
