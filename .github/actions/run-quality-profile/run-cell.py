"""Execute the complete cell only inside the admitted Devtools mount contract."""

from __future__ import annotations

import json
import os
import re
import shutil
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
    control.mkdir(mode=0o700, parents=True, exist_ok=True)
    results = {}
    failed = False
    environment_file = control / "environment"
    admitted_environment = dict(environment)
    for step in steps:
        identity = step["id"]
        if identity in results or step.get("if") not in (None, "always()"):
            raise ValueError("invalid cell step identity or condition")
        if failed and step.get("if") != "always()":
            results[identity] = {"outcome": "skipped", "outputs": {}}
            continue
        output = control / f"{identity}.output"
        damaged = False
        try:
            admitted_environment.update(
                private_values(environment_file, environment=True)
            )
        except (OSError, ValueError):
            # A damaged command file must not prevent an owned finalizer from
            # using the last successfully admitted identity and paths.
            failed = True
            damaged = True
        if damaged and step.get("if") != "always()":
            results[identity] = {"outcome": "failure", "outputs": {}}
            continue
        local = {
            **admitted_environment,
            "GITHUB_ENV": str(environment_file),
            "GITHUB_OUTPUT": str(output),
        }
        try:
            for key, value in step.get("env", {}).items():
                local[key] = expand(str(value), inputs, results)
            command = expand(step["run"], inputs, results)
            result = subprocess.run(
                ["/bin/bash", "-e", "-c", command],
                cwd=workspace,
                env=local,
                check=False,
            )
            outcome = "success" if result.returncode == 0 and not damaged else "failure"
            outputs = private_values(output)
        except (OSError, ValueError, KeyError):
            outcome, outputs = "failure", {}
        results[identity] = {"outcome": outcome, "outputs": outputs}
        failed |= outcome != "success"
    return results


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
        or not re.fullmatch(r"[a-z][a-z0-9-]{0,62}", scenario)
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
        for name in ("control", "artifacts", "package")
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
    try:
        results = run_steps(steps, inputs, environment, control, Path("/workspace"))
    finally:
        # The admitted cell was fresh and exclusively owned. Preserve only the
        # packaged redacted result, after target capture and owned destruction.
        for path in (Path("/quality/tmp"), Path("/quality/artifacts")):
            if path.exists():
                shutil.rmtree(path)
    codes = (
        ("molecule", "exit_code"),
        ("cleanup", "exit_code"),
        ("destroy", "exit_code"),
        ("evidence", "exit_code"),
    )
    success = all(result["outcome"] == "success" for result in results.values())
    success &= all(results[name]["outputs"].get(key) == "0" for name, key in codes)
    final_environment = private_values(control / "environment", environment=True)
    publication = {
        "schema": 1,
        "result_artifact": final_environment.get("QUALITY_RESULT_ARTIFACT", ""),
        "package_directory": "/quality/package",
        "success": success,
    }
    result_root = Path("/quality/control")
    result_root.mkdir(mode=0o700)
    (result_root / "result.json").write_text(
        json.dumps(publication, sort_keys=True) + "\n"
    )
    return 0 if success else 1


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
