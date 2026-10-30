"""Exercise the receiver trust boundary without a credential or network."""

import copy
import hashlib
import importlib.util
import unittest
from pathlib import Path

SPEC = importlib.util.spec_from_file_location(
    "collection_candidate_request",
    Path(__file__).resolve().parents[1] / "scripts/collection_candidate_request.py",
)
adapter = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(adapter)


class CandidateRequestTests(unittest.TestCase):
    def setUp(self):
        self.controller_sha = "a" * 40
        self.repository = "collection-candidates"
        self.url = "https://nexus.example.invalid/repository/collection-candidates"
        self.request = {
            "apiVersion": "lit.mlx90.collection-validation-request/v2",
            "kind": "CollectionValidationRequest",
            "controller": adapter._identity(
                adapter.CONTROLLER_REPOSITORY,
                adapter.CONTROLLER_WORKFLOW,
                self.controller_sha,
            ),
            "source": {
                **adapter._identity(
                    adapter.SOURCE_REPOSITORY, adapter.SOURCE_WORKFLOW, "b" * 40
                ),
                "actor": adapter.APP_ACTOR,
                "actorId": adapter.APP_ACTOR_ID,
                "actorType": "Bot",
                "event": "workflow_dispatch",
                "runId": 12,
                "runAttempt": 1,
            },
            "security": {"evidenceId": "MLX90-TEST123", "humanActions": 0},
            "candidate": {
                "name": "lit-supplementary-1.2.3.tar.gz",
                "version": "1.2.3",
                "size": 42,
                "sha256": "sha256:" + "c" * 64,
                "nexus": {
                    "repository": self.repository,
                    "repositoryUrl": self.url,
                    "url": self.url
                    + "/api/v3/plugin/ansible/content/published/collections/artifacts/lit-supplementary-1.2.3.tar.gz",
                },
            },
        }

    def validate(self, request=None, raw=None, request_id=None, **policy):
        raw = raw if raw is not None else adapter.canonical(request or self.request)
        return adapter.validate_request(
            request_id or hashlib.sha256(raw.encode()).hexdigest(),
            raw,
            controller_sha=self.controller_sha,
            nexus_repository=policy.get("repository", self.repository),
            nexus_repository_url=policy.get("url", self.url),
        )

    def test_exact_request_is_accepted(self):
        self.assertEqual(self.validate(), self.request)

    def test_retired_source_and_controller_names_are_not_current_identity(self):
        for section, repository in (
            ("source", "lightning-it/ansible-collection-supplementary"),
            ("controller", "lightning-it/modulix-validation"),
        ):
            request = copy.deepcopy(self.request)
            request[section]["repository"] = repository
            with self.subTest(section=section), self.assertRaises(adapter.RequestError):
                self.validate(request)

    def test_wrong_hash_noncanonical_duplicate_and_oversized_json_fail(self):
        canonical = adapter.canonical(self.request)
        for raw, request_id in [
            (canonical, "0" * 64),
            (canonical + " ", None),
            (
                canonical.replace(
                    '"humanActions":0', '"humanActions":0,"humanActions":0'
                ),
                None,
            ),
            (" " * 16385, None),
            ("[]", None),
        ]:
            with self.subTest(raw=raw[:40]), self.assertRaises(adapter.RequestError):
                self.validate(raw=raw, request_id=request_id)

    def test_each_identity_and_eligibility_binding_fails_closed(self):
        changes = [
            ("source", "repository", "other/repository"),
            ("source", "workflow", "other.yml"),
            ("source", "actor", "litroc"),
            ("source", "actorId", True),
            ("source", "runAttempt", True),
            ("source", "runId", 0),
            ("source", "sha", "b" * 39),
            ("source", "event", "push"),
            ("source", "ref", "refs/heads/develop"),
            ("controller", "sha", "d" * 40),
            ("controller", "ref", "refs/heads/develop"),
            ("security", "humanActions", False),
            ("security", "humanActions", 1),
            ("candidate", "name", "../lit-supplementary-1.2.3.tar.gz"),
            ("candidate", "size", True),
            ("candidate", "size", adapter.MAX_CANDIDATE_BYTES + 1),
            ("candidate", "sha256", "c" * 64),
            ("candidate", "version", "01.2.3"),
        ]
        for section, key, value in changes:
            with self.subTest(section=section, key=key):
                request = copy.deepcopy(self.request)
                request[section][key] = value
                with self.assertRaises(adapter.RequestError):
                    self.validate(request)

    def test_nexus_request_cannot_select_credentials_destination(self):
        for key in ("url", "repositoryUrl", "repository"):
            request = copy.deepcopy(self.request)
            request["candidate"]["nexus"][key] = "https://attacker.invalid"
            with self.subTest(key=key), self.assertRaises(adapter.RequestError):
                self.validate(request)

    def test_unsafe_configured_nexus_urls_fail_before_network(self):
        for url in [
            self.url + "/",
            self.url + "?token=x",
            self.url + "#fragment",
            self.url.replace("https:", "http:"),
            self.url.replace("nexus.", "user:pass@nexus."),
            self.url.replace("invalid/", "invalid:8443/"),
            self.url + "%0a",
        ]:
            with self.subTest(url=url), self.assertRaises(adapter.RequestError):
                self.validate(url=url)

    def source_run(self):
        source = self.request["source"]
        actor = {"login": adapter.APP_ACTOR, "id": adapter.APP_ACTOR_ID, "type": "Bot"}
        return {
            "id": source["runId"],
            "run_attempt": source["runAttempt"],
            "head_sha": source["sha"],
            "head_branch": "main",
            "path": adapter.SOURCE_WORKFLOW,
            "event": "workflow_dispatch",
            "status": "in_progress",
            "conclusion": None,
            "repository": {"full_name": adapter.SOURCE_REPOSITORY},
            "head_repository": {"full_name": adapter.SOURCE_REPOSITORY},
            "actor": actor,
            "triggering_actor": actor.copy(),
        }

    def test_waiting_live_producer_is_accepted(self):
        adapter.validate_source_run(self.request, self.source_run())

    def test_replayed_rerun_fork_human_and_failed_producers_fail(self):
        for key, value in [
            ("run_attempt", 2),
            ("head_sha", "e" * 40),
            ("status", "completed"),
            ("conclusion", "failure"),
            ("head_repository", {"full_name": "fork/source"}),
            ("triggering_actor", {"login": "litroc", "id": 123, "type": "User"}),
            ("path", "other.yml"),
            ("event", "push"),
            ("id", True),
        ]:
            with self.subTest(key=key), self.assertRaises(adapter.RequestError):
                run = self.source_run()
                run[key] = value
                adapter.validate_source_run(self.request, run)


if __name__ == "__main__":
    unittest.main()
