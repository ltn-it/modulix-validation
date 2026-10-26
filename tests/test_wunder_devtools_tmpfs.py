# Managed by lightning-it/shared-assets-lit.

import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
WRAPPER = ROOT / "scripts" / "wunder-devtools-ee.sh"


class WunderDevtoolsTmpfsTests(unittest.TestCase):
    def wrapper_args(self, engine: str, *, rootless: bool) -> list[str]:
        with tempfile.TemporaryDirectory() as temporary_directory:
            temporary_root = Path(temporary_directory)
            environment = {
                "HOME": str(temporary_root),
                "PATH": os.environ.get("PATH") or os.defpath,
                "WUNDER_CONTAINER_ENGINE": engine,
                "WUNDER_DEVTOOLS_DOCKER_SOCKET": "disabled",
                "WUNDER_DEVTOOLS_RUN_AS_HOST_UID": "1",
                "FAKE_ROOTLESS": "true" if rootless else "false",
            }
            # Exported Bash functions emulate only the two container-engine
            # calls the wrapper makes. No executable fixture is written to a
            # host or container temporary filesystem, which remains noexec.
            harness = r"""
fake_engine() {
  if [ "${1:-}" = "info" ]; then
    printf '%s\n' "${FAKE_ROOTLESS:-false}"
    return 0
  fi
  printf '%s\n' "$@"
}
docker() { fake_engine "$@"; }
podman() { fake_engine "$@"; }
export -f fake_engine docker podman
exec /bin/bash "$1" true
"""
            result = subprocess.run(
                ["/bin/bash", "-c", harness, "wunder-test", str(WRAPPER)],
                cwd=temporary_root,
                env=environment,
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertEqual(0, result.returncode, result.stderr)
            return result.stdout.splitlines()

    def test_host_uid_run_tmpfs_matches_container_identity(self) -> None:
        cases = (
            ("docker", False, os.getuid(), os.getgid(), True),
            ("podman", False, os.getuid(), os.getgid(), True),
            ("podman", True, 0, 0, False),
        )
        for engine, rootless, expected_uid, expected_gid, includes_identity in cases:
            with self.subTest(engine=engine, rootless=rootless):
                arguments = self.wrapper_args(engine, rootless=rootless)
                self.assertEqual(
                    f"{expected_uid}:{expected_gid}",
                    arguments[arguments.index("--user") + 1],
                )
                run_mount = next(
                    argument for argument in arguments if argument.startswith("/run:")
                )
                if includes_identity:
                    expected_mount = (
                        "/run:rw,nosuid,nodev,size=256m,"
                        f"uid={expected_uid},gid={expected_gid},mode=0755"
                    )
                else:
                    expected_mount = "/run:rw,nosuid,nodev,size=256m,mode=0755"
                    self.assertNotIn("uid=", run_mount)
                    self.assertNotIn("gid=", run_mount)
                self.assertEqual(expected_mount, run_mount)
                self.assertNotIn("mode=1777", run_mount)

    def test_wrapper_args_do_not_require_ambient_home_or_path(self) -> None:
        with mock.patch.dict(os.environ, {}, clear=True):
            arguments = self.wrapper_args("docker", rootless=False)
        self.assertEqual(
            f"{os.getuid()}:{os.getgid()}",
            arguments[arguments.index("--user") + 1],
        )

class ProtectedIncusContextTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.workspace = self.root / "work/modulix-validation/modulix-validation"
        self.workspace.mkdir(parents=True)
        self.runtime = self.root / "temp"
        self.runtime.mkdir(mode=0o700)
        self.action_sha = "a" * 40
        self.controller_sha = "b" * 40
        self.action = self.root / f"work/_actions/ltn-it/modulix-validation/{self.action_sha}/.github/actions/run-quality-profile"
        self.action.mkdir(parents=True)
        for name in ("action.yml", "run-devtools.sh", "run-cell.py", "run-phase.sh", "profile-steps.yml"):
            (self.action / name).write_text("fixture only\n")
        self.context = self.runtime / "mlx90-incus/123/1"
        (self.context / "servercerts").mkdir(mode=0o700, parents=True)
        self.context.chmod(0o700)
        for name in ("binding.json", "config.yml", "client.crt", "client.key", "servercerts/quality.crt"):
            (self.context / name).write_text("fixture only; no target access\n")
            (self.context / name).chmod(0o600)
        self.output = self.runtime / "_runner_file_commands/set_output_fixture"
        self.output.parent.mkdir(mode=0o700)
        self.output.touch(mode=0o600)
        self.trace = self.root / "engine.jsonl"
        self.binary = self.root / "bin"
        self.binary.mkdir()
        # The generic rootless wrapper intentionally selects container UID 0.
        # This protected-runner fixture models a non-root host independently
        # of that outer test-container identity. Preserve real mode, link,
        # size and traversal checks; translate only ownership of fixture files.
        self.runner_uid = os.getuid() or 1001
        self.runner_gid = os.getgid() if os.getuid() else 1001
        real_id = shutil.which("id")
        real_stat = shutil.which("stat")
        self.assertIsNotNone(real_id)
        self.assertIsNotNone(real_stat)
        identity = self.binary / "id"
        identity.write_text(
            "#!/usr/bin/env python3\nimport os, subprocess, sys\n"
            f"uid = os.environ.get('FIXTURE_RUNNER_UID', {str(self.runner_uid)!r})\n"
            f"gid = {str(self.runner_gid)!r}\n"
            "if sys.argv[1:] == ['-u']: print(uid)\n"
            "elif sys.argv[1:] == ['-g']: print(gid)\n"
            f"else: raise SystemExit(subprocess.run([{real_id!r}, *sys.argv[1:]], check=False).returncode)\n"
        )
        identity.chmod(0o755)
        metadata = self.binary / "stat"
        metadata.write_text(
            "#!/usr/bin/env python3\nimport os, pathlib, subprocess, sys\n"
            "args = sys.argv[1:]\n"
            "if len(args) == 4 and args[:3] == ['-c', '%u', '--']:\n"
            " path = pathlib.Path(args[3])\n"
            f" if path.is_relative_to({str(self.root)!r}) and path.stat().st_uid == {os.getuid()}:\n"
            f"  uid = {self.runner_uid}\n"
            "  if str(path) == os.environ.get('FIXTURE_FOREIGN_OWNER'): uid += 1\n"
            "  print(uid); raise SystemExit(0)\n"
            f"raise SystemExit(subprocess.run([{real_stat!r}, *args], check=False).returncode)\n"
        )
        metadata.chmod(0o755)
        engine = self.binary / "docker"
        engine.write_text(
            "#!/usr/bin/env python3\nimport json, pathlib, sys\n"
            f"trace = pathlib.Path({str(self.trace)!r})\n"
            "with trace.open('a') as stream: stream.write(json.dumps(sys.argv[1:]) + '\\n')\n"
            "args = sys.argv[1:]\n"
            "if args[0] == 'info': raise SystemExit(0)\n"
            "if 'QUALITY_CONTEXT_PHASE=preflight' in args:\n"
            " print('PROTECTED_INCUS_PREFLIGHT=1'); raise SystemExit(0)\n"
            "for value in args:\n"
            " if 'destination=/quality' in value:\n"
            "  state = pathlib.Path(value.split('source=', 1)[1].split(',', 1)[0])\n"
            "  (state/'control').mkdir(); (state/'package').mkdir()\n"
            "  (state/'package/result.tar.gz').write_bytes(b'fixture')\n"
            "  (state/'package/SHA256SUMS').write_text('fixture')\n"
            "  result = {'schema':1, 'success':True, 'package_directory':'/quality/package',\n"
            f"   'result_artifact':'quality-result-fixture-target-{'c' * 40}-attempt-1'}}\n"
            "  (state/'control/result.json').write_text(json.dumps(result,sort_keys=True)+'\\n')\n"
            "  (state/'control/result.json').chmod(0o600)\n"
        )
        engine.chmod(0o755)
        self.engine = engine
        self.environment = {
            "PATH": f"{self.binary}:{os.environ.get('PATH', os.defpath)}",
            "HOME": str(self.root),
            "BASH_ENV": "",
            "WUNDER_CONTAINER_ENGINE": "docker",
            "GITHUB_ACTIONS": "true",
            "GITHUB_EVENT_NAME": "workflow_dispatch",
            "GITHUB_REPOSITORY": "ltn-it/modulix-validation",
            "GITHUB_REPOSITORY_ID": "1269461997",
            "GITHUB_REF": "refs/heads/main",
            "GITHUB_REF_PROTECTED": "true",
            "GITHUB_SHA": self.controller_sha,
            "GITHUB_ACTOR": "lightning-it-release-automation[bot]",
            "GITHUB_ACTOR_ID": "307565056",
            "GITHUB_TRIGGERING_ACTOR": "lightning-it-release-automation[bot]",
            "GITHUB_RUN_ID": "123", "GITHUB_RUN_ATTEMPT": "1", "GITHUB_JOB": "heavy",
            "GITHUB_WORKFLOW": "MLX-90 collection candidate validation",
            "GITHUB_WORKSPACE": str(self.workspace),
            "RUNNER_WORKSPACE": str(self.workspace.parent), "RUNNER_TEMP": str(self.runtime),
            "GITHUB_OUTPUT": str(self.output),
            "QUALITY_ACTION_REPOSITORY": "ltn-it/modulix-validation",
            "QUALITY_ACTION_REF": self.action_sha,
            "QUALITY_ACTION_ROOT": str(self.action),
            "QUALITY_CONTROLLER_SHA": self.controller_sha,
            "QUALITY_INCUS_CONFIG_DIR": str(self.context),
            "QUALITY_INPUT_PROFILE": "heavy", "QUALITY_INPUT_SCENARIO": "fixture",
            "QUALITY_INPUT_TARGET": "target", "QUALITY_INPUT_TARGET_DISPOSITION": "supported",
            "QUALITY_INPUT_ROLES": "keycloak_deploy", "QUALITY_INPUT_IMAGE": "images:fixture",
            "QUALITY_INPUT_INSTANCE_TYPE": "container", "QUALITY_INPUT_CANDIDATE_ARTIFACT": "mlx90-candidate-fixture",
            "QUALITY_INPUT_SOURCE_SHA": "c" * 40, "QUALITY_INPUT_JUNIT_REQUIRED": "true",
            "QUALITY_INPUT_ALLURE_REQUIRED": "true", "QUALITY_INPUT_CPU_LIMIT": "4",
            "QUALITY_INPUT_MEMORY_LIMIT": "12GiB", "QUALITY_INPUT_DISK_LIMIT": "24GiB",
            "PERSONAL_API_KEY": "must-never-enter-container", "GH_TOKEN": "must-never-enter-container",
        }
        candidate = self.runtime / f"supplementary-candidate/1269461997/123/1/heavy/{self.controller_sha}"
        candidate.mkdir(parents=True)
        (candidate / "candidate.tar.gz").write_bytes(b"fixture")
        self.candidate = candidate

    def invoke(self, mode="--quality-incus-v1", **changes):
        return subprocess.run(
            ["/bin/bash", str(WRAPPER), mode, str(self.action)],
            cwd=self.workspace, env={**self.environment, **changes},
            capture_output=True, text=True, check=False, timeout=10,
        )

    def calls(self):
        return [json.loads(line) for line in self.trace.read_text().splitlines()] if self.trace.exists() else []

    def test_full_context_uses_exact_pinned_sandbox_and_only_two_outputs(self):
        result = self.invoke()
        self.assertEqual(0, result.returncode, result.stderr)
        runs = [call for call in self.calls() if call[0] == "run"]
        self.assertEqual(2, len(runs))
        self.assertIn("QUALITY_CONTEXT_PHASE=preflight", runs[0])
        self.assertIn("none", runs[0])
        self.assertNotIn("destination=/candidate", " ".join(runs[0]))
        runtime = runs[1]
        image = re.search(r'^COPILOT_DEVTOOL_IMAGE = "([^"]+)"$', (ROOT / "scripts/lit-push-ready.py").read_text(), re.MULTILINE).group(1)
        self.assertIn(image, runtime)
        self.assertEqual([image, "python3", "/controller/run-cell.py"], runtime[-3:])
        for required in ("--read-only", "ALL", "no-new-privileges=true", f"{self.runner_uid}:{self.runner_gid}"):
            self.assertIn(required, runtime)
        mounts = [runtime[i + 1] for i, value in enumerate(runtime[:-1]) if value == "--mount"]
        for target in ("/workspace", "/candidate", "/controller", "/incus"):
            self.assertTrue(any(f"destination={target},readonly" in mount for mount in mounts))
        self.assertTrue(any("destination=/quality" in mount and "readonly" not in mount for mount in mounts))
        self.assertNotIn("PERSONAL_API_KEY", " ".join(runtime))
        self.assertNotIn("GH_TOKEN", " ".join(runtime))
        self.assertNotIn(str(self.output), " ".join(runtime))
        self.assertEqual(2, len(self.output.read_text().splitlines()))

    def test_root_runner_stops_before_any_engine_call(self):
        result = self.invoke(FIXTURE_RUNNER_UID="0")
        self.assertNotEqual(0, result.returncode)
        self.assertIn("non-root runner required", result.stderr)
        self.assertEqual([], self.calls())
        self.assertEqual("", self.output.read_text())

    def test_foreign_context_owner_stops_before_any_engine_call(self):
        result = self.invoke(FIXTURE_FOREIGN_OWNER=str(self.context / "client.key"))
        self.assertNotEqual(0, result.returncode)
        self.assertIn("foreign context ownership", result.stderr)
        self.assertEqual([], self.calls())
        self.assertEqual("", self.output.read_text())

    def test_untrusted_action_identity_stops_before_any_engine_call(self):
        result = self.invoke(QUALITY_ACTION_REPOSITORY="foreign/action")
        self.assertNotEqual(0, result.returncode)
        self.assertEqual([], self.calls())
        self.assertEqual("", self.output.read_text())

    def test_retired_repository_or_action_owner_stops_before_engine(self):
        for key in ("GITHUB_REPOSITORY", "QUALITY_ACTION_REPOSITORY"):
            with self.subTest(key=key):
                result = self.invoke(**{key: "lightning-it/modulix-validation"})
                self.assertNotEqual(0, result.returncode)
                self.assertEqual([], self.calls())
                self.assertEqual("", self.output.read_text())

    def test_complete_retired_owner_tuple_stops_before_engine(self):
        retired = self.root / f"work/_actions/lightning-it/modulix-validation/{self.action_sha}/.github/actions/run-quality-profile"
        retired.parent.mkdir(parents=True)
        self.action.rename(retired)
        self.action = retired
        result = self.invoke(
            GITHUB_REPOSITORY="lightning-it/modulix-validation",
            QUALITY_ACTION_REPOSITORY="lightning-it/modulix-validation",
            QUALITY_ACTION_ROOT=str(retired),
        )
        self.assertNotEqual(0, result.returncode)
        self.assertEqual([], self.calls())
        self.assertEqual("", self.output.read_text())

    def test_retired_native_action_path_stops_before_engine(self):
        retired = self.root / f"work/_actions/lightning-it/modulix-validation/{self.action_sha}/.github/actions/run-quality-profile"
        retired.parent.mkdir(parents=True)
        self.action.rename(retired)
        self.action = retired
        result = self.invoke(QUALITY_ACTION_ROOT=str(retired))
        self.assertNotEqual(0, result.returncode)
        self.assertEqual([], self.calls())
        self.assertEqual("", self.output.read_text())

    def test_unknown_quality_api_fails_before_engine(self):
        result = self.invoke(mode="--quality-incus-v2")
        self.assertNotEqual(0, result.returncode)
        self.assertEqual([], self.calls())

    def test_invalid_identity_inputs_and_sandbox_overrides_never_reach_engine(self):
        for changes in (
            {"QUALITY_ACTION_REF": "main"},
            {"QUALITY_CONTROLLER_SHA": "d" * 40},
            {"GITHUB_RUN_ATTEMPT": "2"},
            {"GITHUB_REF_PROTECTED": "false"},
            {"QUALITY_INPUT_SOURCE_SHA": "main"},
            {"QUALITY_INPUT_TARGET": "../escape"},
            {"QUALITY_INPUT_IMAGE": "images:fixture\nTOKEN=value"},
            {"QUALITY_INCUS_CONFIG_DIR": str(self.runtime)},
            {"GITHUB_OUTPUT": str(self.root / "outside")},
            {"WUNDER_DEVTOOLS_WORKSPACE_MODE": "rw"},
            {"WUNDER_DEVTOOLS_DOCKER_SOCKET": "required"},
            {"WUNDER_DEVTOOLS_PRIVILEGED": "1"},
        ):
            with self.subTest(changes=changes):
                result = self.invoke(**changes)
                self.assertNotEqual(0, result.returncode)
                self.assertEqual([], self.calls())
                self.assertEqual("", self.output.read_text())

    def test_private_context_mode_and_candidate_symlink_fail_before_engine(self):
        key = self.context / "client.key"
        key.chmod(0o644)
        self.assertNotEqual(0, self.invoke().returncode)
        key.chmod(0o600)
        (self.candidate / "foreign").symlink_to(self.output)
        self.assertNotEqual(0, self.invoke().returncode)
        self.assertEqual([], self.calls())

    def test_check_needs_no_candidate_and_never_starts_runtime(self):
        (self.candidate / "candidate.tar.gz").unlink()
        self.candidate.rmdir()
        result = self.invoke(mode="--quality-incus-v1-check")
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual(1, len(self.calls()))
        self.assertEqual("", self.output.read_text())
        self.assertEqual([], list(self.runtime.glob("quality-cell.*")))

    def test_unreadable_candidate_directory_stops_before_engine(self):
        blocked = self.candidate / "unreadable"
        blocked.mkdir()
        (blocked / "hidden").write_text("must be inspected\n")
        blocked.chmod(0)
        try:
            result = self.invoke()
        finally:
            blocked.chmod(0o700)
        self.assertIn("Permission denied", result.stderr)
        self.assertNotEqual(0, result.returncode)
        self.assertEqual([], self.calls())
        self.assertEqual("", self.output.read_text())

    def test_unreadable_package_directory_never_publishes_outputs(self):
        self.engine.write_text(self.engine.read_text().replace(
            "  (state/'package/SHA256SUMS').write_text('fixture')",
            "  (state/'package/SHA256SUMS').write_text('fixture')\n"
            "  blocked = state/'package/unreadable'\n"
            "  blocked.mkdir(); (blocked/'hidden').write_text('must be inspected')\n"
            "  blocked.chmod(0)",
        ))
        try:
            result = self.invoke()
        finally:
            for blocked in self.runtime.glob("quality-cell.*/package/unreadable"):
                blocked.chmod(0o700)
        self.assertIn("Permission denied", result.stderr)
        self.assertNotEqual(0, result.returncode)
        self.assertEqual(2, len(self.calls()))
        self.assertEqual("", self.output.read_text())

    def test_other_find_producer_failures_stop_even_after_plausible_output(self):
        # A real find may emit a complete-looking prefix before reporting an
        # inspection error. Preserve that output but inject its failed status.
        find = self.binary / "find"
        for arguments in (
            [str(self.context), "-print0"],
            [str(self.action), "-mindepth", "1", "-maxdepth", "1"],
            [str(self.context), "-type", "f"],
            [str(self.context), "-type", "d"],
        ):
            with self.subTest(arguments=arguments):
                find.write_text(
                    "#!/usr/bin/env python3\nimport subprocess, sys\n"
                    "result = subprocess.run(['/usr/bin/find', *sys.argv[1:]], check=False)\n"
                    f"raise SystemExit(1 if sys.argv[1:] == {arguments!r} else result.returncode)\n"
                )
                find.chmod(0o755)
                result = self.invoke(mode="--quality-incus-v1-check")
                self.assertNotEqual(0, result.returncode)
                self.assertIn("traversal failed", result.stderr)
                self.assertEqual([], self.calls())
                self.assertEqual("", self.output.read_text())

    def test_failed_offline_preflight_does_not_create_cell_or_start_runtime(self):
        content = self.engine.read_text().replace(
            "print('PROTECTED_INCUS_PREFLIGHT=1'); raise SystemExit(0)",
            "print('required pinned tool unavailable: incus'); raise SystemExit(1)",
        )
        self.engine.write_text(content)
        self.assertNotEqual(0, self.invoke().returncode)
        self.assertEqual(1, len(self.calls()))
        self.assertEqual([], list(self.runtime.glob("quality-cell.*")))
        self.assertEqual("", self.output.read_text())

    def test_unrecognized_container_result_never_becomes_host_output(self):
        self.engine.write_text(self.engine.read_text().replace(
            "'package_directory':'/quality/package'", "'package_directory':'../../escape'"
        ))
        self.assertNotEqual(0, self.invoke().returncode)
        self.assertEqual("", self.output.read_text())

    def test_result_bytes_are_not_coerced_into_canonical_json(self):
        original = self.engine.read_text()
        mutations = {
            "nul-true": "raw.replace(b'true', b'tr\\x00ue')",
            "nul-false": "raw.replace(b'true', b'fa\\x00lse')",
            "nul-prefix": "b'\\x00' + raw",
            "nul-suffix": "raw + b'\\x00'",
            "prefix": "b'junk' + raw",
            "trailing-junk": "raw + b'junk'",
            "extra-newline": "raw + b'\\n'",
            "missing-newline": "raw.rstrip(b'\\n')",
        }
        for name, expression in mutations.items():
            with self.subTest(mutation=name):
                self.output.write_text("")
                self.engine.write_text(original +
                    "  result_path = state/'control/result.json'\n"
                    "  raw = result_path.read_bytes()\n"
                    f"  result_path.write_bytes({expression})\n")
                result = self.invoke()
                self.assertNotEqual(0, result.returncode)
                self.assertEqual("", self.output.read_text())

    def test_canonical_diagnostic_results_preserve_outputs_and_failure(self):
        original = self.engine.read_text()
        for content in (
            original.replace("'success':True", "'success':False"),
            original + "raise SystemExit(23)\n",
        ):
            with self.subTest(engine=content[-40:]):
                self.engine.write_text(content)
                result = self.invoke()
                self.assertNotEqual(0, result.returncode)
                self.assertEqual(2, len(self.output.read_text().splitlines()))
                self.output.write_text("")

    def test_existing_profile_interface_accepts_vm_dots_case_digest_and_limits(self):
        result = self.invoke(
            mode="--quality-incus-v1-check",
            QUALITY_INPUT_SCENARIO="Keycloak.26",
            QUALITY_INPUT_TARGET="Rocky_9.4",
            QUALITY_INPUT_INSTANCE_TYPE="vm",
            QUALITY_INPUT_IMAGE="images:Rocky/9+cloud@sha256:" + "d" * 64,
            QUALITY_INPUT_CPU_LIMIT="999",
            QUALITY_INPUT_MEMORY_LIMIT="1024KiB",
            QUALITY_INPUT_DISK_LIMIT="10TiB",
        )
        self.assertEqual(0, result.returncode, result.stderr)

    def test_check_requires_inputs_before_download_and_native_context(self):
        for changes in ({"QUALITY_INPUT_PROFILE": ""}, {"QUALITY_ACTION_REF": ""}):
            self.assertNotEqual(0, self.invoke(mode="--quality-incus-v1-check", **changes).returncode)
            self.assertEqual([], self.calls())

    def test_rootless_podman_is_explicitly_unsupported_before_mount(self):
        podman = self.binary / "podman"
        podman.write_text(self.engine.read_text().replace(
            "if args[0] == 'info': raise SystemExit(0)",
            "if args[0] == 'info': print('true'); raise SystemExit(0)",
        ))
        podman.chmod(0o755)
        result = self.invoke(WUNDER_CONTAINER_ENGINE="podman")
        self.assertNotEqual(0, result.returncode)
        self.assertIn("does not admit rootless Podman", result.stderr)
        self.assertEqual(1, len(self.calls()))
        self.assertEqual("info", self.calls()[0][0])
        self.assertEqual("", self.output.read_text())

    def test_actual_preflight_program_checks_tls_and_run_binding_offline(self):
        import datetime

        result = self.invoke(mode="--quality-incus-v1-check")
        self.assertEqual(0, result.returncode, result.stderr)
        code = self.calls()[0][-1].replace("pathlib.Path('/incus')", f"pathlib.Path({str(self.context)!r})")
        subprocess.run(
            ["openssl", "req", "-x509", "-newkey", "rsa:2048", "-nodes", "-days", "1",
             "-subj", "/CN=offline-fixture", "-keyout", str(self.context / "client.key"),
             "-out", str(self.context / "client.crt")],
            check=True, capture_output=True,
        )
        (self.context / "servercerts/quality.crt").write_bytes((self.context / "client.crt").read_bytes())
        binding = {
            "schema": 1, "repository": self.environment["GITHUB_REPOSITORY"],
            "run_id": "123", "run_attempt": "1", "server": "https://offline.invalid:8443",
            "project": "quality-fixture",
            "expires_at": (datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(minutes=30)).isoformat(),
        }
        (self.context / "binding.json").write_text(json.dumps(binding))
        (self.context / "config.yml").write_text(
            "default-remote: quality\nremotes:\n"
            "  images:\n    addr: https://images.linuxcontainers.org\n"
            "    protocol: simplestreams\n    public: true\n  quality:\n"
            "    addr: https://offline.invalid:8443\n    project: quality-fixture\n"
            "    auth_type: tls\n    protocol: incus\n    public: false\n"
        )
        # Tool availability is isolated from semantic validation; no Incus command
        # or network call is executed by this actual preflight program.
        program = "import unittest.mock as m\nwith m.patch('shutil.which', return_value='/fixture/tool'):\n exec(" + repr(code) + ")"
        def execute():
            return subprocess.run([sys.executable, "-c", program], env=self.environment, capture_output=True, text=True, check=False)
        self.assertEqual(0, execute().returncode)
        for mutation in ({"run_attempt": "2"}, {"server": "https://user:password@offline.invalid"}, {"expires_at": "2000-01-01T00:00:00Z"}):
            with self.subTest(mutation=mutation):
                (self.context / "binding.json").write_text(json.dumps({**binding, **mutation}))
                self.assertNotEqual(0, execute().returncode)
        (self.context / "binding.json").write_text(json.dumps(binding))
        configuration = self.context / "config.yml"
        boolean_configuration = configuration.read_text()
        for numeric in ("0", "0.0"):
            with self.subTest(public=numeric):
                configuration.write_text(boolean_configuration.replace("public: false", "public: " + numeric))
                self.assertNotEqual(0, execute().returncode)
        configuration.write_text(boolean_configuration)
        self.assertEqual(0, execute().returncode)
        for original, changed in (
            ("https://images.linuxcontainers.org", "https://foreign.invalid"),
            ("protocol: simplestreams", "protocol: incus"),
            ("public: true", "public: 1"),
            ("public: true", "public: false"),
        ):
            with self.subTest(image_remote=changed):
                configuration.write_text(boolean_configuration.replace(original, changed))
                self.assertNotEqual(0, execute().returncode)
        configuration.write_text(boolean_configuration)
        configuration.write_text(configuration.read_text().replace("auth_type:", "auth-type:"))
        self.assertNotEqual(0, execute().returncode)


if __name__ == "__main__":
    unittest.main()
