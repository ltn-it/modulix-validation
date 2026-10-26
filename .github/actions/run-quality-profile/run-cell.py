"""Execute the complete cell only inside the admitted Devtools mount contract."""

from __future__ import annotations

import json
import os
import re
import shutil
import signal
import stat
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit

import yaml

EXPRESSION = re.compile(r"\$\{\{\s*([^{}]+?)\s*\}\}")
IMAGE = re.compile(
    r"quay\.io/l-it/ee-wunder-devtools-ubi9:v[0-9]+\.[0-9]+\.[0-9]+@sha256:[0-9a-f]{64}\Z"
)
INPUTS = (
    "profile",
    "scenario",
    "target",
    "target-disposition",
    "roles",
    "image",
    "instance-type",
    "candidate-artifact",
    "source-sha",
    "junit-required",
    "allure-required",
    "cpu-limit",
    "memory-limit",
    "disk-limit",
)

# Cancellation has a smaller fixed finalization budget than a normal phase.
# Expiry retains the private host-backed state for an owner-driven recovery.
CANCEL_FINALIZER_SECONDS = 120
PROCESS_STOP_SECONDS = 2
OWNED_FINALIZERS = {"cleanup", "destroy"}


class CellCancelled(KeyboardInterrupt):
    def __init__(self, signum, results=None):
        super().__init__("quality cell cancelled")
        self.signum = signum
        self.results = results or {}


class Cancellation:
    def __enter__(self):
        self.signum = None
        self.active = None
        self.finalizing = False
        self.previous = {kind: signal.getsignal(kind) for kind in (signal.SIGINT, signal.SIGTERM)}
        for kind in self.previous:
            signal.signal(kind, self.request)
        return self

    def request(self, signum, _frame):
        first = self.signum is None
        self.signum = self.signum or signum
        # Between steps (including process creation), record the request and
        # inspect it before another ordinary effect. During owned finalizers,
        # defer repeated signals to their fixed timeout instead of skipping them.
        if first and self.active is not None and not self.finalizing:
            raise CellCancelled(self.signum)

    def __exit__(self, *_error):
        for kind, previous in self.previous.items():
            signal.signal(kind, previous)


def stop_owned_process(process):
    """Stop only the new session created for this exact phase, descendants too."""
    try:
        os.killpg(process.pid, signal.SIGTERM)
    except ProcessLookupError:
        pass
    try:
        process.wait(timeout=PROCESS_STOP_SECONDS)
    except subprocess.TimeoutExpired:
        pass
    # A shell can exit while a descendant ignores TERM. The owned session must
    # also be gone before a finalizer starts against the same lifecycle state.
    try:
        os.killpg(process.pid, signal.SIGKILL)
    except ProcessLookupError:
        pass
    process.wait(timeout=PROCESS_STOP_SECONDS)


def run_owned_process(command, workspace, environment, cancellation):
    process = None
    try:
        process = subprocess.Popen(
            ["/bin/bash", "-e", "-c", command], cwd=workspace,
            env=environment, start_new_session=True,
        )
        cancellation.active = process
        if cancellation.signum and not cancellation.finalizing:
            raise CellCancelled(cancellation.signum)
        timeout = CANCEL_FINALIZER_SECONDS if cancellation.finalizing else None
        try:
            return process.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            stop_owned_process(process)
            return 124
    except BaseException:
        if process is not None:
            stop_owned_process(process)
        raise
    finally:
        cancellation.active = None


def private_values(path: Path, *, environment: bool = False) -> dict[str, str]:
    if not path.exists():
        return {}
    if path.is_symlink() or not path.is_file() or path.stat().st_size > 131072:
        raise ValueError("unsafe private cell output")
    result = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        key, separator, value = line.partition("=")
        if not separator:
            raise ValueError("malformed private cell output")
        if environment:
            allowed = re.fullmatch(
                r"(?:QUALITY|MOLECULE|KEYCLOAK)_[A-Z_]+|ANSIBLE_COLLECTIONS_PATH", key
            )
            if key in {
                "QUALITY_DEVTOOLS_IMAGE",
                "QUALITY_HOST_UID",
                "QUALITY_EFFECTIVE_UID",
                "QUALITY_EFFECTIVE_GID",
                "QUALITY_INCUS_PROJECT",
                "MOLECULE_ANSIBLE_ARGS_STRICT_MODE",
            } or key.startswith("QUALITY_INPUT_"):
                allowed = None
        else:
            allowed = re.fullmatch(r"[a-z][a-z0-9_-]*", key)
        if not allowed or "\x00" in value or "\r" in value:
            raise ValueError("unexpected private cell output key or value")
        result[key] = value
    return result


