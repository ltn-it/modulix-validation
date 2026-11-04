"""Protected MLX-90 receiver adapter; no candidate rebuild or publication."""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import re
import shutil
import tempfile
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

from collection_candidate_request import (
    APP_ACTOR,
    APP_ACTOR_ID,
    CONTROLLER_REPOSITORY,
    CONTROLLER_WORKFLOW,
    MAIN_REF,
    RequestError,
    canonical,
    validate_request,
    validate_source_run,
)


def load(path: Path) -> Any:
    if path.is_symlink() or not path.is_file() or path.stat().st_size > 1024 * 1024:
        raise RequestError("controller input is missing or oversized")
    return json.loads(path.read_text())


def controller_identity(
    run: dict[str, Any], request: dict[str, Any], request_id: str
) -> dict[str, Any]:
    actor = {"login": APP_ACTOR, "id": APP_ACTOR_ID, "type": "Bot"}
    for name in ("actor", "triggering_actor"):
        if {key: run.get(name, {}).get(key) for key in actor} != actor or type(
            run.get(name, {}).get("id")
        ) is not int:
            raise RequestError("controller App identity differs")
    for name in ("repository", "head_repository"):
        if run.get(name, {}).get("full_name") != CONTROLLER_REPOSITORY:
            raise RequestError("controller repository differs")
    expected = {
        "head_sha": request["controller"]["sha"],
        "head_branch": "main",
        "path": CONTROLLER_WORKFLOW,
        "event": "workflow_dispatch",
        "status": "in_progress",
        "conclusion": None,
        "display_title": f"MLX-90 collection candidate / {request_id}",
    }
    if any(run.get(key) != value for key, value in expected.items()):
        raise RequestError("controller native run binding differs")
    if any(
        type(run.get(key)) is not int or run[key] <= 0 for key in ("id", "run_attempt")
    ):
        raise RequestError("controller run/attempt is invalid")
    return {
        "actor": APP_ACTOR,
        "actorId": APP_ACTOR_ID,
        "actorType": "Bot",
        "conclusion": "success",
        "event": "workflow_dispatch",
        "humanActions": 0,
        "receiptArtifact": f"mlx90-collection-validation-{request_id}",
        "ref": MAIN_REF,
        "repository": CONTROLLER_REPOSITORY,
        "runAttempt": run["run_attempt"],
        "runId": run["id"],
        "sha": run["head_sha"],
        "workflow": CONTROLLER_WORKFLOW,
    }


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def exact_readback(
    request: dict[str, Any], credentials: dict[str, str], destination: Path, opener=None
) -> None:
    """Authenticate to the independently configured URL and atomically retain exact bytes."""
    username, password = (
        credentials.get("username", ""),
        credentials.get("password", ""),
    )
    if (
        not username
        or not password
        or ":" in username
        or any(c in username + password for c in "\r\n")
    ):
        raise RequestError("protected Nexus reader configuration is missing or invalid")
    candidate = request["candidate"]
    authorization = base64.b64encode(f"{username}:{password}".encode()).decode()
    outgoing = urllib.request.Request(
        candidate["nexus"]["url"],
        headers={
            "Authorization": f"Basic {authorization}",
            "Accept": "application/octet-stream",
        },
        method="GET",
    )
    client = opener or urllib.request.build_opener(NoRedirect())
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with client.open(outgoing, timeout=120) as response:
            if response.status != 200 or response.geturl() != candidate["nexus"]["url"]:
                raise RequestError(
                    "Nexus did not return an exact nonredirected response"
                )
            length = response.headers.get("Content-Length")
            if length is not None and length != str(candidate["size"]):
                raise RequestError("Nexus size header differs")
            digest, size = hashlib.sha256(), 0
            with tempfile.NamedTemporaryFile(
                dir=destination.parent, delete=False
            ) as output:
                temporary = Path(output.name)
                while chunk := response.read(
                    min(1024 * 1024, candidate["size"] - size + 1)
                ):
                    size += len(chunk)
                    if size > candidate["size"]:
                        raise RequestError("Nexus candidate exceeds bound size")
                    digest.update(chunk)
                    output.write(chunk)
            if (
                size != candidate["size"]
                or f"sha256:{digest.hexdigest()}" != candidate["sha256"]
            ):
                raise RequestError("Nexus candidate size or digest differs")
            os.replace(temporary, destination)
            temporary = None
    except (OSError, urllib.error.URLError):
        raise RequestError(
            "authenticated Nexus readback failed; no automatic retry"
        ) from None
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def prepare_candidate(request: dict[str, Any], staged: Path, output: Path) -> None:
    """Keep producer-tested dependency bytes; independently prove candidate bytes match Nexus."""
    name = request["candidate"]["name"]
    expected_names = {name, "runtime-collections.tar.gz"}
    manifest = staged / "candidate-SHA256SUMS"
    if (
        manifest.is_symlink()
        or not manifest.is_file()
        or manifest.stat().st_size > 4096
    ):
        raise RequestError("producer candidate checksums are missing")
    checksums = {}
    for row in manifest.read_text().splitlines():
        match = re.fullmatch(r"([0-9a-f]{64})  ([A-Za-z0-9._-]+)", row)
        if match is None or match[2] in checksums:
            raise RequestError("producer candidate checksums are ambiguous")
        checksums[match[2]] = match[1]
    if checksums.keys() != expected_names:
        raise RequestError("producer candidate checksum inventory differs")
    for filename, digest in checksums.items():
        path = staged / filename
        if (
            path.is_symlink()
            or not path.is_file()
            or path.stat().st_size > 1024 * 1024 * 1024
        ):
            raise RequestError("producer candidate file is unsafe")
        with path.open("rb") as stream:
            if hashlib.file_digest(stream, "sha256").hexdigest() != digest:
                raise RequestError("producer dependency or candidate digest differs")
    if checksums[name] != request["candidate"]["sha256"].removeprefix("sha256:"):
        raise RequestError("producer candidate differs from Nexus-bound request")
    candidate = output / name
    if (
        candidate.is_symlink()
        or not candidate.is_file()
        or candidate.stat().st_size != request["candidate"]["size"]
    ):
        raise RequestError("independent Nexus readback is missing")
    with candidate.open("rb") as stream:
        if hashlib.file_digest(stream, "sha256").hexdigest() != checksums[name]:
            raise RequestError("independent Nexus bytes differ")
    shutil.copyfile(
        staged / "runtime-collections.tar.gz", output / "runtime-collections.tar.gz"
    )
    (output / "candidate-SHA256SUMS").write_text(manifest.read_text())


