"""Strict canonical admission producer; actual immutable consumer bindings are tested separately."""

from __future__ import annotations

import ast
import copy
import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
ACTION = ROOT / ".github/actions/admit-incus-profile"
SPEC = importlib.util.spec_from_file_location(
    "incus_admission", ACTION / "admission.py"
)
ADMISSION = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(ADMISSION)
FIXTURES = ROOT / "tests/fixtures/incus-admission"


def environment(profile="heavy"):
    value = json.loads((FIXTURES / "pending-physical-vm.json").read_text())[profile]
    return {
        **ADMISSION.CALLER,
        "PROFILE": profile,
        "MATRIX_JSON": json.dumps(value),
        "SOURCE_SHA": "a" * 40,
        "CANDIDATE_ARTIFACT": "mlx90-candidate-" + "b" * 64,
    }


class AdmissionCompilerTests(unittest.TestCase):
    def test_complete_actual_protected_main_and_pending_vm_matrices_compile_canonically(
        self,
    ):
        for fixture in FIXTURES.glob("*.json"):
            matrices = json.loads(fixture.read_text())
            for profile, matrix in matrices.items():
                env = environment(profile)
                env["MATRIX_JSON"] = json.dumps(matrix)
                selected, canonical = ADMISSION.admit(env)
                self.assertEqual(selected, profile)
                self.assertEqual(json.loads(canonical), matrix)
                self.assertEqual(
                    canonical, json.dumps(matrix, sort_keys=True, separators=(",", ":"))
                )
                self.assertEqual(
                    ADMISSION.compile_matrix(canonical, profile), canonical
                )
                if fixture.name == "pending-physical-vm.json":
                    self.assertTrue(
                        all(cell["instance_type"] == "vm" for cell in matrix["include"])
                    )

    def test_identity_artifact_limits_and_scalar_inputs_fail_before_output(self):
        env = environment()
        for key in [*ADMISSION.CALLER, "PROFILE", "SOURCE_SHA", "CANDIDATE_ARTIFACT"]:
            for bad in (None, "", "foreign", 1, True, [], {}):
                with (
                    self.subTest(key=key, value=bad),
                    self.assertRaises((ValueError, TypeError)),
                ):
                    ADMISSION.admit({**env, key: bad})

    def test_unknown_axes_cells_and_malformed_json_are_refused(self):
        original = json.loads(environment()["MATRIX_JSON"])
        bad_documents = [
            {},
            [],
            None,
            True,
            {"include": []},
            {"include": True},
            {**original, "os": ["foreign"]},
            {**original, "exclude": []},
            {"include": [None]},
            {"include": [True]},
        ]
        for bad in bad_documents:
            with self.subTest(value=bad), self.assertRaises(ValueError):
                ADMISSION.compile_matrix(json.dumps(bad), "heavy")
        for raw in (
            '{"include":[],"include":[]}',
            '{"include":[{"roles":[],"roles":[]}]}',
            '{"include":[NaN]}',
            '{"include":[Infinity]}',
            '{"include":[-Infinity]}',
            '{"include":',
            "x" * (ADMISSION.MAX_BYTES + 1),
        ):
            with self.subTest(raw=raw[:40]), self.assertRaises(ValueError):
                ADMISSION.compile_matrix(raw, "heavy")

    def test_every_cell_field_is_closed_and_fully_typed(self):
        matrix = json.loads(environment()["MATRIX_JSON"])
        for field in matrix["include"][0]:
            for bad in (None, "", 123, True, [], {}):
                changed = copy.deepcopy(matrix)
                # true is the valid value for these four exact boolean fields.
                if bad is True and field in {
                    "release_required",
                    "junit",
                    "allure",
                    "evidence",
                }:
                    continue
                changed["include"][0][field] = bad
                with (
                    self.subTest(field=field, value=bad),
                    self.assertRaises(ValueError),
                ):
                    ADMISSION.compile_matrix(json.dumps(changed), "heavy")
        for key in list(matrix["include"][0]) + ["foreign"]:
            changed = copy.deepcopy(matrix)
            if key == "foreign":
                changed["include"][0][key] = "unvalidated"
            else:
                del changed["include"][0][key]
            with self.subTest(key=key), self.assertRaises(ValueError):
                ADMISSION.compile_matrix(json.dumps(changed), "heavy")

    def test_malformed_roles_types_selectors_and_duplicate_cells_are_refused(self):
        matrix = json.loads(environment()["MATRIX_JSON"])
        invalid = {
            "roles": [[123], [None], [True], ["bad-role"], ["../escape"], ["x", "x"]],
            "instance_type": ["not-an-incus-type", "VM", ["vm"]],
            "runner": ["self-hosted", ["foreign"], ["self-hosted", True]],
            "scenario": ["../escape", "x\nattack", "a" * 64],
            "target": ["../escape", "a" * 64],
            "image": ["${{secrets.X}}", "x\nattack"],
            "component": ["keycloak+keycloak", "z+a"],
            "profile": ["application_acceptance"],
            "target_disposition": ["candidate"],
            "release_required": [False],
        }
        for field, values in invalid.items():
            for value in values:
                changed = copy.deepcopy(matrix)
                changed["include"][0][field] = value
                with (
                    self.subTest(field=field, value=value),
                    self.assertRaises(ValueError),
                ):
                    ADMISSION.compile_matrix(json.dumps(changed), "heavy")
        duplicate = {"include": matrix["include"] * 2}
        with self.assertRaises(ValueError):
            ADMISSION.compile_matrix(json.dumps(duplicate), "heavy")
        both = copy.deepcopy(matrix)
        both["include"][0]["image_variable"] = "IMAGE_REF"
        with self.assertRaises(ValueError):
            ADMISSION.compile_matrix(json.dumps(both), "heavy")
        variable = copy.deepcopy(matrix)
        del variable["include"][0]["image"]
        variable["include"][0]["image_variable"] = "RHEL_IMAGE"
        self.assertEqual(
            json.loads(ADMISSION.compile_matrix(json.dumps(variable), "heavy")),
            variable,
        )
        variable["include"][0]["image_variable"] = "not-safe"
        with self.assertRaises(ValueError):
            ADMISSION.compile_matrix(json.dumps(variable), "heavy")


