from __future__ import annotations

import json
import os
import re
import subprocess
import tempfile
import unittest
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
ACTION = ROOT / ".github/actions/run-quality-profile"


class QualityConnectionContractTests(unittest.TestCase):
    def fixture(self, root, addition=None):
        subprocess.run(["git", "init", "--quiet", str(root)], check=True, capture_output=True)
        config = root / "molecule/fixture/molecule.yml"
        config.parent.mkdir(parents=True, exist_ok=True)
        value = {"driver": {"name": "default"}, "platforms": [{"name": "offline-instance"}],
                 "provisioner": {"name": "ansible"}, "verifier": {"name": "ansible"}}
        value.update(addition or {})
        config.write_text(yaml.safe_dump(value))
        base = root / ".config/molecule/config.yml"
        base.parent.mkdir(parents=True, exist_ok=True)
        base.write_text("prerun: false\nrole_name_check: 0\nshared_state: false\n")

    def test_every_phase_supplies_private_vars_to_real_incus_connection_builder(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.fixture(root)
            calls = root / "calls.jsonl"
            bin_directory = root / "bin"
            bin_directory.mkdir()
            molecule = bin_directory / "molecule"
            molecule.write_text(
                "#!/usr/bin/env python3\n"
                "import json,os,stat,sys,yaml\nfrom pathlib import Path\n"
                "from ansible.plugins.loader import init_plugin_loader,connection_loader\n"
                "from ansible.playbook.play_context import PlayContext\n"
                "init_plugin_loader()\n"
                "assert sys.argv[1]=='--base-config'\n"
                "assert Path(sys.argv[2]).resolve()==Path.cwd()/'.config/molecule/config.yml',sys.argv\n"
                "assert sys.argv[3]=='--base-config'\n"
                "overlay=Path(sys.argv[4])\n"
                "assert stat.S_IMODE(overlay.stat().st_mode)==0o600\n"
                "args=yaml.safe_load(overlay.read_text())['ansible']['executor']['args']['ansible_playbook']\n"
                "assert args[0]=='--extra-vars'\n"
                "path=Path(args[1].removeprefix('@'))\n"
                "assert stat.S_IMODE(path.stat().st_mode)==0o600\n"
                "values=json.loads(path.read_bytes())\n"
                "assert values=={'ansible_incus_remote':'quality','ansible_incus_project':'bound-test-project'}\n"
                "plugin=connection_loader.get('community.general.incus',PlayContext(),None)\n"
                "plugin.set_options(var_options={'inventory_hostname':'offline-instance',"
                "'ansible_incus_remote':'local','ansible_incus_project':'default',**values})\n"
                "with open(os.environ['CALLS'],'a') as out:\n"
                " out.write(json.dumps({'phase':sys.argv[5],'command':plugin._build_command('true')})+'\\n')\n"
            )
            molecule.chmod(0o755)
            environment = {
                **os.environ, "PATH": f"{bin_directory}:{os.environ['PATH']}", "CALLS": str(calls),
                "QUALITY_INCUS_PROJECT": "bound-test-project", "QUALITY_SCENARIO": "fixture",
                "QUALITY_LOG_PATH": str(root / "log"), "GITHUB_OUTPUT": str(root / "output"),
                "TMPDIR": directory,
            }
            for phase in ("test", "cleanup", "destroy"):
                result = subprocess.run(["bash", str(ACTION / "run-phase.sh"), phase, "10"],
                                        env=environment, cwd=root, capture_output=True, text=True, check=False)
                self.assertEqual(0, result.returncode, result.stderr)
            self.assertEqual(["exit_code=0"] * 3, (root / "output").read_text().splitlines(), (root / "log").read_text())
            rows = [json.loads(line) for line in calls.read_text().splitlines()]
            self.assertEqual(["test", "cleanup", "destroy"], [row["phase"] for row in rows])
            for row in rows:
                self.assertEqual(["--project", "bound-test-project", "exec", "quality:offline-instance"], row["command"][1:5])
            self.assertEqual([], list(root.glob("quality-incus-ansible.*")))

    def test_strict_mode_and_source_argument_collisions_fail_before_molecule(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.fixture(root)
            marker = root / "called"
            bin_directory = root / "bin"
            bin_directory.mkdir()
            molecule = bin_directory / "molecule"
            molecule.write_text(f"#!/bin/sh\ntouch '{marker}'\n")
            molecule.chmod(0o755)
            variants = (
                ({}, {"MOLECULE_ANSIBLE_ARGS_STRICT_MODE": "1"}),
                ({"provisioner": {"name": "ansible", "ansible_args": ["-e", "ansible_incus_remote=foreign"]}}, {}),
                ({"provisioner": {"name": "ansible", "options": {"extra-vars": "ansible_incus_project=foreign"}}}, {}),
                ({"ansible": {"executor": {"args": {"ansible_playbook": []}}}}, {}),
                ({"ansible": {"env": {"MOLECULE_ANSIBLE_ARGS_STRICT_MODE": "1"}}}, {}),
            )
            for addition, environment in variants:
                self.fixture(root, addition)
                result = subprocess.run(["bash", str(ACTION / "run-phase.sh"), "destroy", "10"],
                    cwd=root, env={**os.environ, "PATH": f"{bin_directory}:{os.environ['PATH']}",
                    "QUALITY_INCUS_PROJECT": "bound-test-project", "QUALITY_SCENARIO": "fixture",
                    "QUALITY_LOG_PATH": str(root / "log"), "GITHUB_OUTPUT": str(root / "output"),
                    "TMPDIR": directory, **environment}, capture_output=True, text=True, check=False)
                self.assertNotEqual(0, result.returncode, result.stdout + result.stderr)
                self.assertFalse(marker.exists())
                self.assertEqual([], list(root.glob("quality-incus-ansible.*")))

    def test_unbound_or_invalid_project_stops_before_molecule(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            marker = root / "called"
            molecule = root / "molecule"
            molecule.write_text(f"#!/bin/sh\ntouch '{marker}'\n")
            molecule.chmod(0o755)
            for project in ("", "wrong/project", "wrong\nvalue"):
                with self.subTest(project=project):
                    result = subprocess.run(["bash", str(ACTION / "run-phase.sh"), "destroy", "10"],
                        env={**os.environ, "PATH": f"{root}:{os.environ['PATH']}",
                             "QUALITY_INCUS_PROJECT": project, "QUALITY_SCENARIO": "fixture",
                             "QUALITY_LOG_PATH": str(root / "log"), "GITHUB_OUTPUT": str(root / "output")},
                        capture_output=True, check=False)
                    self.assertNotEqual(0, result.returncode)
                    self.assertFalse(marker.exists())

    def test_actual_producer_disposition_matches_existing_consumer_contract(self):
        steps = yaml.safe_load((ACTION / "profile-steps.yml").read_text())["steps"]
        script = next(step["run"] for step in steps if step.get("id") == "phase-4")
        start = script.index('{\n  echo "mode=')
        end_marker = '} > "$dependency_root/execution-environment-digest.txt"'
        block = script[start:script.index(end_marker, start) + len(end_marker)]
        image = re.search(r'^COPILOT_DEVTOOL_IMAGE = "([^"]+)"', (ROOT / "scripts/lit-push-ready.py").read_text(), re.MULTILINE).group(1)
        with tempfile.TemporaryDirectory() as directory:
            result = subprocess.run(["bash", "-euc", block],
                env={**os.environ, "dependency_root": directory, "QUALITY_DEVTOOLS_IMAGE": image},
                capture_output=True, text=True, check=False)
            self.assertEqual(0, result.returncode, result.stderr)
            values = dict(line.split("=", 1) for line in (Path(directory) / "execution-environment-digest.txt").read_text().splitlines())
        # This is the downstream assess_dependencies contract, independently
        # exercised against its unchanged real implementation before delivery.
        self.assertEqual("execution-environment", values["mode"])
        self.assertRegex(values["digest"], r"^sha256:[0-9a-f]{64}$")
        self.assertTrue(values.get("reason", "").strip())
        self.assertEqual(image, values["image"])


if __name__ == "__main__":
    unittest.main()
