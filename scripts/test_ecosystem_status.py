import unittest
from unittest.mock import Mock

import ecosystem_status as status


class Status(unittest.TestCase):
    def test_exact_heads_and_latest_workflow_result(self):
        api = Mock()
        api.pages.return_value = [
            {
                "body": "<!-- gorak-candidate: candidate -->",
                "head": {"repo": {"full_name": repo}, "sha": "reviewed-head"},
                "html_url": "https://github.com/pr",
                "state": "open",
            }
            for repo in status.CONSUMERS
        ]
        api.call.return_value = {
            "workflow_runs": [
                {
                    "id": 20,
                    "workflow_id": 1,
                    "status": "completed",
                    "conclusion": "success",
                    "html_url": "https://github.com/new",
                },
                {
                    "id": 10,
                    "workflow_id": 1,
                    "status": "completed",
                    "conclusion": "failure",
                    "html_url": "https://github.com/old",
                },
            ]
        }
        block, pending = status.collect(api, "candidate")
        self.assertFalse(pending)
        self.assertEqual(block.count("Passed"), 4)
        self.assertNotIn("https://github.com/old", block)
        self.assertTrue(
            all(
                "head_sha=reviewed-head" in call.args[0]
                for call in api.call.call_args_list
            )
        )

    def test_absent_or_failed_checks_never_pass(self):
        api = Mock()
        api.pages.return_value = [
            {
                "body": "<!-- gorak-candidate: candidate -->",
                "head": {"repo": {"full_name": repo}, "sha": "head"},
                "html_url": "url",
                "state": "open",
            }
            for repo in status.CONSUMERS
        ]
        api.call.return_value = {"workflow_runs": []}
        block, pending = status.collect(api, "candidate")
        self.assertTrue(pending)
        self.assertNotIn("Passed", block)
        api.call.return_value = {
            "workflow_runs": [
                {
                    "id": 1,
                    "workflow_id": 1,
                    "status": "completed",
                    "conclusion": "failure",
                    "html_url": "url",
                }
            ]
        }
        block, pending = status.collect(api, "candidate")
        self.assertFalse(pending)
        self.assertEqual(block.count("Needs attention"), 4)

    def test_missing_or_fork_proposal_never_passes(self):
        api = Mock()
        api.pages.return_value = []
        block, pending = status.collect(api, "candidate")
        self.assertTrue(pending)
        self.assertEqual(block.count("Missing or ambiguous"), 4)
        api.call.assert_not_called()

    def test_update_preserves_review_and_owner_notes(self):
        api = Mock()
        body = (
            "<!-- gorak-ecosystem-candidate: candidate -->\nOwner note\n"
            + status.START
            + "\nOld\n"
            + status.END
            + "\nReviewed head abc"
        )
        api.pages.return_value = [{"number": 7, "html_url": "url", "body": body}]
        new = status.START + "\nNew\n" + status.END
        status.update_issue(api, "candidate", new)
        updated = api.call.call_args.args[2]["body"]
        self.assertIn("Owner note", updated)
        self.assertIn("Reviewed head abc", updated)
        self.assertIn("New", updated)
        self.assertNotIn("Old", updated)
        api.reset_mock()
        api.pages.return_value = [{"number": 7, "html_url": "url", "body": updated}]
        status.update_issue(api, "candidate", new)
        api.call.assert_not_called()

    def test_damaged_markers_stop_without_overwriting(self):
        api = Mock()
        api.pages.return_value = [
            {
                "number": 7,
                "body": "<!-- gorak-ecosystem-candidate: candidate --> human notes",
            }
        ]
        with self.assertRaises(ValueError):
            status.update_issue(api, "candidate", "new")
        api.call.assert_not_called()

    def test_retry_reuses_closed_tracking_issue(self):
        api = Mock()
        block = status.START + "\nStatus\n" + status.END
        api.pages.return_value = [
            {
                "number": 7,
                "state": "closed",
                "html_url": "url",
                "body": "<!-- gorak-ecosystem-candidate: candidate -->\n" + block,
            }
        ]
        self.assertEqual(status.update_issue(api, "candidate", block), "url")
        api.call.assert_not_called()