def expand(value: str, inputs: dict[str, str], results: dict) -> str:
    def replace(match):
        parts = match.group(1).strip().split(".")
        if len(parts) == 2 and parts[0] == "inputs" and parts[1] in inputs:
            return inputs[parts[1]]
        if len(parts) in (3, 4) and parts[0] == "steps" and parts[1] in results:
            step = results[parts[1]]
            if parts[2:] == ["outcome"]:
                return step["outcome"]
            if len(parts) == 4 and parts[2] == "outputs":
                return step["outputs"].get(parts[3], "")
        raise ValueError("unbound cell expression")

    return EXPRESSION.sub(replace, value)


def run_steps(
    steps: list[dict],
    inputs: dict[str, str],
    environment: dict[str, str],
    control: Path,
    workspace: Path,
):
    """Preserve normal step failure and unconditional finalizers inside one container."""
    results = {}
    failed = False
    environment_file = control / "environment"
    admitted_environment = dict(environment)
    identities = set()
    for step in steps:
        identity = step["id"]
        if (not isinstance(identity, str) or not re.fullmatch(r"[a-z][a-z0-9-]*", identity)
                or identity in identities or step.get("if") not in (None, "always()")):
            raise ValueError("invalid cell step identity or condition")
        identities.add(identity)
    with Cancellation() as cancellation:
        control.mkdir(mode=0o700, parents=True, exist_ok=True)
        for step in steps:
            identity = step["id"]
            always = step.get("if") == "always()"
            cancelled = cancellation.signum is not None
            if (failed and not always) or (cancelled and (not always or identity not in OWNED_FINALIZERS)):
                results[identity] = {"outcome": "skipped", "outputs": {}}
                continue
            output = control / f"{identity}.output"
            damaged = False
            try:
                admitted_environment.update(private_values(environment_file, environment=True))
            except (OSError, ValueError):
                failed, damaged = True, True
            if damaged and not always:
                results[identity] = {"outcome": "failure", "outputs": {}}
                continue
            local = {**admitted_environment, "GITHUB_ENV": str(environment_file), "GITHUB_OUTPUT": str(output)}
            try:
                for key, value in step.get("env", {}).items():
                    local[key] = expand(str(value), inputs, results)
                command = expand(step["run"], inputs, results)
                cancellation.finalizing = cancelled
                code = run_owned_process(command, workspace, local, cancellation)
                outcome = "success" if code == 0 and not damaged else "failure"
                outputs = private_values(output)
            except KeyboardInterrupt as error:
                cancellation.signum = cancellation.signum or getattr(error, "signum", signal.SIGINT)
                outcome, outputs = "failure", {}
            except (OSError, ValueError, KeyError):
                outcome, outputs = "failure", {}
            results[identity] = {"outcome": outcome, "outputs": outputs}
            failed |= outcome != "success"
        if cancellation.signum:
            raise CellCancelled(cancellation.signum, results)
    return results


def finalizers_confirmed(results):
    return all(
        results.get(name, {}).get("outcome") == "success"
        and results.get(name, {}).get("outputs", {}).get("exit_code") == "0"
        for name in OWNED_FINALIZERS
    )


