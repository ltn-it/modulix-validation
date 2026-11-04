"""Validate the immutable MLX-90 receiver request before protected access.

This adapter does not execute a profile or issue a release receipt. It supplies
the strict input boundary for the paired receiver; eligibility remains false
until the native execution and signing stages have been integrated.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping
from typing import Any
from urllib.parse import urlsplit

SOURCE_REPOSITORY = "ltn-it/ansible-collection-supplementary"
SOURCE_WORKFLOW = ".github/workflows/collection-publish.yml"
CONTROLLER_REPOSITORY = "ltn-it/modulix-validation"
CONTROLLER_WORKFLOW = ".github/workflows/mlx90-collection-candidate-validation.yml"
APP_ACTOR = "lightning-it-release-automation[bot]"
APP_ACTOR_ID = 307565056
MAIN_REF = "refs/heads/main"
MAX_REQUEST_BYTES = 16384
MAX_CANDIDATE_BYTES = 512 * 1024 * 1024


class RequestError(ValueError):
    """A request is not safe to use at the protected receiver boundary."""


def canonical(value: Mapping[str, Any]) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"))


def _object(value: Any, keys: set[str], label: str) -> dict[str, Any]:
    if not isinstance(value, dict) or value.keys() != keys:
        raise RequestError(f"{label}: unexpected shape")
    return value


def _integer(value: Any, label: str, maximum: int = 2**63 - 1) -> int:
    if type(value) is not int or not 0 < value <= maximum:
        raise RequestError(f"{label}: expected a bounded positive integer")
    return value


def _match(value: Any, pattern: str, label: str) -> str:
    if not isinstance(value, str) or not re.fullmatch(pattern, value):
        raise RequestError(f"{label}: unsupported value")
    return value


def _unique(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise RequestError("request contains a duplicate JSON key")
        result[key] = value
    return result


def _identity(repository: str, workflow: str, sha: str) -> dict[str, Any]:
    return {"repository": repository, "workflow": workflow, "ref": MAIN_REF, "sha": sha}


def validate_request(
    request_id: str,
    request_json: str,
    *,
    controller_sha: str,
    nexus_repository: str,
    nexus_repository_url: str,
) -> dict[str, Any]:
    """Bind untrusted dispatch input to controller and configured Nexus policy.

    The Nexus values must come from protected controller configuration, never
    from the request. No network or credential use occurs in this function.
    """
    _match(request_id, r"[0-9a-f]{64}", "request_id")
    _match(controller_sha, r"[0-9a-f]{40}", "controller SHA")
    if (
        not isinstance(request_json, str)
        or not 0 < len(request_json.encode()) <= MAX_REQUEST_BYTES
    ):
        raise RequestError("request exceeds the input bound")
    if hashlib.sha256(request_json.encode()).hexdigest() != request_id:
        raise RequestError("request hash differs")
    try:
        request = json.loads(request_json, object_pairs_hook=_unique)
    except (ValueError, RecursionError) as exc:
        raise RequestError("request is not unambiguous JSON") from exc
    _object(
        request,
        {"apiVersion", "kind", "source", "security", "candidate", "controller"},
        "request",
    )
    if canonical(request) != request_json:
        raise RequestError("request JSON is not canonical")
    if (
        request["apiVersion"] != "lit.mlx90.collection-validation-request/v2"
        or request["kind"] != "CollectionValidationRequest"
    ):
        raise RequestError("request schema differs")
    expected_controller = _identity(
        CONTROLLER_REPOSITORY, CONTROLLER_WORKFLOW, controller_sha
    )
    if request["controller"] != expected_controller:
        raise RequestError("controller identity differs")
    source = _object(
        request["source"],
        {
            "actor",
            "actorId",
            "actorType",
            "event",
            "ref",
            "repository",
            "runAttempt",
            "runId",
            "sha",
            "workflow",
        },
        "source",
    )
    source_sha = _match(source["sha"], r"[0-9a-f]{40}", "source SHA")
    expected_source = {
        **_identity(SOURCE_REPOSITORY, SOURCE_WORKFLOW, source_sha),
        "actor": APP_ACTOR,
        "actorId": APP_ACTOR_ID,
        "actorType": "Bot",
        "event": "workflow_dispatch",
        "runId": _integer(source["runId"], "source run"),
        "runAttempt": _integer(source["runAttempt"], "source attempt"),
    }
    if source != expected_source or type(source["actorId"]) is not int:
        raise RequestError("source identity differs")
    security = _object(request["security"], {"evidenceId", "humanActions"}, "security")
    _match(security["evidenceId"], r"MLX90-[A-Z0-9][A-Z0-9._-]{2,121}", "evidence ID")
    if type(security["humanActions"]) is not int or security["humanActions"] != 0:
        raise RequestError("human actions must be exactly zero")
    candidate = _object(
        request["candidate"],
        {"name", "sha256", "size", "version", "nexus"},
        "candidate",
    )
    version = _match(
        candidate["version"],
        r"(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)",
        "candidate version",
    )
    if candidate["name"] != f"lit-supplementary-{version}.tar.gz":
        raise RequestError("candidate name differs")
    _match(candidate["sha256"], r"sha256:[0-9a-f]{64}", "candidate digest")
    _integer(candidate["size"], "candidate size", MAX_CANDIDATE_BYTES)
    _match(
        nexus_repository, r"[a-z0-9][a-z0-9._-]{0,126}", "configured Nexus repository"
    )
    if not isinstance(nexus_repository_url, str) or not nexus_repository_url.isascii():
        raise RequestError("configured Nexus URL is invalid")
    url = urlsplit(nexus_repository_url)
    if (
        url.scheme != "https"
        or not url.hostname
        or url.username
        or url.password
        or url.query
        or url.fragment
        or url.port not in {None, 443}
        or url.path != f"/repository/{nexus_repository}"
        or nexus_repository_url != f"https://{url.netloc}{url.path}"
        or any(char.isspace() for char in nexus_repository_url)
    ):
        raise RequestError("configured Nexus URL is unsafe")
    expected_nexus = {
        "repository": nexus_repository,
        "repositoryUrl": nexus_repository_url,
        "url": f"{nexus_repository_url}/api/v3/plugin/ansible/content/published/collections/artifacts/{candidate['name']}",
    }
    if candidate["nexus"] != expected_nexus:
        raise RequestError("candidate Nexus location differs from protected policy")
    return request


def validate_source_run(request: Mapping[str, Any], run: Mapping[str, Any]) -> None:
    """Validate a fresh GitHub API run, including its triggering identity.

    The producer is still waiting for this receiver, so in_progress is required;
    a historical successful producer cannot authorize a new candidate request.
    """
    source = request["source"]
    expected = {
        "id": source["runId"],
        "run_attempt": source["runAttempt"],
        "head_sha": source["sha"],
        "head_branch": "main",
        "path": SOURCE_WORKFLOW,
        "event": "workflow_dispatch",
        "status": "in_progress",
        "conclusion": None,
    }
    for key, value in expected.items():
        if (
            key not in run
            or run[key] != value
            or (key in {"id", "run_attempt"} and type(run[key]) is not int)
        ):
            raise RequestError(f"producer run {key} differs")
    for key in ("repository", "head_repository"):
        repo = run.get(key)
        if not isinstance(repo, dict) or repo.get("full_name") != SOURCE_REPOSITORY:
            raise RequestError(f"producer {key} differs")
    for key in ("actor", "triggering_actor"):
        actor = run.get(key)
        if (
            not isinstance(actor, dict)
            or {name: actor.get(name) for name in ("login", "id", "type")}
            != {
                "login": APP_ACTOR,
                "id": APP_ACTOR_ID,
                "type": "Bot",
            }
            or type(actor.get("id")) is not int
        ):
            raise RequestError(f"producer {key} differs")
