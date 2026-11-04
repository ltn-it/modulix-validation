"""Exercise real owned finalizers, then the outer upload-output boundary."""
import json
import unittest

import test_quality_cancellation as cancellation
import test_wunder_devtools_tmpfs as contract


class FinalizerPublicationTests(unittest.TestCase):
    def test_real_failed_destroy_cannot_publish_but_confirmed_failure_diagnostics_can(self):
        artifact = "quality-result-fixture-target-" + "c" * 40 + "-attempt-1"
        for confirmed in (False, True):
            with self.subTest(confirmed=confirmed):
                driver = cancellation.QualityCancellationTests("test_failed_destroy_retains_private_state_after_controller_exit")
                self.addCleanup(driver.doCleanups)
                _, cell, code = driver.exercise_cell(signum=None,
                    destroy="success" if confirmed else "failure",
                    normal_failure=confirmed, result_artifact=artifact)
                self.assertEqual(1, code)
                self.assertFalse(json.loads((cell / "control/result.json").read_text())["success"])
                self.assertEqual(not confirmed, (cell / "recovery/context.json").exists())
                fixture = contract.ProtectedIncusContextTests("test_full_context_uses_exact_pinned_sandbox_and_only_two_outputs")
                fixture.setUp()
                self.addCleanup(fixture.doCleanups)
                original = fixture.engine.read_text()
                anchor = "  (state/'control').mkdir(); (state/'package').mkdir()"
                self.assertEqual(1, original.count(anchor))
                # Only emulate the container transport. All finalizer processes,
                # private recovery and result bytes above came from the real driver.
                fixture.engine.write_text(original.replace(anchor,
                    "  import shutil\n"
                    f"  source = pathlib.Path({str(cell)!r})\n"
                    "  for path in source.iterdir():\n"
                    "   shutil.copytree(path, state/path.name) if path.is_dir() else shutil.copy2(path, state/path.name)\n"
                    f"  raise SystemExit({code})\n"))
                result = fixture.invoke()
                self.assertNotEqual(0, result.returncode)
                if confirmed:
                    self.assertEqual(2, len(fixture.output.read_text().splitlines()))
                else:
                    self.assertEqual("", fixture.output.read_text())
                    self.assertTrue((cell / "tmp/state").exists())
                    self.assertTrue((cell / "artifacts/raw").exists())