def finish_owned_state(cell, inputs, environment, results, *, cancelled):
    """Keep unconfirmed teardown state on the existing private host-backed cell."""
    if finalizers_confirmed(results):
        for name in ("tmp", "artifacts"):
            path = cell / name
            if path.exists():
                shutil.rmtree(path)
        return
    recovery = cell / "recovery"
    recovery.mkdir(mode=0o700)
    # Never copy RAM-only command files, generated passwords or TLS material.
    # The immutable source and run tuple can reconstruct ownership while the
    # existing private lifecycle and diagnostic paths remain in place.
    payload = {
        "schema": 1,
        "status": "teardown-unconfirmed",
        "cancelled": cancelled,
        "repository": environment.get("GITHUB_REPOSITORY"),
        "workflow": environment.get("GITHUB_WORKFLOW"),
        "run_id": environment.get("GITHUB_RUN_ID"),
        "run_attempt": environment.get("GITHUB_RUN_ATTEMPT"),
        "project": environment.get("QUALITY_INCUS_PROJECT"),
        "source_sha": inputs.get("source-sha"),
        "profile": inputs.get("profile"),
        "scenario": inputs.get("scenario"),
        "target": inputs.get("target"),
        "private_state": [name for name in ("tmp", "artifacts") if (cell / name).exists()],
        "capture_confirmed": results.get("cleanup", {}).get("outcome") == "success"
            and results.get("cleanup", {}).get("outputs", {}).get("exit_code") == "0",
        "destroy_confirmed": results.get("destroy", {}).get("outcome") == "success"
            and results.get("destroy", {}).get("outputs", {}).get("exit_code") == "0",
    }
    descriptor = os.open(recovery / "context.json", os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
        json.dump(payload, stream, sort_keys=True)
        stream.write("\n")


def execute_owned_cell(steps, inputs, environment, control, workspace, cell):
    """Finalize owned resources before disposal; cancellation is never success."""
    try:
        results = run_steps(steps, inputs, environment, control, workspace)
    except CellCancelled as error:
        finish_owned_state(cell, inputs, environment, error.results, cancelled=True)
        return 128 + error.signum
    except BaseException:
        finish_owned_state(cell, inputs, environment, {}, cancelled=True)
        raise
    finish_owned_state(cell, inputs, environment, results, cancelled=False)
    codes = (("molecule", "exit_code"), ("cleanup", "exit_code"),
             ("destroy", "exit_code"), ("evidence", "exit_code"))
    success = all(result["outcome"] == "success" for result in results.values())
    success &= all(results[name]["outputs"].get(key) == "0" for name, key in codes)
    final_environment = private_values(control / "environment", environment=True)
    publication = {"schema": 1, "result_artifact": final_environment.get("QUALITY_RESULT_ARTIFACT", ""),
                   "package_directory": "/quality/package", "success": success}
    result_root = cell / "control"
    result_root.mkdir(mode=0o700)
    (result_root / "result.json").write_text(json.dumps(publication, sort_keys=True) + "\n")
    return 0 if success else 1


def validate_transport(
    environment: dict[str, str], config_root: Path, *, now: datetime | None = None
) -> str:
    """Require a later custodian-provisioned, run-bound TLS context; never discover access."""
    image = environment.get("QUALITY_DEVTOOLS_IMAGE", "")
    if not IMAGE.fullmatch(image):
        raise ValueError("Devtools image is not bound to an immutable managed digest")
    if environment.get("INCUS_CONF") != str(config_root):
        raise ValueError("Incus configuration escaped the admitted mount")
    if (
        int(environment["QUALITY_EFFECTIVE_UID"]) != os.getuid()
        or int(environment["QUALITY_EFFECTIVE_GID"]) != os.getgid()
    ):
        raise ValueError(
            "Devtools UID/GID differs from the admitted controller identity"
        )
    if int(environment["QUALITY_HOST_UID"]) <= 0:
        raise ValueError("quality execution requires a nonroot host identity")
    expected = {"binding.json", "config.yml", "client.crt", "client.key", "servercerts"}
    if (
        config_root.is_symlink()
        or not config_root.is_dir()
        or {p.name for p in config_root.iterdir()} != expected
    ):
        raise ValueError("approved Incus transport has an unexpected private file set")
    if {path.name for path in (config_root / "servercerts").iterdir()} != {
        "quality.crt"
    }:
        raise ValueError("approved Incus transport contains foreign server trust")
    for path in (config_root, *config_root.rglob("*")):
        metadata = path.lstat()
        if path.is_symlink() or not (
            stat.S_ISDIR(metadata.st_mode) or stat.S_ISREG(metadata.st_mode)
        ):
            raise ValueError("approved Incus transport contains a link or special file")
        if metadata.st_mode & 0o077 or metadata.st_uid != os.getuid():
            raise ValueError(
                "approved Incus transport is not private to the controller UID"
            )
        if stat.S_ISREG(metadata.st_mode) and not 0 < metadata.st_size <= 65536:
            raise ValueError("approved Incus transport file is missing or oversized")
    binding = json.loads((config_root / "binding.json").read_text())
    keys = {
        "schema",
        "repository",
        "run_id",
        "run_attempt",
        "server",
        "project",
        "expires_at",
    }
    if (
        set(binding) != keys
        or type(binding["schema"]) is not int
        or binding["schema"] != 1
    ):
        raise ValueError("approved Incus binding shape differs")
    for key, variable in (
        ("repository", "GITHUB_REPOSITORY"),
        ("run_id", "GITHUB_RUN_ID"),
        ("run_attempt", "GITHUB_RUN_ATTEMPT"),
    ):
        if not isinstance(binding[key], str) or binding[key] != environment[variable]:
            raise ValueError(
                "approved Incus transport belongs to a different run or attempt"
            )
    server = urlsplit(binding["server"])
    if (
        server.scheme != "https"
        or not server.hostname
        or server.username
        or server.password
        or server.query
        or server.fragment
    ):
        raise ValueError(
            "approved Incus transport is not an authenticated HTTPS remote"
        )
    if not re.fullmatch(r"[a-z][a-z0-9-]{0,62}", binding["project"]):
        raise ValueError("approved Incus project identity is invalid")
    expiry = datetime.fromisoformat(binding["expires_at"].replace("Z", "+00:00"))
    if (
        expiry.tzinfo is None
        or not 0
        < (expiry - (now or datetime.now(timezone.utc))).total_seconds()
        <= 5400
    ):
        raise ValueError(
            "approved Incus transport is expired or exceeds the job budget"
        )
    configuration = yaml.safe_load((config_root / "config.yml").read_text())
    if not isinstance(configuration, dict) or set(configuration) != {
        "default-remote", "remotes"
    }:
        raise ValueError("approved Incus configuration shape differs")
    if not isinstance(configuration["remotes"], dict):
        raise TypeError("approved Incus remotes shape differs")
    remote = configuration.get("remotes", {}).get("quality", {})
    if (
        configuration.get("default-remote") != "quality"
        or set(configuration.get("remotes", {})) != {"quality", "images"}
        or not isinstance(remote, dict)
        or remote.get("addr") != binding["server"]
        or remote.get("project") != binding["project"]
        or set(remote) != {"addr", "auth_type", "project", "protocol", "public"}
        or remote["auth_type"] != "tls"
        or remote["protocol"] != "incus"
        or remote["public"] is not False
        or not (config_root / "servercerts/quality.crt").is_file()
    ):
        raise ValueError("approved Incus remote, project or TLS trust differs")
    images = configuration["remotes"]["images"]
    if (
        images != {
            "addr": "https://images.linuxcontainers.org",
            "protocol": "simplestreams",
            "public": True,
        }
        or images["public"] is not True
    ):
        raise ValueError("approved public Incus image remote differs")
    for name in ("client.crt", "client.key", "servercerts/quality.crt"):
        if not 0 < (config_root / name).stat().st_size <= 65536:
            raise ValueError("approved Incus TLS material is missing or oversized")
    return binding["project"]


def prepare_molecule_phase(phase: str, directory: Path) -> None:
    """Carry the admitted target through the installed Molecule executor interface."""
    from molecule import shell
    from molecule.config import Config

    project = os.environ.get("QUALITY_INCUS_PROJECT", "")
    scenario = os.environ.get("QUALITY_SCENARIO", "")
    if (
        phase not in {"test", "cleanup", "destroy"}
        or not re.fullmatch(r"[a-z][a-z0-9-]{0,62}", project)
        or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,62}", scenario)
        or os.environ.get("MOLECULE_ANSIBLE_ARGS_STRICT_MODE")
    ):
        raise ValueError("Molecule target or executor argument mode is not admitted")
    # Explicit -c replaces CLI discovery. Retain the actual installed CLI's
    # selected defaults, including collection extensions or HOME when applicable.
    defaults = next(p.default for p in shell.main.params if p.name == "base_config")
    if not isinstance(defaults, (list, tuple)) or any(
        not isinstance(path, str) for path in defaults
    ):
        raise ValueError("unsupported Molecule base configuration discovery")
    source = Path("molecule") / scenario / "molecule.yml"
    if not source.is_file():
        raise ValueError("Molecule scenario configuration is absent")
    args = {"base_config": list(defaults)}
    configuration = Config(str(source), args=args)
    provisioner = configuration.config["provisioner"]
    ansible = configuration.config["ansible"]
    if (
        ansible["executor"]["args"].get("ansible_playbook")
        or {"extra-vars", "e"} & set(provisioner.get("options", {}))
        or ansible.get("env", {}).get("MOLECULE_ANSIBLE_ARGS_STRICT_MODE")
    ):
        raise ValueError("source Molecule arguments conflict with the admitted target")
    variables = directory / "incus-vars.json"
    overlay = directory / "molecule.yml"
    executor_args = ["--extra-vars", "@" + str(variables)]
    # The parent is a fresh private tmpfs directory; exclusive writes and the
    # process umask keep the carrier out of Source and retained evidence.
    with variables.open("x", encoding="utf-8") as stream:
        json.dump({"ansible_incus_remote": "quality", "ansible_incus_project": project}, stream)
    with overlay.open("x", encoding="utf-8") as stream:
        yaml.safe_dump({"ansible": {"executor": {"args": {"ansible_playbook": executor_args}}}}, stream)
    final = Config(str(source), args={"base_config": [*defaults, str(overlay)]})
    if final.config["ansible"]["executor"]["args"]["ansible_playbook"] != executor_args:
        raise ValueError("source Molecule configuration replaced the private target carrier")
    command = ["molecule"]
    for path in [*defaults, str(overlay)]:
        command.extend(["--base-config", path])
    command.extend([phase, "-s", scenario])
    if phase == "test":
        command.extend(["--destroy", "never"])
    with (directory / "argv").open("xb") as stream:
        stream.write(b"\0".join(part.encode() for part in command) + b"\0")


