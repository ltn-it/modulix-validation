"""Compile the closed protected Main admission contract before worker scheduling."""

from __future__ import annotations

import json
import os
import re
import sys

MAX_BYTES = 65536
MAX_CELLS = 256
OPERATING_CASES = ("failure", "broker-cancel", "expiry-controller-loss")
OPERATING_BEFORE = "90e7216b5d085ca4ac6238e44dcdbaa51e847d5f"
OPERATING_CONTINUATION_BEFORE = "14e3abd5d1fa0cfad14d52ec83483b761de207f0"
OPERATING_PREAUTH_BEFORE = "f27c1d4edff75377f285275cec9bfec6bc3081f6"
IDENTIFIER = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,62}")
ROLE = re.compile(r"[a-z][a-z0-9_]{0,62}")
IMAGE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:/@+-]{0,511}")
VARIABLE = re.compile(r"[A-Z][A-Z0-9_]{0,127}")
RUNNERS = (
    ("self-hosted", "linux", "x64", "incus"),
    ("self-hosted", "linux", "x64", "incus", "keycloak-test"),
)
FIELDS = {
    "scenario",
    "component",
    "profile",
    "target",
    "target_disposition",
    "release_required",
    "instance_type",
    "runner",
    "roles",
    "junit",
    "allure",
    "evidence",
}
CALLER = {
    "CALLER_REPOSITORY": "ltn-it/modulix-validation",
    "CALLER_REPOSITORY_ID": "1269461997",
    "CALLER_EVENT": "workflow_dispatch",
    "CALLER_REF": "refs/heads/main",
    "CALLER_WORKFLOW_REF": "ltn-it/modulix-validation/.github/workflows/mlx90-collection-candidate-validation.yml@refs/heads/main",
    "CALLER_ACTOR": "lightning-it-release-automation[bot]",
    "CALLER_ACTOR_ID": "307565056",
    "CALLER_TRIGGERING_ACTOR": "lightning-it-release-automation[bot]",
    "CALLER_ATTEMPT": "1",
    "SOURCE_REPOSITORY": "ltn-it/ansible-collection-supplementary",
    "CPU_LIMIT": "4",
    "MEMORY_LIMIT": "12GiB",
    "DISK_LIMIT": "24GiB",
}
SUPPLEMENTARY_CALLER = {
    "CALLER_REPOSITORY": "ltn-it/ansible-collection-supplementary",
    "CALLER_REPOSITORY_ID": "1103407173",
    "CALLER_REPOSITORY_OWNER_ID": "54334171",
    "CALLER_EVENT": "push",
    "CALLER_REF": "refs/heads/main",
    "CALLER_REF_PROTECTED": "true",
    "CALLER_WORKFLOW_REF": "ltn-it/ansible-collection-supplementary/.github/workflows/collection-ci.yml@refs/heads/main",
    "CALLER_ACTOR_TYPE": "User",
    "CALLER_ATTEMPT": "1",
    "SOURCE_REPOSITORY": "ltn-it/ansible-collection-supplementary",
    "CPU_LIMIT": "4",
    "MEMORY_LIMIT": "12GiB",
    "DISK_LIMIT": "24GiB",
}
SUPPLEMENTARY_ACTORS = (("litroc", "76040632"), ("litdeg", "247824904"))


class Refused(ValueError):
    """Public bounded category; never echo supplied input."""


def require(condition, category):
    if not condition:
        raise Refused(category)


def text(value, pattern):
    return isinstance(value, str) and pattern.fullmatch(value) is not None


def unique(pairs):
    result = {}
    for key, value in pairs:
        require(key not in result, "duplicate-json-key")
        result[key] = value
    return result


def nonfinite(_value):
    raise Refused("nonfinite-json-number")


