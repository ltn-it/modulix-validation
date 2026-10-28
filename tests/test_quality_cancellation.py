from __future__ import annotations

import importlib.util
import json
import os
import secrets
import shlex
import shutil
import signal
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DRIVER = ROOT / ".github/actions/run-quality-profile/run-cell.py"


class QualityCancellationTests(unittest.TestCase):
    def test_recovery_never_replaces_existing_data_or_follows_a_symlink(self):
        spec = importlib.util.spec_from_file_location("cell", DRIVER)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        for symlink in (False, True):
            with self.subTest(symlink=symlink), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                cell = root / "cell"
                (cell / "tmp").mkdir(parents=True)
                state = cell / "tmp/state"
                state.write_text("preserved-owned-state")
                outside = root / "existing"
                outside.mkdir()
                marker = outside / "context.json"
                marker.write_text("existing-recovery-not-this-operation")
                if symlink:
                    (cell / "recovery").symlink_to(outside, target_is_directory=True)
                else:
                    (cell / "recovery").mkdir()
                    (cell / "recovery/context.json").write_text("existing-private-state")
                with self.assertRaises(FileExistsError):
                    module.finish_owned_state(cell, {}, {}, {}, cancelled=True)
                self.assertEqual("preserved-owned-state", state.read_text())
                self.assertEqual("existing-recovery-not-this-operation", marker.read_text())
                if not symlink:
                    self.assertEqual("existing-private-state", (cell / "recovery/context.json").read_text())

    def test_existing_wrapper_keeps_failed_runtime_cell_without_public_outputs(self):
        import test_wunder_devtools_tmpfs as contract

        fixture = contract.ProtectedIncusContextTests("test_full_context_uses_exact_pinned_sandbox_and_only_two_outputs")
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        original = fixture.engine.read_text()
        anchor = "  (state/'control').mkdir(); (state/'package').mkdir()"
        self.assertEqual(1, original.count(anchor))
        fixture.engine.write_text(original.replace(
            anchor,
            "  (state/'tmp').mkdir(mode=0o700); (state/'tmp/state').write_text('private-owned-state')\n"
            "  (state/'recovery').mkdir(mode=0o700)\n"
            "  (state/'recovery/context.json').write_text('private-fixture-context')\n"
            "  raise SystemExit(130)",
        ))
        result = fixture.invoke()
        self.assertNotEqual(0, result.returncode)
        self.assertEqual("", fixture.output.read_text())
        cells = list(fixture.recovery.glob("quality-cell.*"))
        self.assertEqual(1, len(cells))
        self.assertFalse(cells[0].is_relative_to(fixture.runtime))
        shutil.rmtree(fixture.runtime)
        self.assertEqual("private-owned-state", (cells[0] / "tmp/state").read_text())
        self.assertTrue((cells[0] / "recovery/context.json").is_file())
        self.assertFalse((cells[0] / "package").exists())

    def exercise_cell(self, *, signum=signal.SIGINT, before_state=False,
                      destroy="success", repeat=False, interrupt_destroy=False,
                      damaged_environment=False, normal_failure=False,
                      repeat_during_stop=False, interrupt_capture=False,
                      interrupt_after_destroy=False, unowned_finalizer=False):
        root = Path(self.enterContext(tempfile.TemporaryDirectory()))
        cell = root / "cell"
        cell.mkdir(mode=0o700)
        (root / "foreign-resource").write_text("unrelated fixture; never owned")
        active = (
            "import json,os,pathlib,subprocess,sys,time; "
            "child=subprocess.Popen([sys.executable,'-c',"
            "'import signal,time; signal.signal(signal.SIGTERM,signal.SIG_IGN); time.sleep(60)'],"
            "stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL); "
            "pids=[os.getpid(),child.pid]; "
            "data={'pids':pids,'birth':[pathlib.Path('/proc',str(p),'stat').read_text().split()[21] for p in pids]}; "
            "pathlib.Path(os.environ['FIXTURE_ROOT'],'pids.jsonl').open('a').write(json.dumps(data)+'\\n'); "
            "pathlib.Path(os.environ['FIXTURE_ROOT'],'active').touch(); time.sleep(60)"
        )
        active_command = f"python3 -c {shlex.quote(active)}"
        if repeat_during_stop:
            active_command = "trap '' TERM; " + active_command
        # Generate a fresh fixture value; no credential-shaped literal is committed.
        self.command_canary = secrets.token_hex(24)
        command_assignment = shlex.quote("KEYCLOAK_TEST_PASSWORD=" + self.command_canary)
        initialize = (
            f'echo {command_assignment} >> "$GITHUB_ENV"; '
            'echo QUALITY_RESULT_ARTIFACT=fixture-result >> "$GITHUB_ENV"; '
        )
        if before_state:
            initialize += active_command
        else:
            initialize += ('mkdir -p "$FIXTURE_CELL/tmp" "$FIXTURE_CELL/artifacts"; '
                           'echo opaque-owned-state > "$FIXTURE_CELL/tmp/state"; '
                           'echo raw-diagnostic > "$FIXTURE_CELL/artifacts/raw"; '
                           'echo owned > "$FIXTURE_ROOT/resource"')
        capture = ('test "$(cat "$FIXTURE_ROOT/resource")" = owned; '
                   'echo capture >> "$FIXTURE_ROOT/calls"; ')
        if repeat:
            capture += 'touch "$FIXTURE_ROOT/capture-ready"; sleep 0.5; '
        capture += 'echo exit_code=0 >> "$GITHUB_OUTPUT"'
        if interrupt_capture:
            capture = active_command
        destroy_command = ('test "$(cat "$FIXTURE_ROOT/resource")" = owned; '
                           'echo destroy >> "$FIXTURE_ROOT/calls"; ')
        if destroy == "timeout" or interrupt_destroy:
            destroy_command += 'rm -f "$FIXTURE_ROOT/active"; ' + active_command
        elif destroy == "failure":
            destroy_command += 'echo exit_code=19 >> "$GITHUB_OUTPUT"'
        else:
            destroy_command += 'rm "$FIXTURE_ROOT/resource"; echo exit_code=0 >> "$GITHUB_OUTPUT"'
        molecule = ('echo exit_code=1 >> "$GITHUB_OUTPUT"' if normal_failure else
                    'echo exit_code=0 >> "$GITHUB_OUTPUT"')
        if (signum is not None and not before_state and not interrupt_destroy
                and not interrupt_capture and not interrupt_after_destroy):
            molecule = active_command
        if damaged_environment:
            molecule = 'echo PATH=/untrusted >> "$GITHUB_ENV"; ' + molecule
        steps = [
            {"id": "initialize", "run": initialize},
            {"id": "molecule", "run": molecule},
            {"id": "cleanup", "if": "always()", "run": capture},
            {"id": "destroy", "if": "always()", "run": destroy_command},
            {"id": "evidence", "if": "always()", "run": 'echo exit_code=0 >> "$GITHUB_OUTPUT"'},
            {"id": "package", "if": "always()", "run":
             'mkdir -p "$FIXTURE_CELL/package"; echo redacted > "$FIXTURE_CELL/package/evidence"'},
        ]
        if interrupt_after_destroy:
            steps[4]["run"] = active_command
        if unowned_finalizer:
            steps.insert(4, {"id": "unowned", "if": "always()",
                             "run": 'touch "$FIXTURE_ROOT/unowned-effect"'})
        inputs = {"source-sha": "c" * 40, "scenario": "fixture", "target": "target", "profile": "heavy"}
        program = (
            "import importlib.util,os,pathlib\n"
            "os.umask(0o077)\n"
            f"s=importlib.util.spec_from_file_location('cell',{str(DRIVER)!r})\n"
            "m=importlib.util.module_from_spec(s); s.loader.exec_module(m)\n"
            f"m.CANCEL_FINALIZER_SECONDS={2 if repeat else 0.5}\n"
            "m.PROCESS_STOP_SECONDS=0.1\n"
            f"root=pathlib.Path({str(root)!r})\n"
            f"raise SystemExit(m.execute_owned_cell({steps!r},{inputs!r},dict(os.environ),"
            "root/'ram-control',root,root/'cell'))\n"
        )
        process = subprocess.Popen(
            [sys.executable, "-c", program], cwd=root,
            env={**os.environ, "FIXTURE_ROOT": str(root), "FIXTURE_CELL": str(cell),
                 "GITHUB_REPOSITORY": "ltn-it/modulix-validation", "GITHUB_WORKFLOW": "fixture",
                 "GITHUB_RUN_ID": "123", "GITHUB_RUN_ATTEMPT": "1", "QUALITY_INCUS_PROJECT": "fixture"},
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, start_new_session=True,
        )
        try:
            if signum is not None:
                self.wait_for(root / "active", process)
                os.kill(process.pid, signum)
                if repeat_during_stop:
                    time.sleep(0.02)
                    os.kill(process.pid, signal.SIGINT)
                    os.kill(process.pid, signal.SIGTERM)
                if repeat:
                    self.wait_for(root / "capture-ready", process)
                    os.kill(process.pid, signal.SIGINT)
                    os.kill(process.pid, signal.SIGTERM)
            stdout, stderr = process.communicate(timeout=12)
            traces = (root / "pids.jsonl").read_text().splitlines() if (root / "pids.jsonl").exists() else []
            for trace in traces:
                for pid in json.loads(trace)["pids"]:
                    path = Path(f"/proc/{pid}/stat")
                    self.assertTrue(not path.exists() or path.read_text().split()[2] == "Z")
            self.assertEqual("unrelated fixture; never owned", (root / "foreign-resource").read_text())
            if signum is not None:
                self.assertEqual(128 + signum, process.returncode, stdout + stderr)
                self.assertFalse((cell / "control/result.json").exists())
                self.assertFalse((cell / "package").exists())
            return root, cell, process.returncode
        finally:
            traces = (root / "pids.jsonl").read_text().splitlines() if (root / "pids.jsonl").exists() else []
            for trace in traces:
                data = json.loads(trace)
                for pid, birth in zip(data["pids"], data["birth"]):
                    path = Path(f"/proc/{pid}/stat")
                    if path.exists() and path.read_text().split()[21] == birth:
                        try:
                            os.kill(pid, signal.SIGKILL)
                        except ProcessLookupError:
                            pass
            if process.poll() is None:
                os.killpg(process.pid, signal.SIGKILL)
                process.communicate(timeout=5)

    def wait_for(self, path, process):
        deadline = time.monotonic() + 8
        while not path.exists():
            if process.poll() is not None or time.monotonic() > deadline:
                stdout, stderr = process.communicate(timeout=1)
                self.fail("fixture did not reach signal point: " + stdout + stderr)
            time.sleep(0.02)

    def assert_private_recovery(self, cell):
        path = cell / "recovery/context.json"
        self.assertEqual(0o700, path.parent.stat().st_mode & 0o777)
        self.assertEqual(0o600, path.stat().st_mode & 0o777)
        self.assertNotIn(self.command_canary, path.read_text())
        self.assertFalse((path.parent / "ram-control").exists())
        self.assertFalse((cell / "control/result.json").exists())
        return json.loads(path.read_text())

    def test_sigint_cell_disposes_state_only_after_confirmed_finalizers(self):
        root, cell, _ = self.exercise_cell()
        self.assertEqual(["capture", "destroy"], (root / "calls").read_text().splitlines())
        self.assertFalse((cell / "tmp").exists())
        self.assertFalse((cell / "artifacts").exists())
        self.assertFalse((cell / "recovery").exists())

    def test_sigterm_cell_is_failure_after_owned_finalization(self):
        root, cell, _ = self.exercise_cell(signum=signal.SIGTERM)
        self.assertFalse((root / "resource").exists())
        self.assertFalse((cell / "tmp").exists())

    def test_interrupt_before_lifecycle_cannot_touch_foreign_resource(self):
        root, cell, _ = self.exercise_cell(before_state=True)
        context = self.assert_private_recovery(cell)
        self.assertEqual([], context["private_state"])
        self.assertFalse((root / "resource").exists())

    def test_failed_destroy_retains_private_state_after_controller_exit(self):
        root, cell, _ = self.exercise_cell(destroy="failure")
        context = self.assert_private_recovery(cell)
        self.assertFalse(context["destroy_confirmed"])
        self.assertTrue((cell / "tmp/state").exists())
        self.assertTrue((cell / "artifacts/raw").exists())
        self.assertTrue((root / "resource").exists())

    def test_hung_destroy_is_stopped_and_recovery_retained(self):
        _, cell, _ = self.exercise_cell(destroy="timeout")
        self.assertFalse(self.assert_private_recovery(cell)["destroy_confirmed"])

    def test_repeated_interrupts_do_not_skip_bounded_finalizers(self):
        root, cell, _ = self.exercise_cell(repeat=True)
        self.assertEqual(["capture", "destroy"], (root / "calls").read_text().splitlines())
        self.assertFalse((cell / "recovery").exists())

    def test_repeated_interrupts_inside_term_kill_window_cannot_leave_descendants(self):
        root, cell, _ = self.exercise_cell(repeat_during_stop=True)
        self.assertEqual(["capture", "destroy"], (root / "calls").read_text().splitlines())
        self.assertFalse((cell / "recovery").exists())

    def test_interrupt_during_capture_still_destroys_and_preserves_uncaptured_data(self):
        root, cell, _ = self.exercise_cell(interrupt_capture=True)
        context = self.assert_private_recovery(cell)
        self.assertFalse(context["capture_confirmed"])
        self.assertTrue(context["destroy_confirmed"])
        self.assertFalse((root / "resource").exists())

    def test_interrupt_after_confirmed_destruction_cannot_publish_success(self):
        _, cell, _ = self.exercise_cell(interrupt_after_destroy=True)
        self.assertFalse((cell / "tmp").exists())
        self.assertFalse((cell / "recovery").exists())

    def test_cancel_never_executes_unowned_always_steps(self):
        root, _, _ = self.exercise_cell(unowned_finalizer=True)
        self.assertFalse((root / "unowned-effect").exists())

    def test_normal_failed_destruction_keeps_private_recovery_outside_package(self):
        _, cell, code = self.exercise_cell(signum=None, destroy="failure")
        self.assertEqual(1, code)
        self.assertTrue((cell / "tmp/state").exists())
        self.assertFalse(json.loads((cell / "control/result.json").read_text())["success"])
        context = cell / "recovery/context.json"
        self.assertNotIn(self.command_canary, context.read_text())
        self.assertNotIn(self.command_canary, (cell / "package/evidence").read_text())

    def test_interruption_during_destroy_does_not_retry_ambiguous_effect(self):
        root, cell, _ = self.exercise_cell(interrupt_destroy=True)
        self.assertFalse(self.assert_private_recovery(cell)["destroy_confirmed"])
        self.assertEqual(["capture", "destroy"], (root / "calls").read_text().splitlines())

    def test_damaged_command_file_cannot_redirect_finalizers_or_claim_cleanup(self):
        root, cell, _ = self.exercise_cell(damaged_environment=True)
        self.assertFalse((root / "resource").exists())
        self.assertFalse(self.assert_private_recovery(cell)["destroy_confirmed"])

    def test_normal_success_and_failure_keep_existing_publication_contract(self):
        for failure in (False, True):
            with self.subTest(failure=failure):
                _, cell, code = self.exercise_cell(signum=None, normal_failure=failure)
                self.assertEqual(int(failure), code)
                result = json.loads((cell / "control/result.json").read_text())
                self.assertEqual(not failure, result["success"])
                self.assertEqual({"schema", "package_directory", "result_artifact", "success"}, set(result))
                self.assertFalse((cell / "tmp").exists())

    def test_actual_sigint_stops_phase_and_runs_owned_finalizers(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            cell = root / "cell"
            cell.mkdir(mode=0o700)
            active = (
                "import json,os,pathlib,subprocess,sys,time; "
                "child=subprocess.Popen([sys.executable,'-c',"
                "'import signal,time; signal.signal(signal.SIGTERM,signal.SIG_IGN); time.sleep(60)'],"
                "stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL); "
                "pathlib.Path(os.environ['FIXTURE_ROOT'],'active.json').write_text("
                "json.dumps({'parent':os.getpid(),'child':child.pid})); time.sleep(60)"
            )
            steps = [
                {"id": "initialize", "run": 'printf owned > "$FIXTURE_ROOT/resource"'},
                {"id": "molecule", "run": f"python3 -c {shlex.quote(active)}"},
                {"id": "cleanup", "if": "always()", "run":
                 'echo capture >> "$FIXTURE_ROOT/calls"; echo exit_code=0 >> "$GITHUB_OUTPUT"'},
                {"id": "destroy", "if": "always()", "run":
                 'test "$(cat "$FIXTURE_ROOT/resource")" = owned; '
                 'rm "$FIXTURE_ROOT/resource"; echo destroy >> "$FIXTURE_ROOT/calls"; '
                 'echo exit_code=0 >> "$GITHUB_OUTPUT"'},
            ]
            program = (
                "import importlib.util,json,os,pathlib,signal,sys\n"
                f"s=importlib.util.spec_from_file_location('cell',{str(DRIVER)!r})\n"
                "m=importlib.util.module_from_spec(s); s.loader.exec_module(m)\n"
                f"root=pathlib.Path({str(root)!r})\n"
                "previous={kind:signal.getsignal(kind) for kind in (signal.SIGINT,signal.SIGTERM)}\n"
                "try:\n"
                f" results=m.run_steps({steps!r},{{}},dict(os.environ),root/'control',root)\n"
                "except BaseException as error:\n"
                " (root/'outcome.json').write_text(json.dumps({'error':type(error).__name__,"
                "'results':getattr(error,'results',{}),"
                "'handlers_restored':all(signal.getsignal(kind)==value for kind,value in previous.items())}))\n"
                " raise SystemExit(130)\n"
                "raise SystemExit('interruption unexpectedly succeeded')\n"
            )
            process = subprocess.Popen(
                [sys.executable, "-c", program], cwd=root,
                env={**os.environ, "FIXTURE_ROOT": str(root)},
                stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                start_new_session=True,
            )
            pids = {}
            births = {}
            try:
                deadline = time.monotonic() + 8
                while not (root / "active.json").exists():
                    if process.poll() is not None or time.monotonic() > deadline:
                        self.fail("fixture phase did not become active")
                    time.sleep(0.02)
                pids = json.loads((root / "active.json").read_text())
                births = {pid: Path(f"/proc/{pid}/stat").read_text().split()[21] for pid in pids.values()}
                os.kill(process.pid, signal.SIGINT)
                stdout, stderr = process.communicate(timeout=10)
                self.assertEqual(130, process.returncode, stdout + stderr)
                self.assertEqual(["capture", "destroy"], (root / "calls").read_text().splitlines())
                self.assertFalse((root / "resource").exists())
                self.assertEqual("CellCancelled", json.loads((root / "outcome.json").read_text())["error"])
                self.assertTrue(json.loads((root / "outcome.json").read_text())["handlers_restored"])
                for pid in pids.values():
                    state = Path(f"/proc/{pid}/stat")
                    self.assertTrue(not state.exists() or state.read_text().split()[2] == "Z")
            finally:
                for pid, birth in births.items():
                    path = Path(f"/proc/{pid}/stat")
                    if path.exists() and path.read_text().split()[21] == birth:
                        try:
                            os.kill(pid, signal.SIGKILL)
                        except ProcessLookupError:
                            pass
                if process.poll() is None:
                    os.killpg(process.pid, signal.SIGKILL)
                    process.communicate(timeout=5)


if __name__ == "__main__":
    unittest.main()