def main() -> int:
    os.umask(0o077)
    environment = dict(os.environ)
    expected_paths = {
        "GITHUB_WORKSPACE": "/workspace",
        "RUNNER_TEMP": "/quality/tmp",
        "HOME": "/tmp/wunder",
        "TMPDIR": "/tmp/wunder",
    }
    if any(environment.get(key) != value for key, value in expected_paths.items()):
        raise ValueError("quality paths differ from the admitted container namespace")
    for name in ("/", "/workspace", "/candidate", "/controller", "/incus"):
        if not Path(name).is_dir() or os.access(name, os.W_OK):
            raise ValueError(
                "quality source, candidate, controller and credentials must be read-only"
            )
    if not Path("/quality").is_dir() or not os.access("/quality", os.W_OK):
        raise ValueError("quality output requires its own writable cell mount")
    if any(
        (Path("/quality") / name).exists()
        for name in ("control", "tmp", "artifacts", "package", "recovery")
    ):
        raise ValueError(
            "quality cell output is not fresh; previous evidence cannot be reused"
        )
    for command in (
        "python3",
        "ansible",
        "ansible-galaxy",
        "molecule",
        "incus",
        "openssl",
        "timeout",
        "tar",
    ):
        if shutil.which(command) is None:
            raise ValueError(f"required managed Devtools command is absent: {command}")
    environment["QUALITY_INCUS_PROJECT"] = validate_transport(environment, Path("/incus"))
    inputs = {
        name: environment[f"QUALITY_INPUT_{name.upper().replace('-', '_')}"]
        for name in INPUTS
    }
    if not re.fullmatch(r"[0-9a-f]{40}|[0-9a-f]{64}", inputs["source-sha"]):
        raise ValueError("quality source SHA is invalid")
    head = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd="/workspace",
        capture_output=True,
        text=True,
        check=True,
    )
    clean = subprocess.run(
        ["git", "status", "--porcelain=v1", "--untracked-files=all"],
        cwd="/workspace",
        capture_output=True,
        text=True,
        check=True,
    )
    if head.stdout.strip() != inputs["source-sha"] or clean.stdout:
        raise ValueError("quality source is not the clean exact reviewed revision")
    steps = yaml.safe_load(Path("/controller/profile-steps.yml").read_text())["steps"]
    # Command files contain generated secrets; keep them in the isolated home
    # tmpfs, never in the host-mounted evidence or output directory.
    control = Path("/tmp/wunder/quality-control")
    return execute_owned_cell(
        steps, inputs, environment, control, Path("/workspace"), Path("/quality")
    )


if __name__ == "__main__":
    try:
        if len(sys.argv) == 4 and sys.argv[1] == "--molecule-phase":
            os.umask(0o077)
            prepare_molecule_phase(sys.argv[2], Path(sys.argv[3]))
        elif len(sys.argv) == 1:
            raise SystemExit(main())
        else:
            raise ValueError("unsupported private quality invocation")
    except (OSError, ValueError, KeyError, TypeError) as error:
        raise SystemExit(f"quality cell failed closed: {error}") from None
