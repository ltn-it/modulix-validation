from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
ACTION = ROOT / ".github/actions/run-quality-profile"


class QualityDevtoolsBoundaryTests(unittest.TestCase):
    def test_preflight_and_run_forward_same_complete_native_action_context(self):
        action = yaml.safe_load((ACTION / "action.yml").read_text())
        check = action["runs"]["steps"][0]
        run = next(step for step in action["runs"]["steps"] if step.get("id") == "cell")
        expected = {
            "QUALITY_ACTION_ROOT": "${{ github.action_path }}",
            "QUALITY_ACTION_REPOSITORY": "${{ github.action_repository }}",
            "QUALITY_ACTION_REF": "${{ github.action_ref }}",
            "QUALITY_CONTROLLER_SHA": "${{ github.sha }}",
        }
        expected.update({
            "QUALITY_INPUT_" + name.upper().replace("-", "_"): "${{ inputs." + name + " }}"
            for name in action["inputs"]
        })
        self.assertEqual(expected, check["env"])
        self.assertEqual(expected, run["env"])

    def test_actual_initial_step_uses_action_archive_dispatcher_with_source_separate(self):
        action = yaml.safe_load((ACTION / "action.yml").read_text())
        check = action["runs"]["steps"][0]
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            archive = root / "_actions/ltn-it/modulix-validation" / ("a" * 40)
            controller = archive / ".github/actions/run-quality-profile"
            controller.mkdir(parents=True)
            (controller / "run-devtools.sh").write_bytes((ACTION / "run-devtools.sh").read_bytes())
            source = root / "supplementary"
            (source / "scripts").mkdir(parents=True)
            (source / "scripts/wunder-devtools-ee.sh").write_text(
                "#!/bin/bash\n# WUNDER_DEVTOOLS_QUALITY_CONTEXT: protected-incus-v1\nexit 91\n"
            )
            (archive / "scripts").mkdir()
            proof = root / "proof.json"
            (archive / "scripts/wunder-devtools-ee.sh").write_text(
                "#!/bin/bash\n# WUNDER_DEVTOOLS_QUALITY_CONTEXT: protected-incus-v1\n"
                'test "$1" = --quality-incus-v1-check || exit 92\n'
                'test "$2" = "$QUALITY_ACTION_ROOT" || exit 93\n'
                "python3 -c 'import json,os; open(os.environ[\"PROOF\"],\"w\").write(json.dumps(dict(os.environ)))'\n"
            )
            (root / "context").mkdir()
            contexts = {
                "github.action_path": str(controller),
                "github.action_repository": "ltn-it/modulix-validation",
                "github.action_ref": "a" * 40,
                "github.sha": "b" * 40,
            }
            inputs = {name: "fixture-" + name for name in action["inputs"]}
            contexts.update({"inputs." + name: value for name, value in inputs.items()})
            forwarded = {key: contexts[value.removeprefix("${{ ").removesuffix(" }}")] for key, value in check["env"].items()}
            result = subprocess.run(
                ["/bin/bash", "-c", check["run"]], cwd=source,
                env={**os.environ, **forwarded, "GITHUB_WORKSPACE": str(source),
                     "QUALITY_INCUS_CONFIG_DIR": str(root / "context"), "PROOF": str(proof)},
                capture_output=True, text=True, check=False,
            )
            self.assertEqual(0, result.returncode, result.stderr)
            actual = json.loads(proof.read_text())
            self.assertEqual(str(source), actual["GITHUB_WORKSPACE"])
            self.assertEqual(str(controller), actual["QUALITY_ACTION_ROOT"])
            for name, value in inputs.items():
                self.assertEqual(value, actual["QUALITY_INPUT_" + name.upper().replace("-", "_")])
            self.assertEqual("a" * 40, actual["QUALITY_ACTION_REF"])

    def test_quality_action_never_creates_a_host_interpreter_environment(self):
        action = yaml.safe_load((ACTION / "action.yml").read_text())
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            calls = root / "host-calls"
            for step in action["runs"]["steps"]:
                run = step.get("run", "")
                if "-m venv" not in run:
                    continue
                subprocess.run(
                    [
                        "/bin/bash",
                        "-c",
                        'python3() { printf "%s\\n" "$*" >> "$HOST_CALLS"; return 42; };\n'
                        + run,
                    ],
                    env={
                        **os.environ,
                        "PATH": f"{root}:{os.environ['PATH']}",
                        "HOST_CALLS": str(calls),
                        "RUNNER_TEMP": str(root),
                        "GITHUB_RUN_ID": "123",
                        "GITHUB_RUN_ATTEMPT": "1",
                        "GITHUB_JOB": "heavy",
                        "GITHUB_ENV": str(root / "environment"),
                    },
                    capture_output=True,
                    check=False,
                    timeout=5,
                )
            self.assertFalse(
                calls.exists(), "release-authorizing validation invoked host Python"
            )

    def test_missing_transport_cannot_start_a_container_or_publish_success(self):
        dispatcher = ACTION / "run-devtools.sh"
        self.assertTrue(
            dispatcher.is_file(),
            "quality execution lacks a bounded container dispatcher",
        )
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            engine = root / "docker"
            calls = root / "container-calls"
            engine.write_text('#!/bin/sh\nprintf "%s\\n" "$*" >> "$ENGINE_CALLS"\n')
            engine.chmod(0o755)
            result = subprocess.run(
                ["/bin/bash", str(dispatcher), "run"],
                cwd=ROOT,
                env={
                    **os.environ,
                    "PATH": f"{root}:{os.environ['PATH']}",
                    "ENGINE_CALLS": str(calls),
                    "RUNNER_TEMP": str(root),
                    "GITHUB_WORKSPACE": str(ROOT),
                    "GITHUB_OUTPUT": str(root / "output"),
                    "QUALITY_INCUS_CONFIG_DIR": "",
                },
                capture_output=True,
                text=True,
                check=False,
                timeout=5,
            )
            self.assertNotEqual(0, result.returncode)
            self.assertIn("approved Incus", result.stderr)
            self.assertFalse(calls.exists())
            self.assertFalse((root / "output").exists())

    def load_driver(self):
        spec = importlib.util.spec_from_file_location(
            "quality_cell", ACTION / "run-cell.py"
        )
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module

    def test_nonempty_transport_cannot_bypass_missing_central_contract(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "transport").mkdir()
            action_root = root / ".github/actions/run-quality-profile"
            action_root.mkdir(parents=True)
            (root / "scripts").mkdir()
            (root / "scripts/wunder-devtools-ee.sh").write_text(
                "#!/bin/bash\nexit 99\n"
            )
            result = subprocess.run(
                ["/bin/bash", str(ACTION / "run-devtools.sh"), "check"],
                env={
                    **os.environ,
                    "GITHUB_WORKSPACE": str(root),
                    "QUALITY_ACTION_ROOT": str(action_root),
                    "QUALITY_INCUS_CONFIG_DIR": str(root / "transport"),
                },
                capture_output=True,
                text=True,
                check=False,
                timeout=5,
            )
            self.assertNotEqual(0, result.returncode)
            self.assertNotEqual(99, result.returncode)
            self.assertIn("no approved protected-incus-v1 contract", result.stderr)

    def test_damaged_private_output_never_suppresses_owned_finalizers(self):
        module = self.load_driver()
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            steps = [
                {
                    "id": "initialize",
                    "run": 'echo "QUALITY_SCENARIO=fixture" >> "$GITHUB_ENV"',
                },
                {
                    "id": "molecule",
                    "run": 'echo PATH=/untrusted >> "$GITHUB_ENV"; exit 1',
                },
                {
                    "id": "destroy",
                    "if": "always()",
                    "run": 'echo "$QUALITY_SCENARIO" > "$DESTROY_PROOF"',
                },
            ]
            proof = root / "destroyed"
            results = module.run_steps(
                steps,
                {},
                {**os.environ, "DESTROY_PROOF": str(proof)},
                root / "control",
                root,
            )
            self.assertEqual("fixture\n", proof.read_text())
            self.assertEqual("failure", results["destroy"]["outcome"])

    def test_failed_test_still_captures_destroys_and_records_inside_cell(self):
        module = self.load_driver()
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            calls = root / "calls"
            steps = [
                {
                    "id": "initialize",
                    "run": 'echo "QUALITY_SCENARIO=fixture" >> "$GITHUB_ENV"',
                },
                {"id": "molecule", "run": 'echo test >> "$CALLS"; exit 124'},
                {"id": "ordinary", "run": 'echo should-not-run >> "$CALLS"'},
                {
                    "id": "cleanup",
                    "if": "always()",
                    "run": 'echo "capture-$QUALITY_SCENARIO" >> "$CALLS"',
                },
                {
                    "id": "destroy",
                    "if": "always()",
                    "run": 'echo destroy >> "$CALLS"; echo exit_code=0 >> "$GITHUB_OUTPUT"',
                },
            ]
            results = module.run_steps(
                steps, {}, {**os.environ, "CALLS": str(calls)}, root / "control", root
            )
            self.assertEqual(
                ["test", "capture-fixture", "destroy"], calls.read_text().splitlines()
            )
            self.assertEqual("failure", results["molecule"]["outcome"])
            self.assertEqual("skipped", results["ordinary"]["outcome"])
            self.assertEqual("0", results["destroy"]["outputs"]["exit_code"])

    def test_private_environment_cannot_redirect_runtime_or_command_files(self):
        module = self.load_driver()
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "environment"
            for key in (
                "PATH",
                "HOME",
                "GITHUB_OUTPUT",
                "GITHUB_ENV",
                "INCUS_CONF",
                "LD_PRELOAD",
                "QUALITY_DEVTOOLS_IMAGE",
                "QUALITY_HOST_UID",
            ):
                path.write_text(f"{key}=/untrusted\n")
                with (
                    self.subTest(key=key),
                    self.assertRaisesRegex(ValueError, "unexpected private"),
                ):
                    module.private_values(path, environment=True)

    def test_transport_is_private_run_attempt_bound_tls_and_time_limited(self):
        module = self.load_driver()
        now = datetime.now(timezone.utc)
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            config = {
                "default-remote": "quality",
                "remotes": {
                    "quality": {
                        "addr": "https://fixture.invalid:8443",
                        "project": "quality-fixture",
                        "auth_type": "tls",
                        "protocol": "incus",
                        "public": False,
                    }
                },
            }
            binding = {
                "schema": 1,
                "repository": "ltn-it/modulix-validation",
                "run_id": "123",
                "run_attempt": "1",
                "server": "https://fixture.invalid:8443",
                "project": "quality-fixture",
                "expires_at": (now + timedelta(minutes=85)).isoformat(),
            }
            (root / "servercerts").mkdir(mode=0o700)
            for name in ("client.crt", "client.key", "servercerts/quality.crt"):
                (root / name).write_text("fixture only, never connects")
                (root / name).chmod(0o600)
            (root / "config.yml").write_text(yaml.safe_dump(config))
            (root / "config.yml").chmod(0o600)
            path = root / "binding.json"
            path.write_text(json.dumps(binding))
            path.chmod(0o600)
            environment = {
                "QUALITY_DEVTOOLS_IMAGE": "quay.io/l-it/ee-wunder-devtools-ubi9:v1.16.1@sha256:"
                + "c" * 64,
                "INCUS_CONF": str(root),
                "QUALITY_HOST_UID": "501",
                "QUALITY_EFFECTIVE_UID": str(os.getuid()),
                "QUALITY_EFFECTIVE_GID": str(os.getgid()),
                "GITHUB_REPOSITORY": binding["repository"],
                "GITHUB_RUN_ID": "123",
                "GITHUB_RUN_ATTEMPT": "1",
            }
            module.validate_transport(environment, root, now=now)
            for changed in (
                {"run_attempt": "2"},
                {"run_id": "124"},
                {"expires_at": now.isoformat()},
                {"expires_at": (now + timedelta(hours=2)).isoformat()},
                {"server": "http://fixture.invalid"},
            ):
                path.write_text(json.dumps({**binding, **changed}))
                with self.subTest(changed=changed), self.assertRaises(ValueError):
                    module.validate_transport(environment, root, now=now)
            path.write_text(json.dumps(binding))
            remote = config["remotes"]["quality"]
            for changed in ({"auth-type": "tls"}, {"public": True}, {"unrelated": "value"}):
                (root / "config.yml").write_text(yaml.safe_dump({
                    **config, "remotes": {"quality": {**remote, **changed}}
                }))
                with self.subTest(remote=changed), self.assertRaises(ValueError):
                    module.validate_transport(environment, root, now=now)
            (root / "config.yml").write_text(yaml.safe_dump(config))
            (root / "client.key").chmod(0o644)
            with self.assertRaisesRegex(ValueError, "not private"):
                module.validate_transport(environment, root, now=now)


if __name__ == "__main__":
    unittest.main()
