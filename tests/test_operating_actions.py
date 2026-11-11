"""Actual action shells distinguish expected negative assertions from quality."""
import json
import os
from pathlib import Path
import subprocess
import unittest

import yaml

ROOT = Path(__file__).resolve().parents[1]


class OperatingActionTests(unittest.TestCase):
    def test_closed_client_commands_publish_only_operating_metadata(self):
        for action_name, command, state in (
            ("run-operating-drill", "run-operating", "safety-proved-retention-armed"),
            ("observe-operating-drill", "observe-operating", "retained"),
        ):
            with self.subTest(action=action_name):
                action = yaml.safe_load((ROOT / ".github/actions" / action_name / "action.yml").read_text())
                self.assertEqual(set(action["inputs"]), {"case"})
                steps = action["runs"]["steps"]
                call = next(s for s in steps if s.get("id") == "operating")
                self.assertIn("incus-runtime-client " + command + ' --case "$OPERATING_CASE"', call["run"])
                self.assertNotIn("--selector", call["run"])
                self.assertEqual(call["env"]["GITHUB_TOKEN"], "${{ github.token }}")
                upload = next(s for s in steps if s.get("id") == "upload")
                self.assertEqual(upload["with"]["path"], "${{ steps.operating.outputs.operating-receipt }}")
                self.assertEqual(upload["with"]["name"], "${{ steps.operating.outputs.operating-artifact }}")
                self.assertNotIn("continue-on-error", json.dumps(action))
                self.assertNotIn("quality-result", json.dumps(action))
                self.assertNotIn("run-profile", json.dumps(action))
                final = steps[-1]
                for outcome, published, actual_state, expected in (
                    ("success", "success", state, 0), ("failure", "success", state, 1),
                    ("success", "failure", state, 1), ("success", "success", "closed", 1),
                    ("success", "success", "", 1),
                ):
                    result = subprocess.run(["bash", "-c", final["run"]], check=False,
                        env={**os.environ, "OPERATING_OUTCOME": outcome,
                             "UPLOAD_OUTCOME": published, "OPERATING_STATE": actual_state})
                    self.assertEqual(result.returncode, expected)
