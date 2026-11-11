"""Execute the complete cell only inside the admitted Devtools mount contract."""

from __future__ import annotations

import json
import hashlib
import os
import re
import shutil
import signal
import stat
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
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
# This trusted child cannot execute the ordinary command until its parent has
# registered the process and explicitly admitted startup. EOF denies startup.
OWNED_SHELL_LAUNCHER = """import os, sys
descriptor = int(sys.argv[1])
token = os.read(descriptor, 1)
os.close(descriptor)
if token != b'1':
    raise SystemExit(125)
os.execv('/bin/bash', ['/bin/bash', '-e', '-c', sys.argv[2]])
"""


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
        self.stopping = False
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
        if first and self.active is not None and not self.finalizing and not self.stopping:
            raise CellCancelled(self.signum)

    def __exit__(self, *_error):
        for kind, previous in self.previous.items():
            signal.signal(kind, previous)


class ProcessQuiescenceError(RuntimeError):
    """An owned session could not be proven inactive; no later effect is safe."""


def require_pidfd_signalling():
    """Admit this kernel/runtime before ordinary effects; no numeric-PID fallback."""
    if not callable(getattr(os, "pidfd_open", None)) or not callable(getattr(signal, "pidfd_send_signal", None)):
        raise ProcessQuiescenceError("identity-bound process signalling unavailable")
    descriptor = None
    try:
        descriptor = os.pidfd_open(os.getpid())
        signal.pidfd_send_signal(descriptor, 0)
    except OSError as error:
        raise ProcessQuiescenceError("identity-bound process signalling unavailable") from error
    finally:
        if descriptor is not None:
            os.close(descriptor)


def signal_owned_member(pid, identity, signum):
    descriptor = None
    try:
        descriptor = os.pidfd_open(pid)
        # Revalidate after opening: a recycled PID must not acquire ownership.
        # Recycling after this check cannot retarget the open kernel handle.
        current = process_identity(Path("/proc") / str(pid))
        if current is not None and current[1:] == identity[1:]:
            signal.pidfd_send_signal(descriptor, signum)
    except ProcessLookupError:
        pass
    except OSError as error:
        raise ProcessQuiescenceError("cannot stop owned process") from error
    finally:
        if descriptor is not None:
            os.close(descriptor)


def process_identity(path):
    try:
        # comm may itself contain spaces and parentheses. The fields after its
        # final ')' are state, ppid, pgrp, session, ... and starttime (index 19).
        fields = (path / "stat").read_text().rpartition(") ")[2].split()
        return fields[0], int(fields[3]), fields[19]
    except (FileNotFoundError, ProcessLookupError):
        return None
    except (OSError, ValueError, IndexError) as error:
        raise ProcessQuiescenceError("cannot inspect owned process state") from error


def owned_session_members(session):
    """GNU timeout changes process group but remains in our fresh session."""
    members = {}
    terminal = set()
    vanished = False
    try:
        paths = list(Path("/proc").iterdir())
    except OSError as error:
        raise ProcessQuiescenceError("owned process inventory unavailable") from error
    for path in paths:
        if not path.name.isdecimal():
            continue
        identity = process_identity(path)
        if identity is None:
            # Its session is now unknown: it might have forked an owned child
            # after this directory listing, so an empty scan is not proof.
            vanished = True
        elif identity[1] == session:
            if identity[0] in {"Z", "X"}:
                terminal.add((int(path.name), identity[2]))
            else:
                members[int(path.name)] = identity
    return members, terminal, vanished


def stop_owned_process(process):
    """Stop every live group in this phase's session and prove quiescence.

    A group-only kill misses GNU timeout's separate group. Check each process
    birth and session before signalling so foreign processes and reused PIDs
    are never selected. Repeat the inventory to include concurrent forks. A
    zombie cannot perform effects, but its first observation can hide a child
    born after the listing. Vanished entries have unknown session membership.
    Neither permits quiescence until another complete scan includes their
    possible children. Persistent inventory uncertainty after the stop budget
    blocks capture/destroy and preserves the existing private recovery state.
    """
    stopped = False
    known_terminal = set()

    def inventory():
        # Reap our own exited parent before listing; already terminal orphans
        # can remain until their independent reaper collects them.
        process.poll()
        members, terminal, vanished = owned_session_members(process.pid)
        unsettled = vanished or bool(terminal - known_terminal)
        known_terminal.update(terminal)
        return members, unsettled

    for signum in (signal.SIGTERM, signal.SIGKILL):
        deadline = time.monotonic() + PROCESS_STOP_SECONDS
        signalled = set()
        while True:
            members, unsettled = inventory()
            if not members and not unsettled:
                process.wait(timeout=PROCESS_STOP_SECONDS)
                return stopped
            stopped |= bool(members)
            for pid, identity in members.items():
                key = (pid, identity[2])
                if key not in signalled:
                    signal_owned_member(pid, identity, signum)
                    signalled.add(key)
            if time.monotonic() >= deadline:
                break
            time.sleep(0.01)
    members, unsettled = inventory()
    if members or unsettled:
        raise ProcessQuiescenceError("owned phase quiescence unconfirmed after bounded stop")
    process.wait(timeout=PROCESS_STOP_SECONDS)
    return stopped


