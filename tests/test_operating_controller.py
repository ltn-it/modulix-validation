"""Root-sealed operating fixture has no free resource or business-role input."""
import base64
import importlib.util
import json
from pathlib import Path
import unittest
import tempfile

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("operating_controller", ROOT / ".github/actions/run-operating-drill/controller.py")
CONTROLLER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(CONTROLLER)


def specification(case="failure"):
    return {**CONTROLLER.FIXED_NUMBERS, "kind": "operating", "case": case,
            "image": CONTROLLER.IMAGE, "instance_name": "g06-operating-fixture"}


def environment(spec):
    return {"QUALITY_OPERATING_SPEC": json.dumps(spec), "QUALITY_OPERATING_CASE": spec["case"],
            "QUALITY_FAILURE_CUSTODY": "retain-failed-v1", "GITHUB_RUN_ID": "1234",
            "GITHUB_RUN_ATTEMPT": "1", "GITHUB_SHA": "a" * 40, "QUALITY_CONTROLLER_SHA": "b" * 40}


class OperatingControllerTests(unittest.TestCase):
    def test_exact_root_spec_maps_only_to_shared_source_vm_create(self):
        for case in CONTROLLER.CASES:
            env = environment(specification(case))
            spec = CONTROLLER.spec_from_environment(env)
            platform = CONTROLLER.source_create_variables(spec)["molecule_yml"]["platforms"][0]
            self.assertEqual(platform["type"], "vm")
            self.assertEqual(platform["image"], "quality:" + CONTROLLER.IMAGE)
            self.assertEqual(platform["resources"], {"cpu": "1", "memory": "2GiB", "disk": "5GiB"})
            self.assertNotIn("roles", json.dumps(platform))
            self.assertEqual(CONTROLLER.SOURCE_CREATE, "/workspace/molecule/shared/incus/create.yml")

    def test_unknown_fields_images_booleans_and_shrinking_are_denied(self):
        original = specification()
        for key, value in (("cpu", True), ("root_disk_bytes", 3 * 1024**3),
                           ("total_disk_bytes", 4 * 1024**3), ("project_reservation_bytes", 6 * 1024**3),
                           ("image", "images:ubuntu/24.04"), ("instance_name", "other; effect"),
                           ("case", "unreviewed"), ("caller_accept", True)):
            with self.subTest(key=key), self.assertRaises(ValueError):
                CONTROLLER.spec_from_environment(environment(original | {key: value}))
        with self.assertRaises(ValueError):
            CONTROLLER.spec_from_environment(environment(original) | {"QUALITY_OPERATING_CASE": "broker-cancel"})

    def test_raw_frame_never_claims_business_or_operating_acceptance(self):
        for code in (None, 23):
            spec = specification()
            frame = CONTROLLER.raw_frame(spec, environment(spec), {
                "name": spec["instance_name"], "uuid": "12345678-1234-1234-1234-123456789abc", "state": "Running",
            }, code=code)
            self.assertEqual(frame["root_finalization"], "pending")
            self.assertEqual(frame["execution"]["raw_exit_code"], code)
            self.assertNotIn("success", frame)
            self.assertNotIn("release_eligible", frame)
            self.assertNotIn("roles", frame)
            self.assertNotIn("retained", frame)

    def test_root_ready_marker_is_run_owned_not_a_caller_boolean(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "ready.json"
            uuid = "12345678-1234-1234-1234-123456789abc"
            value = {"schema": 1, "state": "operating-ready", "case": "failure",
                     "lease_id": "a" * 32, "instance_uuid": uuid}
            path.write_text(json.dumps(value))
            path.chmod(0o600)
            self.assertEqual(CONTROLLER.read_ready(path, "failure", uuid), value)
            for changed in ({"case": "broker-cancel"}, {"schema": True}, {"instance_uuid": "other"},
                            {"caller_accept": True}):
                path.write_text(json.dumps(value | changed))
                with self.subTest(changed=changed), self.assertRaises(ValueError):
                    CONTROLLER.read_ready(path, "failure", uuid)
            path.unlink()
            path.symlink_to(Path(directory) / "absent")
            with self.assertRaises((ValueError, OSError)):
                CONTROLLER.read_ready(path, "failure", uuid)

    def test_controller_sha_is_existing_root_admission_projection_not_job_input(self):
        payload = base64.urlsafe_b64encode(json.dumps({"identity": {"reusable_sha": "c" * 40}}).encode()).decode().rstrip("=")
        self.assertEqual(CONTROLLER.controller_sha({"admission": "header." + payload + ".signature"}), "c" * 40)
        for value in ("", "caller-value", "header.e30.signature"):
            with self.subTest(value=value), self.assertRaises((ValueError, TypeError)):
                CONTROLLER.controller_sha({"admission": value})
