from __future__ import annotations

import os
import subprocess
import tempfile
import unittest
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
ACTION_DIR = ROOT / ".github/actions/run-quality-profile"
PHASE_SCRIPT = ACTION_DIR / "run-phase.sh"
WORKFLOW = ROOT / ".github/workflows/collection-quality-profile.yml"


class QualityPhaseTimeoutTests(unittest.TestCase):
    def test_hung_test_records_timeout_and_later_phases_still_run(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            subprocess.run(["git", "init", "--quiet", str(root)], check=True, capture_output=True)
            scenario = root / "molecule/fixture/molecule.yml"
            scenario.parent.mkdir(parents=True)
            scenario.write_text("driver: {name: default}\nplatforms: [{name: offline-instance}]\nprovisioner: {name: ansible}\n")
            base = root / ".config/molecule/config.yml"
            base.parent.mkdir(parents=True)
            base.write_text("prerun: false\n")
            bin_directory = root / "bin"
            bin_directory.mkdir()
            molecule = bin_directory / "molecule"
            molecule.write_text(
                "#!/usr/bin/env bash\n"
                "while [ \"$1\" = --base-config ]; do shift 2; done\n"
                "printf '%s\\n' \"$1\" >> \"$MOLECULE_CALLS\"\n"
                "if [ \"$1\" = test ]; then\n"
                "  echo test-started\n"
                "  sleep 30\n"
                "else\n"
                "  echo \"$1-completed\"\n"
                "fi\n",
                encoding="utf-8",
            )
            molecule.chmod(0o755)
            output = root / "outputs"
            log = root / "molecule.log"
            calls = root / "calls"
            env = {
                **os.environ,
                "PATH": f"{bin_directory}:{os.environ['PATH']}",
                "QUALITY_INCUS_PROJECT": "bound-test-project",
                "TMPDIR": directory,
                "QUALITY_SCENARIO": "fixture",
                "QUALITY_LOG_PATH": str(log),
                "GITHUB_OUTPUT": str(output),
                "MOLECULE_CALLS": str(calls),
            }
            for phase, duration in (("test", "1"), ("cleanup", "5"), ("destroy", "5")):
                result = subprocess.run(
                    ["bash", str(PHASE_SCRIPT), phase, duration],
                    env=env,
                    cwd=root,
                    capture_output=True,
                    text=True,
                    timeout=8,
                    check=False,
                )
                self.assertEqual(0, result.returncode, result.stderr)

            self.assertEqual(
                ["exit_code=124", "exit_code=0", "exit_code=0"],
                output.read_text(encoding="utf-8").splitlines(),
            )
            self.assertEqual(
                ["test", "cleanup", "destroy"],
                calls.read_text(encoding="utf-8").splitlines(),
            )
            self.assertIn("cleanup-completed", log.read_text(encoding="utf-8"))
            self.assertIn("destroy-completed", log.read_text(encoding="utf-8"))

    def test_action_gives_test_capture_and_destroy_separate_budgets(self):
        action = yaml.safe_load((ACTION_DIR / "profile-steps.yml").read_text(encoding="utf-8"))
        steps = {step.get("id"): step for step in action["steps"]}
        expected = {"molecule": ("test", 1800), "cleanup": ("cleanup", 600), "destroy": ("destroy", 600)}
        for step_id, (phase, seconds) in expected.items():
            self.assertIn(
                f'run-phase.sh" {phase} {seconds}',
                steps[step_id]["run"],
            )
        self.assertEqual("always()", steps["cleanup"]["if"])
        self.assertEqual("always()", steps["destroy"]["if"])

    def test_profile_job_reserves_time_beyond_bounded_phases(self):
        workflow = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
        job_timeout_seconds = workflow["jobs"]["profile-cells"]["timeout-minutes"] * 60
        phase_timeout_seconds = 1800 + 600 + 600
        kill_grace_seconds = 3 * 30

        self.assertEqual(90 * 60, job_timeout_seconds)
        self.assertEqual(40 * 60, job_timeout_seconds - phase_timeout_seconds)
        self.assertIn(
            "--kill-after=30s",
            PHASE_SCRIPT.read_text(encoding="utf-8"),
        )
        self.assertEqual(
            38 * 60 + 30,
            job_timeout_seconds - phase_timeout_seconds - kill_grace_seconds,
        )


if __name__ == "__main__":
    unittest.main()