def run_owned_process(command, workspace, environment, cancellation):
    process = None
    stopped = False
    read_fd = write_fd = None
    try:
        if cancellation.signum and not cancellation.finalizing:
            raise CellCancelled(cancellation.signum)
        read_fd, write_fd = os.pipe()
        process = subprocess.Popen(
            [sys.executable, "-I", "-S", "-c", OWNED_SHELL_LAUNCHER, str(read_fd), command],
            cwd=workspace, env=environment, start_new_session=True,
            pass_fds=(read_fd,),
        )
        cancellation.active = process
        if cancellation.signum and not cancellation.finalizing:
            raise CellCancelled(cancellation.signum)
        if os.write(write_fd, b"1") != 1:
            raise OSError("owned shell start authorization failed")
        timeout = CANCEL_FINALIZER_SECONDS if cancellation.finalizing else None
        try:
            code = process.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            code = 124
    finally:
        cancellation.stopping = True
        try:
            try:
                for descriptor in (read_fd, write_fd):
                    if descriptor is not None:
                        os.close(descriptor)
            finally:
                # A successful shell exit can also leave timeout-owned children.
                # Never start the next phase until this exact session is inactive.
                if process is not None:
                    stopped = stop_owned_process(process)
        finally:
            cancellation.active = None
            cancellation.stopping = False
    # A parent exiting zero while work is still active is not a completed
    # phase. Even after stopping that work, never authorize a success receipt.
    return 1 if code == 0 and stopped else code


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
                "QUALITY_INCUS_RUNTIME_SCHEMA",
                "MOLECULE_INCUS_TRANSPORT",
                "MOLECULE_INCUS_REMOTE",
                "MOLECULE_INCUS_PROJECT",
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
    require_pidfd_signalling()
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
                cancelled = cancellation.signum is not None
                if cancelled and (not always or identity not in OWNED_FINALIZERS):
                    results[identity] = {"outcome": "skipped", "outputs": {}}
                    continue
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
    schema = binding.get("schema") if isinstance(binding, dict) else None
    if (type(schema) is not int or schema not in (1, 2)
            or set(binding) != keys | ({"runtime", "admission"} if schema == 2 else set())):
        raise ValueError("approved Incus binding shape differs")
    if schema == 2:
        runtime = binding["runtime"]
        if (not isinstance(runtime, dict) or set(runtime) != {"firewall_controller", "bridge", "storage_pool"}
                or runtime["firewall_controller"] != "incus"
                or not isinstance(runtime["bridge"], dict)
                or not isinstance(runtime["storage_pool"], str)
                or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,62}", runtime["storage_pool"])
                or not isinstance(binding["admission"], str) or len(binding["admission"]) > 16384
                or not re.fullmatch(r"[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+", binding["admission"])):
            raise ValueError("approved Incus runtime binding differs")
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


def transport_environment(environment: dict[str, str], config_root: Path) -> dict[str, str]:
    """Derive transport selection only from the already verified private mount.

    Schema2 is the Root runtime publication. Its admission signature and native
    ownership are verified upstream by the Root issuer before engine execution;
    this reader is not an independent signature verifier or operating grant.
    The Source TLS helper still checks all runtime facts against the live server.
    """
    derived = ("QUALITY_INCUS_RUNTIME_SCHEMA", "MOLECULE_INCUS_TRANSPORT",
               "MOLECULE_INCUS_REMOTE", "MOLECULE_INCUS_PROJECT")
    if any(environment.get(key) for key in derived):
        raise ValueError("caller cannot select the admitted Incus runtime transport")
    project = validate_transport(environment, config_root)
    binding = json.loads((config_root / "binding.json").read_text())
    values = {"QUALITY_INCUS_PROJECT": project}
    if binding["schema"] == 2:
        values.update({"QUALITY_INCUS_RUNTIME_SCHEMA": "2", "MOLECULE_INCUS_TRANSPORT": "tls",
                       "MOLECULE_INCUS_REMOTE": "quality", "MOLECULE_INCUS_PROJECT": project})
    return values


