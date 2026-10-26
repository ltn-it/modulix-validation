from __future__ import annotations

import json
import hashlib
import os
import subprocess
import tarfile
import tempfile
import unittest
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
ACTION = ROOT / ".github/actions/run-quality-profile"


class QualityRuntimeRegressions(unittest.TestCase):
    def test_pinned_incus_resolves_registry_image_without_global_remotes(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "config.yml").write_text(yaml.safe_dump({
                "default-remote": "quality",
                "remotes": {
                    "quality": {"addr": "https://quality.invalid", "protocol": "incus", "public": False},
                    "images": {"addr": "https://images.linuxcontainers.org", "protocol": "simplestreams", "public": True},
                },
            }))
            # A closed local proxy makes the real client's lookup deterministic
            # and offline. Reaching the fixed image URL proves remote resolution,
            # not image download, VM execution, or live service acceptance.
            result = subprocess.run(
                ["incus", "image", "info", "images:ubuntu/24.04"],
                env={"PATH": os.environ["PATH"], "HOME": directory, "INCUS_CONF": directory,
                     "HTTPS_PROXY": "http://127.0.0.1:1"},
                capture_output=True, text=True, timeout=10, check=False,
            )
            self.assertNotEqual(0, result.returncode)
            self.assertIn("https://images.linuxcontainers.org/", result.stderr)
            self.assertIn("127.0.0.1:1", result.stderr)
            self.assertNotIn("doesn't exist", result.stderr)

    def test_absent_package_output_never_selects_runner_root(self):
        action = yaml.safe_load((ACTION / "action.yml").read_text())
        upload = next(step for step in action["runs"]["steps"] if step.get("id") == "upload")
        # GitHub resolves an absent step output to the empty string. A suffix
        # slash would turn a failed admission into a filesystem-root upload.
        reference = "${{ steps.cell.outputs.package-directory }}"
        self.assertEqual("", upload["with"]["path"].replace(reference, ""))
        self.assertIn("steps.cell.outputs.package-directory != ''", upload["if"])
        self.assertIn("steps.cell.outputs.result-artifact != ''", upload["if"])
        enforce = action["runs"]["steps"][-1]
        with tempfile.TemporaryDirectory() as directory:
            result = subprocess.run(
                ["bash", "-c", enforce["run"]],
                env={**os.environ, "CELL_OUTCOME": "failure", "UPLOAD_OUTCOME": "skipped"},
                cwd=directory, capture_output=True, check=False,
            )
        self.assertNotEqual(0, result.returncode)

    def test_vm_preflight_uses_bound_remote_server_before_candidate_install(self):
        steps = yaml.safe_load((ACTION / "profile-steps.yml").read_text())["steps"]
        phase = next(step for step in steps if step.get("id") == "phase-3")
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            calls = root / "incus-calls"
            for command in ("molecule", "openssl"):
                path = root / command
                path.write_text("#!/bin/sh\nexit 0\n")
                path.chmod(0o755)
            installer = root / "ansible-galaxy"
            installed = root / "install-calls"
            installer.write_text('#!/bin/sh\nprintf "%s\\n" "$*" >> "$INSTALL_CALLS"\n')
            installer.chmod(0o755)
            candidate = root / "candidate"
            candidate.mkdir()
            (candidate / "lit-supplementary-4.1.0.tar.gz").write_bytes(b"synthetic candidate; install is recorded only")
            with tarfile.open(candidate / "runtime-collections.tar.gz", "w:gz") as stream:
                entry = tarfile.TarInfo("ansible_collections")
                entry.type = tarfile.DIRTYPE
                stream.addfile(entry)
            checksums = [f"{hashlib.sha256(path.read_bytes()).hexdigest()}  {path.name}\n" for path in candidate.iterdir()]
            (candidate / "candidate-SHA256SUMS").write_text("".join(checksums))
            (root / "galaxy.yml").write_text("dependencies: {}\n")
            incus = root / "incus"
            incus.write_text(
                '#!/bin/sh\nprintf "%s\\n" "$*" >> "$INCUS_CALLS"\n'
                'if [ "$1" = query ]; then printf "%s\\n" "$SERVER_METADATA"; fi\n'
            )
            incus.chmod(0o755)
            # Capacity is a separate preflight contract; give this VM capability
            # regression deterministic sufficient disk and client memory.
            awk = root / "awk"
            awk.write_text("#!/bin/sh\nprintf '20971520\\n'\n")
            awk.chmod(0o755)
            (root / "scripts").mkdir()
            (root / "scripts/prune_stale_incus_resources.py").write_text("")
            # The actual phase must work without exposing the client's /dev/kvm.
            for metadata, expected in (
                ({"environment": {"driver": "lxc | qemu"}}, 0),
                ({"environment": {"driver": "lxc"}}, 1),
                ({"environment": {"driver": "not-qemu"}}, 1),
                ({"metadata": {"environment": {"driver": "qemu"}}}, 1),
                ({}, 1),
            ):
                with self.subTest(metadata=metadata):
                    calls.unlink(missing_ok=True)
                    installed.unlink(missing_ok=True)
                    result = subprocess.run(
                        ["bash", "-c", phase["run"]], cwd=root,
                        env={**os.environ, "PATH": f"{root}:{os.environ['PATH']}",
                             "KEYCLOAK_TEST_INSTANCE_TYPE": "vm", "RUNNER_TEMP": str(root),
                             "GITHUB_REPOSITORY": "ltn-it/modulix-validation", "GITHUB_RUN_ID": "123",
                             "INCUS_CALLS": str(calls), "SERVER_METADATA": json.dumps(metadata),
                             "QUALITY_CANDIDATE_ROOT": str(candidate), "QUALITY_INSTALL_ROOT": str(root / "installed"),
                             "GITHUB_ENV": str(root / "environment"), "INSTALL_CALLS": str(installed)},
                        capture_output=True, text=True, check=False,
                    )
                    self.assertEqual(expected, int(result.returncode != 0), result.stderr)
                    self.assertIn("query quality:/1.0", calls.read_text())
                    self.assertEqual(expected == 0, installed.exists())


if __name__ == "__main__":
    unittest.main()
