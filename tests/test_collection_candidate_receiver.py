"""Exercise exact-byte readback and receipt gating without network or infrastructure."""

import copy
import hashlib
import io
import json
import os
import stat
import subprocess
import sys
import tempfile
import unittest
import urllib.error
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import collection_candidate_receiver as receiver
import test_collection_candidate_request as request_fixtures


class Response(io.BytesIO):
    def __init__(self, body, url, status=200, length=None):
        super().__init__(body)
        self.url, self.status = url, status
        self.headers = {} if length is None else {"Content-Length": length}

    def geturl(self):
        return self.url


class Opener:
    def __init__(self, response):
        self.response, self.calls = response, []

    def open(self, request, timeout):
        self.calls.append((request, timeout))
        if isinstance(self.response, Exception):
            raise self.response
        return self.response


class ReceiverTests(unittest.TestCase):
    def setUp(self):
        fixture = request_fixtures.CandidateRequestTests()
        fixture.setUp()
        self.request = fixture.request
        self.body = b"immutable Nexus candidate"
        self.digest = hashlib.sha256(self.body).hexdigest()
        self.request["candidate"].update(
            size=len(self.body), sha256=f"sha256:{self.digest}"
        )
        self.request_id = hashlib.sha256(
            receiver.canonical(self.request).encode()
        ).hexdigest()
        self.url = self.request["candidate"]["nexus"]["url"]
        actor = {
            "login": receiver.APP_ACTOR,
            "id": receiver.APP_ACTOR_ID,
            "type": "Bot",
        }
        self.run = {
            "id": 99,
            "run_attempt": 1,
            "head_sha": self.request["controller"]["sha"],
            "head_branch": "main",
            "path": receiver.CONTROLLER_WORKFLOW,
            "event": "workflow_dispatch",
            "status": "in_progress",
            "conclusion": None,
            "display_title": f"MLX-90 collection candidate / {self.request_id}",
            "repository": {"full_name": receiver.CONTROLLER_REPOSITORY},
            "head_repository": {"full_name": receiver.CONTROLLER_REPOSITORY},
            "actor": actor,
            "triggering_actor": actor.copy(),
        }
        self.jobs = [
            {
                "name": name,
                "run_id": 99,
                "run_attempt": 1,
                "status": "in_progress"
                if name == "Sign validation receipt"
                else "completed",
                "conclusion": None if name == "Sign validation receipt" else "success",
            }
            for name in [
                "Validate immutable request",
                "Nexus exact-byte readback",
                "Heavy / scenario / target",
                "Application Acceptance / scenario / target",
                "Sign validation receipt",
            ]
        ]

    def test_exact_authenticated_readback_retains_identical_bytes(self):
        opener = Opener(Response(self.body, self.url, length=str(len(self.body))))
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "candidate.tar.gz"
            receiver.exact_readback(
                self.request,
                {"username": "reader", "password": "fixture"},
                output,
                opener,
            )
            self.assertEqual(output.read_bytes(), self.body)
            self.assertEqual(len(opener.calls), 1)
            outgoing, timeout = opener.calls[0]
            self.assertEqual(outgoing.full_url, self.url)
            self.assertEqual(outgoing.method, "GET")
            self.assertTrue(outgoing.headers["Authorization"].startswith("Basic "))
            self.assertEqual(timeout, 120)

    def test_missing_reader_stops_before_network(self):
        for credentials in (
            {},
            {"username": "reader"},
            {"username": "user:invalid", "password": "fixture"},
        ):
            opener = Opener(Response(self.body, self.url))
            with (
                self.subTest(credentials=credentials),
                self.assertRaises(receiver.RequestError),
            ):
                receiver.exact_readback(
                    self.request, credentials, Path("unused"), opener
                )
            self.assertFalse(opener.calls)

    def test_redirect_size_digest_status_and_network_fail_without_replacement_or_retry(
        self,
    ):
        for response in [
            Response(self.body, "https://other.invalid/candidate"),
            Response(self.body, self.url, status=302),
            Response(self.body, self.url, length="123"),
            Response(self.body[:-1], self.url),
            Response(self.body + b"x", self.url),
            Response(b"x" * len(self.body), self.url),
            urllib.error.URLError("fixture-provider-error"),
        ]:
            opener = Opener(response)
            with tempfile.TemporaryDirectory() as temporary:
                output = Path(temporary) / "candidate.tar.gz"
                output.write_bytes(b"previous")
                with self.assertRaises(receiver.RequestError):
                    receiver.exact_readback(
                        self.request,
                        {"username": "reader", "password": "fixture"},
                        output,
                        opener,
                    )
                self.assertEqual(output.read_bytes(), b"previous")
                self.assertEqual(
                    [p.name for p in Path(temporary).iterdir()], [output.name]
                )
                self.assertEqual(len(opener.calls), 1)

    def staged_candidate(self, root):
        stage, output = root / "stage", root / "output"
        stage.mkdir()
        output.mkdir()
        name = self.request["candidate"]["name"]
        (stage / name).write_bytes(self.body)
        (output / name).write_bytes(self.body)
        bundle = b"tested dependency bundle fixture"
        (stage / "runtime-collections.tar.gz").write_bytes(bundle)
        (stage / "candidate-SHA256SUMS").write_text(
            f"{self.digest}  {name}\n{hashlib.sha256(bundle).hexdigest()}  runtime-collections.tar.gz\n"
        )
        return stage, output

    def test_producer_dependencies_remain_exact_and_candidate_is_never_rebuilt(self):
        with tempfile.TemporaryDirectory() as temporary:
            stage, output = self.staged_candidate(Path(temporary))
            receiver.prepare_candidate(self.request, stage, output)
            self.assertEqual(
                (output / "runtime-collections.tar.gz").read_bytes(),
                (stage / "runtime-collections.tar.gz").read_bytes(),
            )
            self.assertEqual(
                (output / self.request["candidate"]["name"]).read_bytes(), self.body
            )

    def test_substituted_dependency_checksum_inventory_and_nexus_file_fail(self):
        for mutation in ("bundle", "extra", "duplicate", "candidate", "link"):
            with tempfile.TemporaryDirectory() as temporary:
                stage, output = self.staged_candidate(Path(temporary))
                manifest = stage / "candidate-SHA256SUMS"
                if mutation == "bundle":
                    (stage / "runtime-collections.tar.gz").write_bytes(b"different")
                elif mutation == "extra":
                    manifest.write_text(
                        manifest.read_text() + f"{'0' * 64}  extra.tar.gz\n"
                    )
                elif mutation == "duplicate":
                    manifest.write_text(manifest.read_text() * 2)
                elif mutation == "candidate":
                    (output / self.request["candidate"]["name"]).write_bytes(
                        b"different"
                    )
                else:
                    bundle = stage / "runtime-collections.tar.gz"
                    bundle.unlink()
                    bundle.symlink_to(manifest)
                with (
                    self.subTest(mutation=mutation),
                    self.assertRaises(receiver.RequestError),
                ):
                    receiver.prepare_candidate(self.request, stage, output)

    def test_receipt_exactly_confirms_request_and_completed_real_profiles(self):
        receipt = receiver.validation_receipt(
            self.request, self.request_id, self.run, self.jobs
        )
        self.assertEqual(receipt["request"], self.request)
        self.assertEqual(receipt["requestId"], "sha256:" + self.request_id)
        self.assertEqual(
            receipt["validation"]["observations"]["sourceRun"], self.request["source"]
        )
        self.assertTrue(all(receipt["decision"].values()))

    def test_missing_skipped_failed_duplicate_and_foreign_attempt_jobs_block_receipt(
        self,
    ):
        for mutation in (
            "empty",
            "missing",
            "skip",
            "failed",
            "duplicate",
            "attempt",
            "noop",
        ):
            jobs = copy.deepcopy(self.jobs)
            if mutation == "empty":
                jobs = []
            elif mutation == "missing":
                jobs.pop(0)
            elif mutation == "skip":
                jobs[2]["conclusion"] = "skipped"
            elif mutation == "failed":
                jobs[3]["conclusion"] = "failure"
            elif mutation == "duplicate":
                jobs.append(jobs[2])
            elif mutation == "attempt":
                jobs[2]["run_attempt"] = 2
            else:
                jobs[2]["name"] = "Transition no-op"
            with (
                self.subTest(mutation=mutation),
                self.assertRaises(receiver.RequestError),
            ):
                receiver.validation_receipt(
                    self.request, self.request_id, self.run, jobs
                )

    def test_foreign_actor_ref_sha_and_rerun_identity_are_rejected(self):
        for key, value in [
            ("head_sha", "f" * 40),
            ("head_branch", "develop"),
            ("run_attempt", True),
            ("display_title", "other"),
            ("triggering_actor", {"login": "litroc", "id": 1, "type": "User"}),
        ]:
            run = copy.deepcopy(self.run)
            run[key] = value
            with self.subTest(key=key), self.assertRaises(receiver.RequestError):
                receiver.controller_identity(run, self.request, self.request_id)


