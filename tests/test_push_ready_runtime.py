import importlib.util
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "lit_push_ready_validation_tests",
    ROOT / "scripts" / "lit-push-ready.py",
)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError("could not load scripts/lit-push-ready.py for tests")
PUSH_READY = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(PUSH_READY)


class PushReadyRuntimeTests(unittest.TestCase):
    def test_renamed_origin_formats_keep_their_exact_owner_binding(self):
        for url in (
            "https://github.com/ltn-it/modulix-validation.git",
            "ssh://git@github.com/ltn-it/modulix-validation.git",
            "git@github.com:ltn-it/modulix-validation.git",
        ):
            with self.subTest(url=url):
                current = PUSH_READY.governed_push_remote_from_url("origin", url)
                self.assertEqual("ltn-it/modulix-validation", current["repository"])
                legacy = PUSH_READY.governed_push_remote_from_url(
                    "origin", url.replace("ltn-it", "lightning-it")
                )
                self.assertEqual("lightning-it/modulix-validation", legacy["repository"])
                self.assertNotEqual(current["url_sha256"], legacy["url_sha256"])

    def test_renamed_fetch_does_not_reuse_a_differently_bound_push_remote(self):
        with mock.patch.object(
            PUSH_READY,
            "git_output",
            side_effect=[
                "https://github.com/ltn-it/modulix-validation.git",
                "https://github.com/lightning-it/modulix-validation.git",
            ],
        ):
            with self.assertRaisesRegex(RuntimeError, "same governed repository"):
                PUSH_READY.fetch_authoritative_base("develop", "refs/remotes/origin/develop")

    def test_https_base_fetch_uses_scoped_header_not_argv(self):
        completed = object()
        runner = mock.Mock(return_value=completed)
        with mock.patch.object(
            PUSH_READY,
            "git_output",
            side_effect=[
                "https://github.com/lightning-it/example.git\n",
                "https://github.com/lightning-it/example.git\n",
            ],
        ), mock.patch.object(
            PUSH_READY,
            "github_https_authorization",
            return_value="AUTHORIZATION: basic masked-value",
        ), mock.patch.object(PUSH_READY.subprocess, "run", runner):
            result = PUSH_READY.fetch_authoritative_base(
                "develop", "refs/remotes/origin/develop"
            )
        self.assertIs(result, completed)
        self.assertNotIn("masked-value", " ".join(runner.call_args.args[0]))
        self.assertEqual(
            "AUTHORIZATION: basic masked-value",
            runner.call_args.kwargs["env"]["GIT_CONFIG_VALUE_0"],
        )

    def test_base_fetch_rejects_mismatched_fetch_and_push_repositories(self):
        with mock.patch.object(
            PUSH_READY,
            "git_output",
            side_effect=[
                "git@github.com:lightning-it/other.git",
                "https://github.com/lightning-it/example.git",
            ],
        ):
            with self.assertRaisesRegex(RuntimeError, "same governed repository"):
                PUSH_READY.fetch_authoritative_base(
                    "develop", "refs/remotes/origin/develop"
                )

    def change(
        self,
        *,
        diff: str = "safe\n",
        paths: tuple[str, ...] = ("safe.txt",),
    ):
        return PUSH_READY.PlannedChange(
            "refs/remotes/origin/develop",
            "1" * 40,
            "1" * 40,
            "2" * 40,
            diff,
            paths,
            {},
            "3" * 64,
        )

    def test_review_rejects_secret_paths_and_content(self):
        with self.assertRaisesRegex(RuntimeError, "secret-like paths"):
            PUSH_READY.ensure_review_safe(
                self.change(paths=("inventories/secrets/runtime.yml",))
            )
        with self.assertRaisesRegex(RuntimeError, "secret-like content"):
            PUSH_READY.ensure_review_safe(
                self.change(diff="+ token = ghp_" + "a" * 36 + "\n")
            )

    def test_pre_push_accepts_only_the_reviewed_new_branch_head(self):
        remote_url = "https://github.com/lightning-it/modulix-validation.git"
        branch = "refs/heads/feature/example"
        payload = {
            "push_remote": PUSH_READY.governed_push_remote_from_url(
                "origin",
                remote_url,
            ),
            "head_commit": "2" * 40,
            "local_branch_ref": branch,
        }
        reviewed = f"{branch} {'2' * 40} {branch} {'0' * 40}\n"
        with mock.patch.object(
            PUSH_READY,
            "git_output",
            return_value="2" * 40,
        ):
            PUSH_READY.verify_pre_push_updates(
                payload,
                reviewed,
                remote_name="origin",
                remote_url=remote_url,
            )

        unreviewed = f"{branch} {'4' * 40} {branch} {'0' * 40}\n"
        with mock.patch.object(
            PUSH_READY,
            "git_output",
            return_value="4" * 40,
        ):
            with self.assertRaisesRegex(RuntimeError, "not bound"):
                PUSH_READY.verify_pre_push_updates(
                    payload,
                    unreviewed,
                    remote_name="origin",
                    remote_url=remote_url,
                )

    def test_trusted_policy_rejects_a_changed_policy_entry(self):
        change = self.change()

        def tree_entry(commit, _path):
            return "base-entry" if commit == change.base_tip else "head-entry"

        with mock.patch.object(
            PUSH_READY,
            "git_tree_entry",
            side_effect=tree_entry,
        ):
            with self.assertRaisesRegex(
                RuntimeError,
                "executable check policy differs",
            ):
                PUSH_READY.require_trusted_check_policy(change)


if __name__ == "__main__":
    unittest.main()
