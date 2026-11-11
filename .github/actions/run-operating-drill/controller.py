"""Immutable operating fixture; Root, not this file, attests its observations."""
from __future__ import annotations

import json
import base64
from datetime import datetime, timezone
import importlib.util
import os
from pathlib import Path
import re
import stat
import subprocess
import sys
import time

CASES = ("failure", "broker-cancel", "expiry-controller-loss")
IMAGE = "38a97063887ebedb3596275e498ee5da4bb0508c28f14d247118d6205fc8cc9c"
SOURCE_CREATE = "/workspace/molecule/shared/incus/create.yml"
SPEC_FIELDS = {
    "schema", "kind", "case", "image", "instance_name", "cpu", "memory_bytes",
    "root_disk_bytes", "state_disk_bytes", "total_disk_bytes", "image_reservation_bytes",
    "project_reservation_bytes",
}
FIXED_NUMBERS = {
    "schema": 1, "cpu": 1, "memory_bytes": 2147483648,
    "root_disk_bytes": 5368709120, "state_disk_bytes": 524288000,
    "total_disk_bytes": 6442450944, "image_reservation_bytes": 4294967296,
    "project_reservation_bytes": 10737418240,
}


def require(condition, category):
    if not condition:
        raise ValueError(category)


def unique(pairs):
    value = {}
    for key, item in pairs:
        require(key not in value, "operating-duplicate-field")
        value[key] = item
    return value


def decode(raw):
    require(isinstance(raw, str) and len(raw.encode()) <= 16384, "operating-json-bound")
    return json.loads(raw, object_pairs_hook=unique, parse_constant=nonfinite)


def nonfinite(_value):
    raise ValueError("operating-number")


def spec_from_environment(environment):
    """Only Root's sealed manifest supplies this fixed operating platform."""
    spec = decode(environment.get("QUALITY_OPERATING_SPEC"))
    require(isinstance(spec, dict) and set(spec) == SPEC_FIELDS, "operating-spec-fields")
    require(spec["kind"] == "operating" and spec["case"] in CASES
            and spec["case"] == environment.get("QUALITY_OPERATING_CASE"), "operating-case")
    require(all(type(spec[key]) is int and spec[key] == number for key, number in FIXED_NUMBERS.items()),
            "operating-fixed-resources")
    require(spec["image"] == IMAGE, "operating-pinned-image")
    require(isinstance(spec["instance_name"], str)
            and re.fullmatch(r"[a-z][a-z0-9-]{0,62}", spec["instance_name"]), "operating-instance-name")
    require(environment.get("QUALITY_FAILURE_CUSTODY") == "retain-failed-v1", "operating-root-custody")
    return spec


def source_create_variables(spec):
    """Reuse the verified Source provider, without any business role/scenario."""
    scenario = "operating-" + spec["case"]
    return {"molecule_yml": {
        "scenario": {"name": scenario},
        "platforms": [{
            "name": spec["instance_name"], "image": "quality:" + spec["image"], "type": "vm",
            "identity": {"scenario": scenario, "target": "ubuntu-24.04"},
            "resources": {"cpu": "1", "memory": "2GiB", "disk": "5GiB"},
        }],
    }}


def raw_frame(spec, environment, instance, *, code=None, signal=None):
    """Bounded diagnostic hints only; no quality PASS, retention or authority."""
    require(isinstance(instance, dict) and set(instance) == {"name", "uuid", "state"}
            and instance["name"] == spec["instance_name"]
            and isinstance(instance["uuid"], str)
            and re.fullmatch(r"[a-f0-9]{8}(?:-[a-f0-9]{4}){3}-[a-f0-9]{12}", instance["uuid"])
            and instance["state"] in {"Running", "Stopped", "Unknown"}, "operating-instance-observation")
    require(code is None or type(code) is int and 0 <= code <= 255, "operating-raw-exit")
    require(signal is None or type(signal) is int and 1 <= signal <= 64, "operating-raw-signal")
    run = environment.get("GITHUB_RUN_ID")
    require(isinstance(run, str) and re.fullmatch(r"[1-9][0-9]{0,19}", run)
            and environment.get("GITHUB_RUN_ATTEMPT") == "1", "operating-run")
    for key in ("GITHUB_SHA", "QUALITY_CONTROLLER_SHA"):
        require(isinstance(environment.get(key), str) and re.fullmatch(r"[a-f0-9]{40}", environment[key]),
                "operating-native-sha")
    return {"schema": 1, "kind": "operating", "case": spec["case"], "run_id": int(run), "run_attempt": 1,
        "source_sha": environment["GITHUB_SHA"], "controller_sha": environment["QUALITY_CONTROLLER_SHA"],
        "execution": {"raw_exit_code": code, "signal": signal}, "instance": dict(instance),
        "observations": {"workload_failed": code is not None and code != 0,
                         "broker_cancel_sent": False, "controller_heartbeat_ceased": False},
        "root_finalization": "pending"}


