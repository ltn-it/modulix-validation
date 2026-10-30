from __future__ import annotations

import importlib.util
import json
import os
import shlex
import signal
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
ACTION = ROOT / ".github/actions/run-quality-profile"


class QualityTimeoutCancellationTests(unittest.TestCase):
    def load_driver(self):
        spec = importlib.util.spec_from_file_location("cell", ACTION / "run-cell.py")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module

    def test_pidfd_unavailable_rejects_before_ordinary_effects_without_fallback(self):
        module = self.load_driver()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            cell = root / "cell"
            cell.mkdir()
            steps = [{"id": "molecule", "run": f"touch {root / 'ordinary-effect'}"}]
            with (mock.patch.object(module.os, "pidfd_open", side_effect=OSError("unsupported")),
                  mock.patch.object(module.subprocess, "Popen") as launch,
                  self.assertRaises(module.ProcessQuiescenceError)):
                module.execute_owned_cell(steps, {}, dict(os.environ), root / "control", root, cell)
            launch.assert_not_called()
            self.assertFalse((root / "ordinary-effect").exists())
            self.assertTrue((cell / "recovery/context.json").is_file())
            self.assertFalse((cell / "control/result.json").exists())

    def test_pid_replaced_before_handle_revalidation_is_not_signalled(self):
        module = self.load_driver()
        descriptor = os.pidfd_open(os.getpid())
        with (mock.patch.object(module.os, "pidfd_open", return_value=descriptor),
              mock.patch.object(module, "process_identity", return_value=("S", 222, "new-birth")),
              mock.patch.object(module.signal, "pidfd_send_signal") as send,
              mock.patch.object(module.os, "kill", side_effect=AssertionError("unsafe numeric PID"))):
            module.signal_owned_member(123, ("S", 111, "old-birth"), signal.SIGTERM)
        send.assert_not_called()
        with self.assertRaises(OSError):
            os.fstat(descriptor)

    def test_exit_between_revalidation_and_send_keeps_handle_bound_and_foreign_alive(self):
        module = self.load_driver()
        owned = subprocess.Popen([sys.executable, "-c", "import time;time.sleep(60)"],
                                 start_new_session=True)
        foreign = subprocess.Popen([sys.executable, "-c", "import time;time.sleep(60)"],
                                   start_new_session=True)
        self.addCleanup(lambda: self.stop_foreign(foreign))
        self.addCleanup(lambda: self.stop_foreign(owned))
        identity = module.process_identity(Path(f"/proc/{owned.pid}"))
        real_kill = os.kill

        def exit_after_inspection(_path):
            real_kill(owned.pid, signal.SIGTERM)
            owned.wait(timeout=3)
            return identity

        with (mock.patch.object(module, "process_identity", side_effect=exit_after_inspection),
              mock.patch.object(module.signal, "pidfd_send_signal", wraps=signal.pidfd_send_signal) as send,
              mock.patch.object(module.os, "kill", side_effect=AssertionError("unsafe numeric PID"))):
            module.signal_owned_member(owned.pid, identity, signal.SIGKILL)
        send.assert_called_once()
        self.assertIsNone(foreign.poll())

    def test_unavailable_process_inventory_blocks_finalizers_and_retains_private_state(self):
        module = self.load_driver()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            cell = root / "cell"
            (cell / "tmp").mkdir(parents=True)
            state = cell / "tmp/state"
            state.write_text("private-owned-state")
            steps = [{"id": "molecule", "run": ":"},
                     {"id": "cleanup", "if": "always()", "run": f"touch {root / 'capture'}"},
                     {"id": "destroy", "if": "always()", "run": f"touch {root / 'destroy'}"}]
            with (mock.patch.object(module.Path, "iterdir", side_effect=PermissionError),
                  self.assertRaises(module.ProcessQuiescenceError)):
                module.execute_owned_cell(steps, {}, dict(os.environ), root / "control", root, cell)
            self.assertEqual("private-owned-state", state.read_text())
            self.assertFalse((root / "capture").exists())
            self.assertFalse((root / "destroy").exists())
            context = cell / "recovery/context.json"
            self.assertEqual(0o700, context.parent.stat().st_mode & 0o777)
            self.assertEqual(0o600, context.stat().st_mode & 0o777)
            self.assertFalse((cell / "control/result.json").exists())
            self.assertFalse((cell / "package").exists())

    def test_persistently_vanished_inventory_is_bounded_and_cannot_start_finalizers(self):
        module = self.load_driver()
        module.PROCESS_STOP_SECONDS = 0.03
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            cell = root / "cell"
            (cell / "tmp").mkdir(parents=True)
            (cell / "tmp/state").write_text("private-owned-state")
            steps = [{"id": "molecule", "run": ":"},
                     {"id": "cleanup", "if": "always()", "run": f"touch {root / 'capture'}"},
                     {"id": "destroy", "if": "always()", "run": f"touch {root / 'destroy'}"}]
            started = time.monotonic()
            with (mock.patch.object(module, "process_identity", return_value=None),
                  self.assertRaises(module.ProcessQuiescenceError)):
                module.execute_owned_cell(steps, {}, dict(os.environ), root / "control", root, cell)
            self.assertLess(time.monotonic() - started, 2)
            self.assertFalse((root / "capture").exists())
            self.assertFalse((root / "destroy").exists())
            self.assertEqual("private-owned-state", (cell / "tmp/state").read_text())
            context = cell / "recovery/context.json"
            self.assertEqual(0o700, context.parent.stat().st_mode & 0o777)
            self.assertEqual(0o600, context.stat().st_mode & 0o777)
            self.assertFalse((cell / "control/result.json").exists())
            self.assertFalse((cell / "package").exists())

    def test_first_terminal_observation_requires_rescan_but_stable_terminal_is_quiescent(self):
        module = self.load_driver()
        process = mock.Mock(pid=123)
        # A first observed zombie can have forked after the directory listing;
        # a second identical terminal birth cannot fork again and must not spin.
        snapshot = ({}, {(456, "terminal-birth")}, False)
        with (mock.patch.object(module, "owned_session_members", return_value=snapshot) as scan,
              mock.patch.object(module, "signal_owned_member") as send):
            self.assertFalse(module.stop_owned_process(process))
        self.assertEqual(2, scan.call_count)
        process.wait.assert_called_once()
        send.assert_not_called()

    def exercise(self, *, signum=signal.SIGINT, repeat=False, hang="test", early_exit=False,
                 fork_handoff=False, prepare_timeout_phase=""):
        root = Path(self.enterContext(tempfile.TemporaryDirectory()))
        environment = {key: value for key, value in os.environ.items()
                       if key not in {"GIT_DIR", "GIT_COMMON_DIR", "GIT_WORK_TREE"}}
        subprocess.run(["git", "init", "--quiet", str(root)], env=environment,
                       check=True, capture_output=True)
        scenario = root / "molecule/fixture/molecule.yml"
        scenario.parent.mkdir(parents=True)
        scenario.write_text("driver: {name: default}\nplatforms: [{name: offline}]\n"
                            "provisioner: {name: ansible}\n")
        base = root / ".config/molecule/config.yml"
        base.parent.mkdir(parents=True)
        base.write_text("prerun: false\n")
        cell = root / "cell"
        (cell / "tmp").mkdir(parents=True)
        (cell / "tmp/state").write_text("private-owned-state")
        (cell / "artifacts").mkdir()
        (cell / "artifacts/raw").write_text("private-diagnostic")
        binary = root / "bin"
        binary.mkdir()
        worker = root / "worker.py"
        worker.write_text(
            "import json,os,pathlib,signal,time\n"
            "root=pathlib.Path(os.environ['FIXTURE_ROOT'])\n"
            "signal.signal(signal.SIGTERM,signal.SIG_IGN)\n"
            "def record():\n"
            " data={'pid':os.getpid(),'pgid':os.getpgrp(),'sid':os.getsid(0),"
            "'birth':pathlib.Path('/proc/self/stat').read_text().split()[21]}\n"
            " with (root/'pids').open('a') as stream: stream.write(json.dumps(data)+'\\n')\n"
            "record()\n"
            "(root/'active').touch()\n"
            "if os.environ.get('FIXTURE_FORK_HANDOFF')=='1':\n"
            " while not (root/'fork-release').exists(): time.sleep(0.005)\n"
            " if os.fork(): os._exit(0)\n"
            " record()\n"
            " (root/'handoff-child').touch()\n"
            "while True: time.sleep(0.02)\n"
        )
        molecule = binary / "molecule"
        molecule.write_text(
            "#!/usr/bin/env python3\n"
            "import json,os,pathlib,signal,subprocess,sys,time\n"
            "root=pathlib.Path(os.environ['FIXTURE_ROOT'])\n"
            "args=sys.argv[1:]\n"
            "while args[0]=='--base-config': args=args[2:]\n"
            "phase=args[0]\n"
            "if phase==os.environ.get('FIXTURE_PREP_TIMEOUT'): time.sleep(30)\n"
            "def active():\n"
            " for line in (root/'pids').read_text().splitlines() if (root/'pids').exists() else []:\n"
            "  data=json.loads(line); path=pathlib.Path('/proc',str(data['pid']),'stat')\n"
            "  if path.exists():\n"
            "   fields=path.read_text().split()\n"
            "   if fields[21]==data['birth'] and fields[2]!='Z': return True\n"
            " return False\n"
            "if phase!='test' and active(): (root/'overlap').touch()\n"
            "with (root/'calls').open('a') as stream: stream.write(phase+'\\n')\n"
            "if phase in os.environ['FIXTURE_HANG'].split(','):\n"
            " child=subprocess.Popen([sys.executable,str(root/'worker.py')],"
            "stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)\n"
            " while not (root/'active').exists(): time.sleep(0.01)\n"
            " if os.environ['FIXTURE_EARLY']=='1': raise SystemExit(0)\n"
            " signal.signal(signal.SIGTERM,signal.SIG_IGN)\n"
            " child.wait()\n"
        )
        molecule.chmod(0o755)
        phase = lambda name: f"bash {shlex.quote(str(ACTION / 'run-phase.sh'))} {name} 60"
        steps = [
            {"id": "molecule", "run": phase("test")},
            {"id": "cleanup", "if": "always()", "run": phase("cleanup")},
            {"id": "destroy", "if": "always()", "run": phase("destroy")},
            {"id": "evidence", "if": "always()", "run": 'echo exit_code=0 >> "$GITHUB_OUTPUT"'},
        ]
        if "test" not in hang.split(","):
            # Enter cancellation during a real finalizer: it must not be retried.
            steps[0]["run"] = 'echo exit_code=0 >> "$GITHUB_OUTPUT"'
        hook = (
            "original_iterdir=pathlib.Path.iterdir\n"
            "def handoff_inventory(path):\n"
            " paths=list(original_iterdir(path))\n"
            " if path==pathlib.Path('/proc') and not (root/'fork-release').exists():\n"
            "  sid=json.loads((root/'pids').read_text().splitlines()[0])['sid']\n"
            "  members=[p for p in paths if p.name.isdecimal() and "
            "(identity:=module.process_identity(p)) is not None and identity[1]==sid]\n"
            "  (root/'fork-release').touch()\n"
            "  deadline=time.monotonic()+3\n"
            "  while (not (root/'handoff-child').exists() or any("
            "(identity:=module.process_identity(p)) is not None and identity[0] not in {'Z','X'} "
            "for p in members)):\n"
            "   assert time.monotonic()<deadline,'pipeline parents did not finish the real fork handoff'\n"
            "   time.sleep(0.005)\n"
            "  child=json.loads((root/'pids').read_text().splitlines()[-1])['pid']\n"
            "  assert str(child) not in {p.name for p in paths},'new child was already in the old listing'\n"
            "  (root/'handoff-proof').write_text(json.dumps({'old_listing_misses_child':True,"
            "'parent_chain_exited':True,'actual_timeout_tee':True}))\n"
            " return iter(paths)\n"
            "pathlib.Path.iterdir=handoff_inventory\n"
        ) if fork_handoff else ""
        program = (
            "import importlib.util,json,os,pathlib,time\n"
            f"spec=importlib.util.spec_from_file_location('cell',{str(ACTION / 'run-cell.py')!r})\n"
            "module=importlib.util.module_from_spec(spec); spec.loader.exec_module(module)\n"
            f"module.PROCESS_STOP_SECONDS={0.4 if fork_handoff else 0.15}\n"
            "module.CANCEL_FINALIZER_SECONDS=5\n"
            f"root=pathlib.Path({str(root)!r})\n"
            "original_run=module.run_owned_process\n"
            "def traced_run(command,workspace,environment,cancellation):\n"
            " started=time.monotonic(); code=None; error=None\n"
            " phase=pathlib.Path(environment['GITHUB_OUTPUT']).stem\n"
            " if phase in {'cleanup','destroy'} and (root/'pids').exists():\n"
            "  for line in (root/'pids').read_text().splitlines():\n"
            "   data=json.loads(line); path=pathlib.Path('/proc',str(data['pid']),'stat')\n"
            "   if path.exists():\n"
            "    fields=path.read_text().split()\n"
            "    if fields[21]==data['birth'] and fields[2] not in {'Z','X'}: (root/'entry-overlap').touch()\n"
            " try:\n"
            "  code=original_run(command,workspace,environment,cancellation); return code\n"
            " except BaseException as caught:\n"
            "  error=type(caught).__name__; raise\n"
            " finally:\n"
            "  trace={'phase':pathlib.Path(environment['GITHUB_OUTPUT']).stem,'code':code,"
            "'error':error,'seconds':round(time.monotonic()-started,3)}\n"
            "  with (root/'phase-trace').open('a') as stream: stream.write(json.dumps(trace)+'\\n')\n"
            "module.run_owned_process=traced_run\n"
            f"{hook}"
            f"raise SystemExit(module.execute_owned_cell({steps!r},{{}},dict(os.environ),"
            "root/'control',root,root/'cell'))\n"
        )
        environment.update({"PATH": f"{binary}:{environment['PATH']}", "TMPDIR": str(root),
                            "FIXTURE_ROOT": str(root), "FIXTURE_HANG": hang,
                            "FIXTURE_FORK_HANDOFF": str(int(fork_handoff)),
                            "FIXTURE_PREP_TIMEOUT": prepare_timeout_phase,
                            "FIXTURE_EARLY": str(int(early_exit)), "QUALITY_SCENARIO": "fixture",
                            "QUALITY_LOG_PATH": str(root / "molecule.log"),
                            "QUALITY_INCUS_PROJECT": "owned-fixture"})
        foreign = subprocess.Popen([sys.executable, "-c", "import time;time.sleep(60)"],
                                   env=environment, start_new_session=True)
        self.addCleanup(lambda: self.stop_foreign(foreign))
        controller = subprocess.Popen([sys.executable, "-c", program], env=environment, cwd=root,
                                      stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                                      start_new_session=True)
        try:
            deadline = time.monotonic() + 8
            while not (root / "active").exists():
                if controller.poll() is not None or time.monotonic() > deadline:
                    self.fail("actual timeout/tee pipeline did not become active")
                time.sleep(0.01)
            if signum is not None:
                os.kill(controller.pid, signum)
                if repeat:
                    time.sleep(0.03)
                    os.kill(controller.pid, signal.SIGTERM)
                    os.kill(controller.pid, signal.SIGINT)
            stdout, stderr = controller.communicate(timeout=20)
            trace = (root / "phase-trace").read_text() if (root / "phase-trace").exists() else "no phase trace"
            diagnostics = stdout + stderr + "\n" + trace
            if os.environ.get("QUALITY_TEST_TRACE") == "1":
                print(trace, flush=True)
            self.assertIsNone(foreign.poll(), "unrelated process was signalled")
            self.assertFalse((root / "entry-overlap").exists(), diagnostics)
            outcomes = [json.loads(line) for line in trace.splitlines()]
            expected_phases = ["molecule", "cleanup", "destroy"] + (["evidence"] if signum is None else [])
            self.assertEqual(expected_phases, [row["phase"] for row in outcomes], diagnostics)
            records = [json.loads(line) for line in (root / "pids").read_text().splitlines()]
            if fork_handoff:
                self.assertEqual(2, len(records))
                self.assertEqual({"old_listing_misses_child": True, "parent_chain_exited": True,
                                  "actual_timeout_tee": True}, json.loads((root / "handoff-proof").read_text()))
            self.assertTrue(records)
            self.assertTrue(all(item["sid"] != item["pgid"] for item in records),
                            "fixture must use the actual separate GNU timeout process group")
            self.assertFalse((root / "overlap").exists(), "finalizer overlapped active prior phase")
            for item in records:
                path = Path(f"/proc/{item['pid']}/stat")
                self.assertTrue(not path.exists() or path.read_text().split()[2] == "Z",
                                "timeout-owned worker survived the controller")
            expected = ["test", "cleanup", "destroy"] if "test" in hang.split(",") else ["cleanup", "destroy"]
            if prepare_timeout_phase:
                expected.remove(prepare_timeout_phase)
                self.assertEqual(124, next(row["code"] for row in outcomes
                                          if row["phase"] == prepare_timeout_phase), diagnostics)
            self.assertEqual(expected, (root / "calls").read_text().splitlines(), diagnostics)
            if signum is not None:
                self.assertEqual(128 + signum, controller.returncode, stdout + stderr)
                self.assertFalse((cell / "control/result.json").exists())
            else:
                self.assertEqual(1 if early_exit else 0, controller.returncode, stdout + stderr)
                publication = json.loads((cell / "control/result.json").read_text())
                self.assertEqual(not early_exit, publication["success"])
            if hang != "test" or prepare_timeout_phase:
                self.assertTrue((cell / "tmp/state").is_file())
                self.assertTrue((cell / "recovery/context.json").is_file())
            else:
                self.assertFalse((cell / "tmp").exists())
        finally:
            for line in (root / "pids").read_text().splitlines() if (root / "pids").exists() else []:
                item = json.loads(line)
                path = Path(f"/proc/{item['pid']}/stat")
                if path.exists() and path.read_text().split()[21] == item["birth"]:
                    try:
                        os.killpg(item["pgid"], signal.SIGKILL)
                    except ProcessLookupError:
                        pass
            if controller.poll() is None:
                os.killpg(controller.pid, signal.SIGKILL)
                controller.communicate(timeout=5)

    @staticmethod
    def stop_foreign(process):
        process.terminate()
        process.wait(timeout=3)

    def test_actual_timeout_tee_sigint_is_quiescent_before_finalizers(self):
        self.exercise()

    def test_actual_timeout_tee_sigterm_is_quiescent_before_finalizers(self):
        self.exercise(signum=signal.SIGTERM)

    def test_repeated_signals_cannot_leave_timeout_owned_groups(self):
        self.exercise(repeat=True)

    def test_interrupted_real_capture_stops_its_group_before_destroy(self):
        self.exercise(hang="cleanup")

    def test_interrupted_real_destroy_preserves_recovery_without_retry(self):
        self.exercise(hang="destroy")

    def test_parent_exit_cannot_leave_its_timeout_child_running(self):
        self.exercise(signum=None, early_exit=True)

    def test_cancel_during_parent_exit_cannot_interrupt_group_shutdown(self):
        self.exercise(early_exit=True, repeat=True)

    def test_cancelled_capture_timeout_stops_group_before_destroy(self):
        self.exercise(hang="test,cleanup")

    def test_cancelled_destroy_timeout_stops_group_and_retains_state(self):
        self.exercise(hang="test,destroy")

    def test_fork_after_listing_and_parent_exit_cannot_overlap_finalizers(self):
        self.exercise(fork_handoff=True)

    def test_sigterm_fork_handoff_cannot_leave_a_missed_child(self):
        self.exercise(fork_handoff=True, signum=signal.SIGTERM)

    def test_repeated_signals_during_fork_handoff_still_stop_child(self):
        self.exercise(fork_handoff=True, repeat=True)

    def test_zero_exit_fork_handoff_cannot_publish_success_with_a_missed_child(self):
        self.exercise(fork_handoff=True, early_exit=True, signum=None)

    def test_finalizer_timeout_before_molecule_effects_is_not_skipped_or_success(self):
        self.exercise(prepare_timeout_phase="destroy")


if __name__ == "__main__":
    unittest.main()
