import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW_PATH = ROOT / ".github" / "workflows" / "copilot-review.yml"


class CopilotReviewThreadContractTests(unittest.TestCase):
    def test_unresolved_findings_remain_blocking_across_head_changes(self):
        workflow = WORKFLOW_PATH.read_text(encoding="utf-8")

        self.assertNotIn(".pullRequestReview.commit.oid == $head_sha", workflow)
        self.assertNotIn(".pullRequestReview.commit.oid == $head", workflow)
        self.assertGreaterEqual(
            workflow.count(".isResolved == false"),
            2,
        )
        self.assertGreaterEqual(
            workflow.count('($reviewer + "[bot]")'),
            1,
        )
        self.assertGreaterEqual(
            workflow.count('copilot-pull-request-reviewer[bot]'),
            1,
        )


if __name__ == "__main__":
    unittest.main()
