"""Execute the real inventory phase in pinned EE; only remote/tool replies are fixtures."""

from __future__ import annotations

import ast
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
ACTION = ROOT / ".github/actions/run-quality-profile"
CONTAINER_FINGERPRINT = "a" * 64
VM_FINGERPRINT = "b" * 64


def run_inventory_phase(instance_type, *, vm_only=False, invalid_fingerprint=False):
    steps = yaml.safe_load((ACTION / "profile-steps.yml").read_text())["steps"]
    phase = next(step["run"] for step in steps if step.get("id") == "phase-4")
    engine = ast.parse((ROOT / "scripts/lit-push-ready.py").read_text())
    image = next(
        ast.literal_eval(node.value)
        for node in engine.body
        if isinstance(node, ast.Assign)
        and any(
            isinstance(target, ast.Name) and target.id == "COPILOT_DEVTOOL_IMAGE"
            for target in node.targets
        )
    )
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        binaries = root / "bin"
        binaries.mkdir()
        fixture = f"""#!{sys.executable}
import json,os,sys
from pathlib import Path
name=Path(sys.argv[0]).name
with open(os.environ['TOOL_CALLS'],'a') as f:f.write(json.dumps([name,*sys.argv[1:]])+'\\n')
if name=='ansible':print('ansible [core 2.18.18]')
elif name=='molecule':print('molecule 25.12.0')
elif name=='ansible-galaxy':print(json.dumps({{'/fixture/collections':{{'community.general':{{'version':'11.4.9'}}}}}}))
elif name=='incus' and sys.argv[1:]==['version']:print('Client version: 7.6')
elif name=='incus' and sys.argv[1:4]==['image','info','images:ubuntu/24.04']:
    vm='--vm' in sys.argv[4:]
    if os.environ['VM_ONLY']=='1' and not vm:raise SystemExit(44)
    fingerprint=('b' if vm else 'a')*64
    if os.environ['INVALID_FINGERPRINT']=='1':fingerprint='not-a-fingerprint'
    print('Fingerprint: '+fingerprint)
else:raise SystemExit(91)
"""
        for command in ("ansible", "molecule", "ansible-galaxy", "incus"):
            path = binaries / command
            path.write_text(fixture)
            path.chmod(0o755)
        env = {
            **os.environ,
            "BASH_ENV": "/dev/null",
            "PATH": f"{binaries}:{os.environ['PATH']}",
            "TOOL_CALLS": str(root / "calls.jsonl"),
            "VM_ONLY": str(int(vm_only)),
            "INVALID_FINGERPRINT": str(int(invalid_fingerprint)),
            "QUALITY_ARTIFACT_ROOT": str(root / "evidence"),
            "QUALITY_DEVTOOLS_IMAGE": image,
            "KEYCLOAK_TEST_IMAGE": "images:ubuntu/24.04",
            "KEYCLOAK_TEST_INSTANCE_TYPE": instance_type,
            "GITHUB_REPOSITORY": "ltn-it/modulix-validation",
            "QUALITY_SOURCE_SHA": "c" * 40,
            "GITHUB_RUN_ID": "42",
            "GITHUB_RUN_ATTEMPT": "1",
            "QUALITY_PROFILE": "heavy",
            "QUALITY_SCENARIO": "keycloak-heavy",
            "QUALITY_TARGET": "ubuntu-24.04",
            "PIP_DISABLE_PIP_VERSION_CHECK": "1",
        }
        result = subprocess.run(
            ["bash", "-c", phase],
            env=env,
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=False,
            timeout=30,
        )
        evidence_path = root / "evidence/dependencies/incus-base-image.json"
        controller_path = root / "evidence/configuration/controller-environment.json"
        calls_path = root / "calls.jsonl"
        return {
            "rc": result.returncode,
            "stderr": result.stderr,
            "image": json.loads(evidence_path.read_text())
            if evidence_path.exists()
            else None,
            "controller": json.loads(controller_path.read_text())
            if controller_path.exists()
            else None,
            "calls": [json.loads(line) for line in calls_path.read_text().splitlines()]
            if calls_path.exists()
            else [],
        }


class QualityImageProvenanceTests(unittest.TestCase):
    def test_alias_with_distinct_vm_and_container_images_records_the_selected_type(
        self,
    ):
        for kind, fingerprint in (
            ("vm", VM_FINGERPRINT),
            ("container", CONTAINER_FINGERPRINT),
        ):
            with self.subTest(kind=kind):
                actual = run_inventory_phase(kind)
                self.assertEqual(actual["rc"], 0, actual["stderr"])
                self.assertEqual(actual["image"]["fingerprint"], fingerprint)
                self.assertEqual(actual["image"]["reference"], "images:ubuntu/24.04")
                self.assertEqual(actual["image"].get("instance_type"), kind)
                self.assertEqual(actual["controller"]["requested_instance_type"], kind)
                expected = ["incus", "image", "info", "images:ubuntu/24.04"] + (
                    ["--vm"] if kind == "vm" else []
                )
                self.assertIn(expected, actual["calls"])

    def test_vm_only_alias_is_not_retried_or_resolved_as_a_container(self):
        actual = run_inventory_phase("vm", vm_only=True)
        self.assertEqual(actual["rc"], 0, actual["stderr"])
        self.assertEqual(actual["image"]["fingerprint"], VM_FINGERPRINT)
        lookups = [
            row for row in actual["calls"] if row[0:3] == ["incus", "image", "info"]
        ]
        self.assertEqual(
            lookups, [["incus", "image", "info", "images:ubuntu/24.04", "--vm"]]
        )

    def test_unknown_type_and_invalid_fingerprint_never_publish_base_image_identity(
        self,
    ):
        actual = run_inventory_phase("not-a-type")
        self.assertNotEqual(actual["rc"], 0)
        self.assertIsNone(actual["image"])
        self.assertFalse(any(row[0] == "incus" for row in actual["calls"]))
        actual = run_inventory_phase("vm", invalid_fingerprint=True)
        self.assertNotEqual(actual["rc"], 0)
        self.assertIsNone(actual["image"])