def validation_receipt(request, request_id, run, jobs):
    identity = controller_identity(run, request, request_id)
    if not isinstance(jobs, list) or not jobs:
        raise RequestError("native job inventory is empty")
    names = [job.get("name") for job in jobs]
    if len(set(names)) != len(names):
        raise RequestError("native job names are ambiguous")
    signing = [job for job in jobs if job.get("name") == "Sign validation receipt"]
    if len(signing) != 1 or signing[0].get("status") != "in_progress":
        raise RequestError("current signing job is not uniquely in progress")
    prior = [job for job in jobs if job is not signing[0]]
    if any(
        job.get("status") != "completed"
        or job.get("conclusion") != "success"
        or job.get("run_id") != run["id"]
        or job.get("run_attempt") != run["run_attempt"]
        for job in prior
    ):
        raise RequestError("a required native job is missing, skipped or unsuccessful")
    for required in ("Validate immutable request", "Nexus exact-byte readback"):
        if names.count(required) != 1:
            raise RequestError("required receiver stage is missing")
    for prefix in ("Heavy / ", "Application Acceptance / "):
        if not any(isinstance(name, str) and name.startswith(prefix) for name in names):
            raise RequestError("real infrastructure profile execution is missing")
    identity["observations"] = {
        "applicationAcceptance": "passed",
        "candidateDigest": request["candidate"]["sha256"],
        "heavy": "passed",
        "nexusReadback": request["candidate"]["sha256"],
        "sourceRun": request["source"],
    }
    return {
        "apiVersion": "lit.mlx90.collection-validation-receipt/v2",
        "kind": "CollectionValidationReceipt",
        "requestId": f"sha256:{request_id}",
        "request": request,
        "validation": identity,
        "decision": {
            "candidateUnchanged": True,
            "galaxyPublicationAuthorized": True,
            "releaseEligible": True,
        },
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("phase", choices=("request", "validate", "readback", "receipt"))
    parser.add_argument("--root", type=Path, default=Path(".candidate-control"))
    parser.add_argument("--request-id", required=True)
    parser.add_argument("--controller-sha", required=True)
    args = parser.parse_args()
    root = args.root
    config = load(root / "config.json")
    request = validate_request(
        args.request_id,
        (root / "request.json").read_text(),
        controller_sha=args.controller_sha,
        nexus_repository=config["repository"],
        nexus_repository_url=config["url"],
    )
    if args.phase == "request":
        print(f"source-sha={request['source']['sha']}")
        print(f"source-run-id={request['source']['runId']}")
        print(f"source-run-attempt={request['source']['runAttempt']}")
        return
    validate_source_run(request, load(root / "producer-run.json"))
    run = load(root / "controller-run.json")
    controller_identity(run, request, args.request_id)
    if args.phase == "readback":
        exact_readback(
            request,
            load(root / "nexus-auth.json"),
            root / "candidate" / request["candidate"]["name"],
        )
        prepare_candidate(
            request, root / "stage" / "incoming" / "candidate", root / "candidate"
        )
    elif args.phase == "receipt":
        receipt = validation_receipt(
            request, args.request_id, run, load(root / "jobs.json")
        )
        (root / "receipt").mkdir(exist_ok=True)
        (root / "receipt" / "mlx90-collection-validation-receipt.json").write_text(
            canonical(receipt) + "\n"
        )


if __name__ == "__main__":
    try:
        main()
    except (RequestError, OSError, ValueError, KeyError, TypeError) as error:
        # Network/provider exceptions must never leak credential-bearing request objects.
        raise SystemExit(f"receiver stopped: {error}") from None
