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
OPERATING_THIRD_BEFORE = "3d84e26d90cc778fb8c4f462ce481584da57fb5a"
OPERATING_FOURTH_BEFORE = "f138a227d9eee41ea698b1a6f3b9a05f7ae3e18d"
OPERATING_FIFTH_BEFORE = "8926e7f535f158d4af89e4ac68149ff0b8ab740d"
OPERATING_SIXTH_BEFORE = "086d039c8c58bc91edfeacadf508c207a03a58b5"
OPERATING_SEVENTH_BEFORE = "cfd2e8ca4cbcf58a1a22cf37f2a8336bba19cb85"
OPERATING_EIGHTH_BEFORE = "8345d447e65609e66eac616afbeb3b5d4bc362be"
OPERATING_NINTH_BEFORE = "86f3cb46e5856c4066cac14e73f46c3cefb8453e"
OPERATING_TENTH_BEFORE = "5604f19544f97b572272496fd61f5c4949d45fba"
OPERATING_VERIFIED_CLOSURE_BEFORE = "e403e0fffa9318be82718b29e854ab7a3a6da98c"
OPERATING_PODMAN_REPAIR_BEFORE = "69d2ccf034dfe5c64c0fda8fc037569fc9b96ff6"
OPERATING_CENSUS_HELD_BEFORE = "e42b0cdd65536e3749f6c405ec23955e5aaa419b"
OPERATING_SEALED_INTAKE_BEFORE = "8edd19c61a8faffe10d6c570cc3ad8338750f475"
OPERATING_ENGINE_RETIREMENT_BEFORE = "5759a628d9fadb258036390483cb158c8ea36570"
OPERATING_LEDGER_READ_BEFORE = "a2d4a7e906eec88b250af82375d82592f9b2380f"
OPERATING_PODMAN_CID_BEFORE = "33c97bee9d37f3b1901765d5ffc59a79823c7534"
OPERATING_PODMAN_NETNS_BEFORE = "d2490ec0841ff5c372840aae06ce75a3d5a3f627"
OPERATING_CAPACITY_FAILURE_BEFORE = "8cf199eedd68e653f97a4739a5d0b2e7235f91f5"
OPERATING_STOPPED_FAILURE_CLOSED_BEFORE = "aca24665c7d0e192974e1bb030737a349c6b70db"
OPERATING_C22_CLOSED_BEFORE = "af5a45eca7e7dcaa85af8bea3e6d77c775fd8b9a"
OPERATING_C23_PRELEASE_BEFORE = "98157a078b130bc6daa61adb5bc76e17e4acac2c"
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
        # Only the recorded protected-main predecessors are eligible for scheduling.
        # Root admission still independently binds the genuine job and continuation.
        require(
            environment.get("CALLER_BEFORE")
            in (OPERATING_BEFORE, OPERATING_CONTINUATION_BEFORE, OPERATING_PREAUTH_BEFORE,
                OPERATING_THIRD_BEFORE, OPERATING_FOURTH_BEFORE, OPERATING_FIFTH_BEFORE,
                OPERATING_SIXTH_BEFORE, OPERATING_SEVENTH_BEFORE, OPERATING_EIGHTH_BEFORE,
                OPERATING_NINTH_BEFORE, OPERATING_TENTH_BEFORE,
                OPERATING_VERIFIED_CLOSURE_BEFORE, OPERATING_PODMAN_REPAIR_BEFORE,
                OPERATING_CENSUS_HELD_BEFORE, OPERATING_SEALED_INTAKE_BEFORE,
                OPERATING_ENGINE_RETIREMENT_BEFORE, OPERATING_LEDGER_READ_BEFORE, OPERATING_PODMAN_CID_BEFORE,
                OPERATING_PODMAN_NETNS_BEFORE, OPERATING_CAPACITY_FAILURE_BEFORE,
                OPERATING_STOPPED_FAILURE_CLOSED_BEFORE, OPERATING_C22_CLOSED_BEFORE,
                OPERATING_C23_PRELEASE_BEFORE),
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
