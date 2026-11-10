from __future__ import annotations

import hashlib
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "quality_snapshot_driver", ROOT / ".github/actions/run-quality-profile/run-cell.py"
)
DRIVER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(DRIVER)


class QualitySourceSnapshotTests(unittest.TestCase):
    def fixture(self, root):
        workspace = root / "workspace"
        workspace.mkdir()
        files = {"galaxy.yml": b"version: 1.2.3\n", "molecule/fixture/molecule.yml": b"driver: default\n",
                 "run.sh": b"#!/bin/sh\nexit 0\n", "empty": b""}
        entries = []
        for name, raw in sorted(files.items()):
            path = workspace / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(raw)
            mode = "100755" if name == "run.sh" else "100644"
            path.chmod(0o700 if mode == "100755" else 0o600)
            entries.append({"path": name, "mode": mode, "size": len(raw),
                            "oid": hashlib.sha1(b"blob "+str(len(raw)).encode()+b"\0"+raw).hexdigest()})
        value = {"schema": 1, "repository": "ltn-it/ansible-collection-supplementary",
                 "repository_id": 1103407173, "commit_sha": "f"*40, "tree_sha": "e"*40, "files": entries}
        proof = root / "source-provenance.json"
        proof.write_text(json.dumps(value))
        return workspace, proof, value, files

    def test_exact_archive_without_git_metadata_and_evidence_blob_reader(self):
        with tempfile.TemporaryDirectory() as temporary:
            workspace, proof, value, files = self.fixture(Path(temporary))
            self.assertFalse((workspace/".git").exists())
            DRIVER.verify_source_snapshot(workspace, proof, value["commit_sha"])
            entries = DRIVER.source_snapshot(proof, value["commit_sha"])
            for name, raw in files.items():
                self.assertEqual(raw, DRIVER.snapshot_blob(workspace, entries, name))
            self.assertFalse((workspace/".git").exists(), "verification must not manufacture a checkout")

    def test_changed_missing_extra_mode_or_linked_source_denies(self):
        for case in ("changed", "missing", "extra", "mode", "link", "extra-directory"):
            with self.subTest(case=case), tempfile.TemporaryDirectory() as temporary:
                workspace, proof, value, files = self.fixture(Path(temporary))
                path = workspace/"galaxy.yml"
                if case == "changed":
                    path.write_bytes(b"Version: 1.2.3\n")
                elif case == "missing":
                    path.unlink()
                elif case == "extra":
                    (workspace/"untracked").write_text("untracked")
                elif case == "mode":
                    (workspace/"run.sh").chmod(0o600)
                elif case == "link":
                    path.unlink()
                    path.symlink_to(proof)
                else:
                    (workspace/"untracked-directory").mkdir()
                with self.assertRaises((ValueError, OSError)):
                    DRIVER.verify_source_snapshot(workspace, proof, value["commit_sha"])

    def test_closed_provenance_identity_and_path_schema(self):
        variants = ({"repository_id": True}, {"repository": "foreign/repository"},
                    {"commit_sha": "a"*40}, {"extra": "not admitted"})
        with tempfile.TemporaryDirectory() as temporary:
            workspace, proof, value, files = self.fixture(Path(temporary))
            for changed in variants:
                proof.write_text(json.dumps({**value, **changed}))
                with self.subTest(changed=changed), self.assertRaises(ValueError):
                    DRIVER.source_snapshot(proof, value["commit_sha"])
            for changed in ({"path": "../outside"}, {"path": "."}, {"path": ".git/HEAD"},
                            {"size": True}, {"mode": "120000"}):
                proof.write_text(json.dumps({**value, "files": [{**value["files"][0], **changed}]}))
                with self.subTest(changed=changed), self.assertRaises(ValueError):
                    DRIVER.source_snapshot(proof, value["commit_sha"])
            proof.write_text(json.dumps({**value, "files": [value["files"][0], value["files"][0]]}))
            with self.assertRaises(ValueError):
                DRIVER.source_snapshot(proof, value["commit_sha"])


if __name__ == "__main__":
    unittest.main()