def controller_sha(binding):
    """Project Root-verified admission identity, not a job-supplied SHA.

    Root verifies the JWS and exact engine/custody digests before launch; this
    projection is only a diagnostic hint which Root independently checks again.
    """
    token = binding.get("admission")
    require(isinstance(token, str) and len(token) <= 16384 and token.count(".") == 2, "operating-admission")
    encoded = token.split(".")[1]
    payload = decode(base64.urlsafe_b64decode(encoded + "=" * (-len(encoded) % 4)).decode("utf-8"))
    sha = payload.get("identity", {}).get("reusable_sha")
    require(isinstance(sha, str) and re.fullmatch(r"[a-f0-9]{40}", sha), "operating-controller-sha")
    return sha


def read_ready(path, case, uuid):
    """A one-time synchronization marker, never an authorization grant."""
    before = path.lstat()
    require(stat.S_ISREG(before.st_mode) and before.st_nlink == 1 and before.st_size <= 4096
            and not before.st_mode & 0o022, "operating-ready-file")
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC)
    try:
        raw = os.read(fd, 4097)
        after = os.fstat(fd)
        named = path.lstat()
        def stamp(info):
            return (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns)
        require(stamp(before) == stamp(after) == stamp(named) and len(raw) == before.st_size,
                "operating-ready-drift")
    finally:
        os.close(fd)
    value = decode(raw.decode("utf-8"))
    require(isinstance(value, dict) and set(value) == {"schema", "state", "case", "lease_id", "instance_uuid"}
            and type(value["schema"]) is int and value["schema"] == 1
            and value["state"] == "operating-ready" and value["case"] == case
            and value["instance_uuid"] == uuid and isinstance(value["lease_id"], str)
            and re.fullmatch(r"[a-f0-9]{32}", value["lease_id"]), "operating-ready-binding")
    return value


def main():
    require(len(sys.argv) == 1, "operating-no-job-arguments")
    os.umask(0o077)
    environment = dict(os.environ)
    spec = spec_from_environment(environment)
    for path in ("/workspace", "/controller", "/incus"):
        require(Path(path).is_dir() and not os.access(path, os.W_OK), "operating-readonly-inputs")
    require(Path("/quality").is_dir() and os.access("/quality", os.W_OK), "operating-output")
    marker = Path("/quality/control/root-operating-ready.json")
    require(not marker.exists() and not marker.is_symlink(), "operating-ready-preexisting")
    helper_path = Path("/workspace/molecule/shared/incus/helpers/tls_transport.py")
    require(helper_path.is_file() and not helper_path.is_symlink(), "operating-verified-source-helper")
    module_spec = importlib.util.spec_from_file_location("operating_source_tls", helper_path)
    transport = importlib.util.module_from_spec(module_spec)
    sys.modules[module_spec.name] = transport
    module_spec.loader.exec_module(transport)
    binding, tls, _ = transport.load_context(Path("/incus"), repository=environment["GITHUB_REPOSITORY"],
        run_id=environment["GITHUB_RUN_ID"], attempt="1", now=datetime.now(timezone.utc))
    environment["QUALITY_CONTROLLER_SHA"] = controller_sha(binding)
    owner = binding["runtime"]["bridge"]["owner"]
    private = Path("/tmp/wunder/operating-private")
    private.mkdir(mode=0o700)
    variables = private / "create.json"
    with variables.open("x", encoding="utf-8") as stream:
        json.dump(source_create_variables(spec), stream)
    environment.update({"INCUS_CONF": "/incus", "MOLECULE_INCUS_TRANSPORT": "tls",
        "MOLECULE_INCUS_REMOTE": "quality", "MOLECULE_INCUS_PROJECT": binding["project"],
        "MOLECULE_PROJECT_DIRECTORY": "/workspace", "MOLECULE_TEST_OWNER": owner,
        "MOLECULE_TEST_ARTIFACTS": "/quality/operating-private", "MOLECULE_EPHEMERAL_DIRECTORY": str(private)})
    created = subprocess.run(["ansible-playbook", SOURCE_CREATE, "--extra-vars", "@" + str(variables)],
        cwd="/workspace", env=environment, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL, timeout=180, check=False)
    require(created.returncode == 0, "operating-shared-create-failed")
    value = transport.Client(binding, tls).get("/1.0/instances/" + spec["instance_name"])
    require(value.get("name") == spec["instance_name"] and value.get("type") == "virtual-machine"
            and value.get("status") == "Running"
            and value.get("config", {}).get("user.lit-molecule-owner") == owner, "operating-owned-running-vm")
    instance = {"name": spec["instance_name"], "uuid": value["config"].get("volatile.uuid"), "state": "Running"}
    # Root must first double-read and durably bind this actual VM before the
    # failure case exits; the marker prevents a create/exit readiness race.
    deadline = time.monotonic() + 120
    while not marker.exists():
        require(time.monotonic() < deadline, "operating-root-ready-timeout")
        time.sleep(0.1)
    read_ready(marker, spec["case"], instance["uuid"])
    code = 23 if spec["case"] == "failure" else None
    with Path("/quality/operating-result.json").open("x", encoding="utf-8") as stream:
        json.dump(raw_frame(spec, environment, instance, code=code), stream, sort_keys=True)
        stream.write("\n")
    if code is not None:
        return code
    # The broker/client or real authorization expiry must end this workload.
    # Root's supervisor remains alive and owns stop, access withdrawal/custody.
    while True:
        time.sleep(1)


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception:
        print("Operating fixture held; no operating acceptance", file=sys.stderr)
        raise SystemExit(2) from None
