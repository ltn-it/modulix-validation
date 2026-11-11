import unittest
from pathlib import Path


class AapIncusNightlyContractTests(unittest.TestCase):
    def test_cross_repository_checkouts_use_bounded_app_tokens(self):
        workflow = (
            Path(__file__).parents[1] / ".github/workflows/aap-incus-nightly.yml"
        ).read_text(encoding="utf-8")

        self.assertEqual(
            workflow.count("actions/create-github-app-token@"), 2
        )
        self.assertEqual(
            workflow.count("token: ${{ steps.source-app.outputs.token }}"), 8
        )
        self.assertEqual(workflow.count("permission-contents: read"), 2)
        self.assertEqual(
            workflow.count(
                "          repositories: |\n"
                "            ansible-collection-supplementary\n"
                "            ansible-collection-ubuntu\n"
                "            modulix-automation\n"
                "          permission-contents: read"
            ),
            1,
        )
        self.assertEqual(
            workflow.count(
                "          repositories: |\n"
                "            ansible-collection-foundational\n"
                "            ansible-collection-rhel\n"
                "            ansible-collection-supplementary\n"
                "            ansible-collection-ubuntu\n"
                "            modulix-automation\n"
                "          permission-contents: read"
            ),
            1,
        )
        self.assertNotIn("LIT_REPOSITORY_READ_TOKEN", workflow)
        self.assertIn("permissions:\n  contents: read", workflow)
        self.assertIn("cancel-in-progress: false", workflow)
        self.assertIn("timeout-minutes: 15", workflow)
        self.assertIn("timeout-minutes: 330", workflow)


if __name__ == "__main__":
    unittest.main()