def compile_matrix(raw, profile):
    require(profile in ("heavy", "application_acceptance"), "profile")
    require(
        isinstance(raw, str) and 0 < len(raw.encode("utf-8")) <= MAX_BYTES,
        "matrix-size",
    )
    document = json.loads(raw, object_pairs_hook=unique, parse_constant=nonfinite)
    require(
        isinstance(document, dict) and set(document) == {"include"},
        "matrix-outer-shape",
    )
    cells = document["include"]
    require(
        isinstance(cells, list) and 1 <= len(cells) <= MAX_CELLS, "matrix-cell-count"
    )
    result, seen = [], set()
    for cell in cells:
        require(isinstance(cell, dict), "matrix-cell-shape")
        selectors = set(cell) & {"image", "image_variable"}
        require(
            len(selectors) == 1 and set(cell) == FIELDS | selectors,
            "matrix-cell-fields",
        )
        for key in ("scenario", "target"):
            require(text(cell[key], IDENTIFIER), "matrix-identifier")
        roles = cell["roles"]
        require(
            isinstance(roles, list)
            and 1 <= len(roles) <= MAX_CELLS
            and all(text(role, ROLE) for role in roles),
            "matrix-roles",
        )
        require(len(set(roles)) == len(roles), "duplicate-role")
        component = cell["component"]
        require(isinstance(component, str), "matrix-component")
        parts = component.split("+")
        require(
            1 <= len(parts) <= len(roles)
            and all(text(part, IDENTIFIER) for part in parts)
            and parts == sorted(set(parts)),
            "matrix-component",
        )
        require(cell["profile"] == profile, "matrix-profile")
        require(
            cell["target_disposition"] == "supported"
            and cell["release_required"] is True,
            "matrix-release-disposition",
        )
        require(cell["instance_type"] in ("container", "vm"), "matrix-instance-type")
        runner = cell["runner"]
        require(
            isinstance(runner, list)
            and all(isinstance(label, str) for label in runner)
            and tuple(runner) in RUNNERS,
            "matrix-runner",
        )
        require(
            all(isinstance(cell[key], bool) for key in ("junit", "allure", "evidence")),
            "matrix-boolean",
        )
        selector = next(iter(selectors))
        require(
            text(cell[selector], IMAGE if selector == "image" else VARIABLE),
            "matrix-image",
        )
        identity = (cell["scenario"], cell["target"])
        require(identity not in seen, "duplicate-cell")
        seen.add(identity)
        result.append(dict(cell))
    canonical = json.dumps(
        {"include": result}, sort_keys=True, separators=(",", ":"), ensure_ascii=True
    )
    require(len(canonical.encode("ascii")) <= MAX_BYTES, "canonical-matrix-size")
    return canonical


def admit(environment):
    # Only complete trusted GitHub identities select a domain. No workflow
    # input or matrix field chooses the caller policy.
    receiver = all(environment.get(key) == value for key, value in CALLER.items())
    supplementary = (
        all(
            environment.get(key) == value for key, value in SUPPLEMENTARY_CALLER.items()
        )
        and any(
            environment.get("CALLER_ACTOR") == login
            and environment.get("CALLER_ACTOR_ID") == actor_id
            and environment.get("CALLER_TRIGGERING_ACTOR") == login
            for login, actor_id in SUPPLEMENTARY_ACTORS
        )
        and environment.get("CALLER_SHA") == environment.get("SOURCE_SHA")
    )
    require(receiver or supplementary, "caller-or-pilot-binding")
    profile = environment.get("PROFILE")
    require(
        text(environment.get("SOURCE_SHA"), re.compile(r"[0-9a-f]{40}")), "source-sha"
    )
    artifact = environment.get("CANDIDATE_ARTIFACT")
    require(
        text(artifact, re.compile(r"mlx90-candidate-[0-9a-f]{64}"))
        if receiver
        else artifact == "collection-candidate-" + environment["SOURCE_SHA"],
        "candidate-artifact",
    )
    case = environment.get("OPERATING_CASE", "")
    require(isinstance(case, str), "operating-case-type")
    if profile == "operating":
        require(supplementary and not receiver and case in OPERATING_CASES,
                "operating-source-case")
        # Scheduling retains both failed transitions and one exact protocol follow-up.
        # Root admission still independently binds the genuine job and continuation.
        require(
            environment.get("CALLER_BEFORE")
            in (OPERATING_BEFORE, OPERATING_CONTINUATION_BEFORE, OPERATING_PREAUTH_BEFORE),
            "operating-first-main-transition",
        )
        raw = environment.get("MATRIX_JSON")
        require(isinstance(raw, str) and 0 < len(raw.encode("utf-8")) <= MAX_BYTES,
                "operating-matrix-bound")
        matrix = json.loads(raw, object_pairs_hook=unique, parse_constant=nonfinite)
        require(matrix == {"include": []}, "operating-no-business-matrix")
        return profile, '{"include":[]}'
    require(profile in ("heavy", "application_acceptance") and case == "", "profile")
    return profile, compile_matrix(environment.get("MATRIX_JSON"), profile)


def worker_group(environment):
    """Derive capacity only after the entire native admission has succeeded."""
    admit(environment)
    return (
        "lit-pis-prd-supplementary-isolated"
        if environment["CALLER_REPOSITORY"] == SUPPLEMENTARY_CALLER["CALLER_REPOSITORY"]
        else "lit-pis-prd-isolated"
    )


def operating_case(environment):
    """An operating test is never a business-cell role or quality result."""
    profile, _ = admit(environment)
    return environment["OPERATING_CASE"] if profile == "operating" else ""


def main():
    try:
        require(len(sys.argv) == 1, "closed-argv")
        profile, matrix = admit(os.environ)
        group = worker_group(os.environ)
        case = operating_case(os.environ)
    except (ValueError, TypeError, UnicodeError, RecursionError):
        print("Incus admission refused", file=sys.stderr)
        return 2
    # No output is produced until the complete identity and every cell validate.
    print("profile=" + profile)
    print("matrix-json=" + matrix)
    print("worker-group=" + group)
    print("operating-case=" + case)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