def source_snapshot(path: Path, expected_sha: str) -> dict[str, dict]:
    """Read the fixed Root-derived archive inventory, not a job assertion.

    Its bytes and Source tree are sealed in the Root engine descriptor after
    independent GitHub commit/tree/blob acquisition. This reader alone grants
    no authenticity to an arbitrary file outside that admitted mount contract.
    """
    if path.is_symlink() or not path.is_file() or not 0 < path.stat().st_size <= 4*1024*1024:
        raise ValueError("Root Source provenance is missing or oversized")
    value = json.loads(path.read_bytes())
    if (not isinstance(value, dict) or set(value) != {
            "schema", "repository", "repository_id", "commit_sha", "tree_sha", "files"}
            or type(value["schema"]) is not int or value["schema"] != 1
            or value["repository"] != "ltn-it/ansible-collection-supplementary"
            or type(value["repository_id"]) is not int or value["repository_id"] != 1103407173
            or not re.fullmatch(r"[0-9a-f]{40}", expected_sha)
            or value["commit_sha"] != expected_sha
            or not isinstance(value["tree_sha"], str) or not re.fullmatch(r"[0-9a-f]{40}", value["tree_sha"])
            or not isinstance(value["files"], list) or not 0 < len(value["files"]) <= 20000):
        raise ValueError("Root Source provenance differs from the exact candidate")
    entries = {}
    for row in value["files"]:
        if not isinstance(row, dict) or set(row) != {"path", "mode", "oid", "size"}:
            raise ValueError("invalid Root Source inventory entry")
        name = row["path"]
        if (not isinstance(name, str) or not 0 < len(name) <= 4096 or name in (".", "..")
                or any(ord(c) < 32 or ord(c) == 127 for c in name)
                or PurePosixPath(name).is_absolute() or str(PurePosixPath(name)) != name
                or any(part in (".", "..", ".git") for part in PurePosixPath(name).parts)
                or name in entries or row["mode"] not in ("100644", "100755")
                or type(row["size"]) is not int or not 0 <= row["size"] <= 512*1024*1024
                or not isinstance(row["oid"], str) or not re.fullmatch(r"[0-9a-f]{40}", row["oid"])):
            raise ValueError("invalid Root Source inventory identity")
        entries[name] = row
    return entries


def snapshot_blob(workspace: Path, entries: dict[str, dict], relative: str) -> bytes:
    if relative not in entries:
        raise ValueError("test input is absent from the exact Source snapshot")
    row = entries[relative]
    path = workspace / relative
    info = path.lstat()
    if (not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or info.st_mode & 0o7000
            or bool(info.st_mode & 0o111) != (row["mode"] == "100755") or info.st_size != row["size"]):
        raise ValueError("Source snapshot file type, mode or size differs")
    raw = path.read_bytes()
    oid = hashlib.sha1(b"blob " + str(len(raw)).encode() + b"\0" + raw).hexdigest()
    if oid != row["oid"]:
        raise ValueError("Source snapshot Git blob differs")
    return raw


def verify_source_snapshot(workspace: Path, path: Path, expected_sha: str) -> None:
    entries = source_snapshot(path, expected_sha)
    files, directories = set(), set()
    expected_directories = {str(parent) for name in entries for parent in PurePosixPath(name).parents
                            if parent != PurePosixPath(".")}
    for root, children, leaves in os.walk(workspace, followlinks=False):
        for name in children:
            child = Path(root) / name
            if child.is_symlink():
                raise ValueError("Source snapshot contains a linked directory")
            directories.add(child.relative_to(workspace).as_posix())
        files.update((Path(root)/name).relative_to(workspace).as_posix() for name in leaves)
    if files != set(entries) or directories != expected_directories:
        raise ValueError("Source snapshot has missing or untracked paths")
    if sum(row["size"] for row in entries.values()) > 2*1024*1024*1024:
        raise ValueError("Source snapshot exceeds the complete input budget")
    for name in entries:
        snapshot_blob(workspace, entries, name)


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
    environment.update(transport_environment(environment, Path("/incus")))
    inputs = {
        name: environment[f"QUALITY_INPUT_{name.upper().replace('-', '_')}"]
        for name in INPUTS
    }
    if not re.fullmatch(r"[0-9a-f]{40}|[0-9a-f]{64}", inputs["source-sha"]):
        raise ValueError("quality source SHA is invalid")
    if environment.get("QUALITY_INCUS_RUNTIME_SCHEMA") == "2":
        verify_source_snapshot(Path("/workspace"), Path("/candidate/source-provenance.json"), inputs["source-sha"])
    else:
        head = subprocess.run(["git", "rev-parse", "HEAD"], cwd="/workspace",
                              capture_output=True, text=True, check=True)
        clean = subprocess.run(["git", "status", "--porcelain=v1", "--untracked-files=all"], cwd="/workspace",
                               capture_output=True, text=True, check=True)
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