class WorkflowCodeTests(unittest.TestCase):
    def test_private_context_preserves_runner_uid_for_subsequent_devtools_steps(self):
        import yaml

        root = Path(__file__).resolve().parents[1]
        context = yaml.safe_load(
            (
                root / ".github/actions/collection-candidate-context/action.yml"
            ).read_text()
        )
        materialize = next(
            step
            for step in context["runs"]["steps"]
            if step["name"]
            == "Materialize nonsecret request and protected endpoint policy"
        )
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            environment = dict(os.environ)
            environment.update(
                GITHUB_ENV=str(directory / "github-env"),
                REQUEST_JSON='{"version":2}',
                NEXUS_REPOSITORY="fixture-candidates",
                NEXUS_REPOSITORY_URL="https://fixture.invalid/repository/candidates",
            )
            subprocess.run(
                ["bash", "-c", materialize["run"]],
                cwd=directory,
                env=environment,
                check=True,
                capture_output=True,
                text=True,
            )
            self.assertIn(
                "WUNDER_DEVTOOLS_RUN_AS_HOST_UID=1",
                (directory / "github-env").read_text().splitlines(),
            )
            control = directory / ".candidate-control"
            self.assertEqual(stat.S_IMODE(control.stat().st_mode), 0o700)
            for name in ("request.json", "config.json"):
                self.assertEqual(stat.S_IMODE((control / name).stat().st_mode), 0o600)

    def test_receipt_jobs_are_flattened_across_native_api_pages(self):
        import yaml

        root = Path(__file__).resolve().parents[1]
        workflow = yaml.safe_load(
            (
                root / ".github/workflows/mlx90-collection-candidate-validation.yml"
            ).read_text()
        )
        binding = next(
            step
            for step in workflow["jobs"]["sign"]["steps"]
            if step.get("name")
            == "Bind receipt to every real current-attempt native job"
        )
        command = binding["run"].split("WUNDER_DEVTOOLS_WORKSPACE_MODE=", 1)[0]
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            (directory / ".candidate-control").mkdir()
            binary = directory / "bin"
            binary.mkdir()
            gh = binary / "gh"
            gh.write_text(
                "#!/bin/sh\nset -eu\n"
                'for argument in "$@"; do\n'
                '  test "$argument" != --jq || exit 9\n'
                'done\nprintf "%s\\n" "$@" > "$GH_ARGS"\n'
                'printf "%s\\n" "$JOB_PAGES"\n'
            )
            gh.chmod(0o700)
            jobs = [{"id": value} for value in (1, 2, 3)]
            environment = dict(os.environ)
            environment.update(
                PATH=f"{binary}:{environment['PATH']}",
                GH_ARGS=str(directory / "gh-args"),
                JOB_PAGES=json.dumps([{"jobs": jobs[:2]}, {"jobs": jobs[2:]}]),
                GITHUB_REPOSITORY="ltn-it/modulix-validation",
                GITHUB_RUN_ID="42",
                GITHUB_RUN_ATTEMPT="1",
            )
            subprocess.run(
                ["bash", "-c", command],
                cwd=directory,
                env=environment,
                check=True,
                capture_output=True,
                text=True,
            )
            self.assertEqual(
                json.loads((directory / ".candidate-control/jobs.json").read_text()),
                jobs,
            )
            arguments = (directory / "gh-args").read_text().splitlines()
            self.assertIn("--paginate", arguments)
            self.assertIn("--slurp", arguments)

    def test_required_profiles_and_signature_depend_on_success_without_noop(self):
        import yaml

        root = Path(__file__).resolve().parents[1]
        value = yaml.safe_load(
            (
                root / ".github/workflows/mlx90-collection-candidate-validation.yml"
            ).read_text()
        )
        jobs = value["jobs"]
        self.assertEqual(
            set(jobs), {"validate", "readback", "heavy", "application", "sign"}
        )
        self.assertEqual(
            set(jobs["sign"]["needs"]), {"validate", "readback", "heavy", "application"}
        )
        for job in jobs.values():
            self.assertNotIn("continue-on-error", job)
            self.assertNotIn("if", job)
            self.assertLessEqual(job["timeout-minutes"], 90)
        self.assertEqual(jobs["sign"]["permissions"]["id-token"], "write")
        self.assertTrue(
            all(
                jobs[job]["strategy"]["fail-fast"] is False
                for job in ("heavy", "application")
            )
        )
        context = (
            root / ".github/actions/collection-candidate-context/action.yml"
        ).read_text()
        self.assertIn('test "$REF" = refs/heads/main', context)
        self.assertIn('test "$ATTEMPT" = 1', context)
        self.assertTrue(
            (root / ".github/workflows/collection-release-transition.yml").is_file()
        )


if __name__ == "__main__":
    unittest.main()
