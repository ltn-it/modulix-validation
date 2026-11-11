"""Actual Thin finalizer boundary, with only Incus effects replaced by a sentinel."""
import importlib.util
import json
import os
import signal
from pathlib import Path
import tempfile
import unittest

import yaml
import test_quality_cancellation as cancellation

ROOT = Path(__file__).resolve().parents[1]
ACTION = ROOT / ".github/actions/run-quality-profile"
SPEC = importlib.util.spec_from_file_location("root_custody_cell", ACTION / "run-cell.py")
CELL = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(CELL)


class RootCustodyTests(unittest.TestCase):
    def test_actual_evidence_step_selects_preliminary_only_for_root_physical_custody(self):
        for physical in (False, True):
            with self.subTest(physical=physical):
                root = Path(self.enterContext(tempfile.TemporaryDirectory()))
                (root / "scripts").mkdir()
                (root / "scripts/quality_evidence.py").write_text(
                    "import json,sys\nfrom pathlib import Path\nPath('argv.json').write_text(json.dumps(sys.argv[1:]))\n"
                )
                actual = yaml.safe_load((ACTION / "profile-steps.yml").read_text())["steps"]
                step = next(s for s in actual if s["id"] == "evidence")
                env = {**os.environ, "QUALITY_TARGET_DISPOSITION": "supported"}
                for name in ("CELL_ROOT", "ARTIFACT_ROOT", "RESULTS_ROOT", "PROFILE", "SCENARIO", "TARGET", "SOURCE_SHA"):
                    env["QUALITY_" + name] = "fixture"
                env["GITHUB_RUN_ATTEMPT"] = "1"
                if physical:
                    env.update(QUALITY_INCUS_RUNTIME_SCHEMA="2", QUALITY_FAILURE_CUSTODY="retain-failed-v1")
                result = CELL.run_steps([step], {}, env, root / "control", root)
                self.assertEqual(result["evidence"]["outputs"]["exit_code"], "0")
                args = json.loads((root / "argv.json").read_text())
                self.assertEqual("--preliminary" in args, physical)

    def test_real_signals_stop_work_and_capture_without_thin_destruction(self):
        for signum in (signal.SIGINT, signal.SIGTERM):
            with self.subTest(signum=signum):
                driver = cancellation.QualityCancellationTests("test_failed_destroy_retains_private_state_after_controller_exit")
                self.addCleanup(driver.doCleanups)
                root, cell, code = driver.exercise_cell(signum=signum, root_custody=True)
                self.assertEqual(code, 128 + signum)
                self.assertTrue((root / "resource").exists())
                self.assertEqual((root / "calls").read_text().splitlines(), ["capture"])
                retained = json.loads((cell / "recovery/context.json").read_text())
                self.assertTrue(retained["cancelled"])
                self.assertFalse(retained["destroy_confirmed"])
                self.assertEqual(retained["status"], "awaiting-root-finalization")

    def exercise(self, *, test_rc=0, evidence_rc=0, directive="retain-failed-v1", tamper=None):
        root = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.last_root = root
        cell = root / "cell"
        cell.mkdir()
        (root / "owned-vm").touch()
        actual = yaml.safe_load((ACTION / "profile-steps.yml").read_text())["steps"]
        destroy = dict(next(s for s in actual if s["id"] == "destroy"))
        # If the actual production finalizer is dispatched, this sentinel is
        # deleted. Root must own that effect after the real native job ends.
        destroy["run"] = 'rm "$FIXTURE_ROOT/owned-vm"; echo exit_code=0 >> "$GITHUB_OUTPUT"'
        lifecycle = next(s for s in actual if s["id"] == "lifecycle")
        init = 'mkdir -p "$FIXTURE_CELL/tmp" "$FIXTURE_CELL/artifacts"; echo QUALITY_RESULT_ARTIFACT=fixture >> "$GITHUB_ENV"'
        if tamper:
            init += '; echo ' + tamper + ' >> "$GITHUB_ENV"'
        steps = [
            {"id": "initialize", "run": init},
            {"id": "molecule", "run": f'echo exit_code={test_rc} >> "$GITHUB_OUTPUT"'},
            {"id": "cleanup", "if": "always()", "run": 'echo exit_code=0 >> "$GITHUB_OUTPUT"'},
            destroy, lifecycle,
            {"id": "evidence", "if": "always()", "run": f'echo exit_code={evidence_rc} >> "$GITHUB_OUTPUT"'},
            {"id": "package", "if": "always()", "run": 'mkdir -p "$FIXTURE_CELL/package"; echo sanitized > "$FIXTURE_CELL/package/evidence"'},
        ]
        environment = {
            **os.environ, "QUALITY_INCUS_RUNTIME_SCHEMA": "2",
            "FIXTURE_ROOT": str(root), "FIXTURE_CELL": str(cell),
            "QUALITY_ARTIFACT_ROOT": str(cell / "artifacts"), "QUALITY_SCENARIO": "fixture",
            "QUALITY_TARGET": "ubuntu-24.04", "GITHUB_RUN_ATTEMPT": "1",
            "QUALITY_LOG_PATH": str(root / "log"),
        }
        if directive is not None:
            environment["QUALITY_FAILURE_CUSTODY"] = directive
        result = CELL.execute_owned_cell(
            steps, {"source-sha": "a" * 40}, environment, root / "control", root, cell,
        )
        return root, cell, result

    def test_actual_controller_defers_successful_destroy_without_claiming_quality_pass(self):
        root, cell, code = self.exercise()
        self.assertEqual(code, 0)
        self.assertTrue((root / "owned-vm").exists())
        result = json.loads((cell / "control/result.json").read_text())
        self.assertTrue(result["execution_success"])
        self.assertFalse(result["success"])
        self.assertEqual(result["root_finalization"], "pending")
        lifecycle = json.loads((cell / "artifacts/configuration/lifecycle-result.json").read_text())
        self.assertIsNone(lifecycle["destroy_exit_code"])
        self.assertEqual(lifecycle["root_finalization"], "pending")
        recovery = json.loads((cell / "recovery/context.json").read_text())
        self.assertFalse(recovery["destroy_confirmed"])

    def test_both_workload_and_post_finalizer_evidence_failure_retain_actual_vm(self):
        for test_rc, evidence_rc in ((19, 0), (0, 23)):
            with self.subTest(test_rc=test_rc, evidence_rc=evidence_rc):
                root, cell, code = self.exercise(test_rc=test_rc, evidence_rc=evidence_rc)
                self.assertEqual(code, 1)
                self.assertTrue((root / "owned-vm").exists())
                result = json.loads((cell / "control/result.json").read_text())
                self.assertFalse(result["success"])
                self.assertFalse(result["execution_success"])

    def test_physical_directive_missing_unknown_or_caller_overridden_fails_closed(self):
        for directive in (None, "destroy", "retain-failed-v2"):
            with self.subTest(directive=directive), self.assertRaises(ValueError):
                self.exercise(directive=directive)
        for tamper in ("QUALITY_FAILURE_CUSTODY=destroy", "QUALITY_INCUS_RUNTIME_SCHEMA=1"):
            with self.subTest(tamper=tamper):
                with self.assertRaises(ValueError):
                    self.exercise(tamper=tamper)
                self.assertTrue((self.last_root / "owned-vm").exists())
                self.assertFalse((self.last_root / "cell/control/result.json").exists())