class AdmissionActionBoundaryTests(unittest.TestCase):
    def test_action_uses_only_immutable_public_compiler_mount_and_pinned_offline_ee(
        self,
    ):
        action = yaml.safe_load((ACTION / "action.yml").read_text())
        step = action["runs"]["steps"][0]
        tree = ast.parse((ROOT / "scripts/lit-push-ready.py").read_text())
        image = next(
            ast.literal_eval(node.value)
            for node in tree.body
            if isinstance(node, ast.Assign)
            and any(
                isinstance(target, ast.Name) and target.id == "COPILOT_DEVTOOL_IMAGE"
                for target in node.targets
            )
        )
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            env = {
                **environment(),
                "PATH": os.environ["PATH"],
                "ADMISSION_ACTION_PATH": "/immutable-action",
                "GITHUB_OUTPUT": str(directory / "outputs"),
                "ARGV": str(directory / "argv"),
            }
            harness = 'docker() { printf \'%s\\n\' "$@" > "$ARGV"; }; export -f docker; bash -c "$1"'
            result = subprocess.run(
                ["bash", "-c", harness, "action-test", step["run"]],
                env=env,
                text=True,
                capture_output=True,
                timeout=10,
                check=False,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            args = (directory / "argv").read_text().splitlines()
            self.assertIn("--read-only", args)
            self.assertEqual(args[args.index("--network") + 1], "none")
            self.assertEqual(args[args.index("--user") + 1], "1000:1000")
            self.assertEqual(args[args.index("--cap-drop") + 1], "ALL")
            self.assertEqual(
                args[args.index("--security-opt") + 1], "no-new-privileges=true"
            )
            self.assertEqual(args.count("-v"), 1)
            self.assertEqual(
                args[args.index("-v") + 1], "/immutable-action:/admission:ro"
            )
            self.assertEqual(args[-3:], [image, "python3", "/admission/admission.py"])
            forwarded = {
                args[index + 1] for index, value in enumerate(args) if value == "-e"
            }
            self.assertEqual(forwarded, set(environment()))
            self.assertNotIn("GITHUB_TOKEN", forwarded)
            self.assertNotIn("--privileged", args)

    def test_actual_compiler_cli_publishes_all_or_no_outputs(self):
        env = environment()
        for bad in (False, True):
            selected = dict(env)
            if bad:
                selected["MATRIX_JSON"] = json.dumps({"include": [], "os": ["foreign"]})
            result = subprocess.run(
                [sys.executable, str(ACTION / "admission.py")],
                env=selected,
                capture_output=True,
                text=True,
                timeout=10,
                check=False,
            )
            if bad:
                self.assertNotEqual(result.returncode, 0)
                self.assertEqual(result.stdout, "")
            else:
                self.assertEqual(result.returncode, 0, result.stderr)
                outputs = dict(
                    line.split("=", 1) for line in result.stdout.splitlines()
                )
                self.assertEqual(outputs["profile"], "heavy")
                self.assertEqual(
                    json.loads(outputs["matrix-json"]), json.loads(env["MATRIX_JSON"])
                )
