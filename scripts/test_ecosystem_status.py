import unittest
from unittest.mock import Mock, patch

import ecosystem_status as status

TAG = "v0.1.0-alpha.1.dev.42"
NEW = "v0.1.0-alpha.1.dev.43"


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
            "<!-- gorak-ecosystem-candidate: v0.1.0-alpha.1.dev.42 -->\nOwner note\n"
            + status.START
            + "\nOld\n"
            + status.END
            + "\nReviewed head abc"
        )
        api.pages.return_value = [
            {
                "number": 7,
                "state": "open",
                "title": "Coordinate latest gorak candidate",
                "html_url": "url",
                "body": body,
            }
        ]
        new = status.START + "\nNew\n" + status.END
        status.update_issue(api, TAG, new)
        updated = api.call.call_args.args[2]["body"]
        self.assertIn("Owner note", updated)
        self.assertIn("Reviewed head abc", updated)
        self.assertIn("New", updated)
        self.assertNotIn("Old", updated)
        self.assertIn(status.TRACKER, updated)
        api.reset_mock()
        api.pages.return_value = [
            {
                "number": 7,
                "state": "open",
                "title": "Coordinate latest gorak candidate",
                "html_url": "url",
                "body": updated,
            }
        ]
        status.update_issue(api, TAG, new)
        api.call.assert_not_called()

    def test_damaged_markers_stop_without_overwriting(self):
        api = Mock()
        api.pages.return_value = [
            {
                "number": 7,
                "state": "open",
                "title": "Coordinate latest gorak candidate",
                "body": "<!-- gorak-ecosystem-candidate: v0.1.0-alpha.1.dev.42 --> human notes",
            }
        ]
        with self.assertRaises(ValueError):
            status.update_issue(api, TAG, "new")
        api.call.assert_not_called()

    def test_retry_reuses_closed_tracking_issue(self):
        api = Mock()
        block = status.START + "\nStatus\n" + status.END
        api.pages.return_value = [
            {
                "number": 7,
                "title": "Coordinate latest gorak candidate",
                "state": "closed",
                "html_url": "url",
                "body": "<!-- gorak-ecosystem-candidate: v0.1.0-alpha.1.dev.42 -->\n"
                + block,
            }
        ]
        self.assertEqual(status.update_issue(api, TAG, block), "url")
        api.call.assert_not_called()

    def issue(self, tag=TAG, state="open"):
        return {
            "number": 7,
            "state": state,
            "title": "Coordinate latest gorak candidate",
            "html_url": "existing",
            "body": status.TRACKER
            + "\n<!-- gorak-ecosystem-candidate: "
            + tag
            + " -->\n"
            + status.START
            + "\nOld\n"
            + status.END
            + "\nOwner note: reviewed old head",
        }

    def test_new_candidate_advances_same_issue_and_preserves_old_review(self):
        api = Mock()
        api.pages.return_value = [self.issue()]
        block = status.START + "\nNew\n" + status.END
        self.assertEqual(status.update_issue(api, NEW, block), "existing")
        call = api.call.call_args
        self.assertEqual(call.args[:2], ("repos/dougwhite/gorak/issues/7", "PATCH"))
        self.assertIn(NEW, call.args[2]["body"])
        self.assertIn("Owner note: reviewed old head", call.args[2]["body"])

    def test_old_run_cannot_move_active_issue_backwards(self):
        api = Mock()
        api.pages.return_value = [self.issue(NEW)]
        self.assertEqual(status.update_issue(api, TAG, "old"), "existing")
        api.call.assert_not_called()

    def test_next_round_after_closure_creates_new_issue(self):
        api = Mock()
        api.pages.return_value = [self.issue(state="closed")]
        api.call.return_value = {"html_url": "new-round"}
        self.assertEqual(status.update_issue(api, NEW, "block"), "new-round")
        self.assertEqual(api.call.call_args.args[1], "POST")

    def test_duplicate_active_issues_stop_without_writes(self):
        api = Mock()
        api.pages.return_value = [self.issue(), self.issue(NEW)]
        with self.assertRaises(ValueError):
            status.update_issue(api, NEW, "block")
        api.call.assert_not_called()

    def test_latest_uses_numeric_run_order_and_ignores_final_releases(self):
        api = Mock()
        api.pages.return_value = [
            {"tag_name": "v0.1.0-alpha.1.dev.9", "draft": False, "prerelease": True},
            {"tag_name": TAG, "draft": False, "prerelease": True},
            {"tag_name": NEW, "draft": True, "prerelease": True},
            {"tag_name": "v99.0.0", "draft": False, "prerelease": False},
        ]
        self.assertTrue(status.is_latest(api, TAG))
        self.assertFalse(status.is_latest(api, "v0.1.0-alpha.1.dev.9"))

    def test_superseded_run_stops_before_collection_or_writes(self):
        api = Mock()
        api.call.return_value = {"draft": False, "prerelease": True}
        with (
            patch("sys.argv", ["status", TAG]),
            patch.dict("os.environ", {"GITHUB_TOKEN": "test-only"}),
            patch.object(status, "GitHub", return_value=api),
            patch.object(status, "is_latest", return_value=False),
            patch.object(status, "collect") as collect,
            patch.object(status, "update_issue") as update,
        ):
            status.main()
            collect.assert_not_called()
            update.assert_not_called()

    def test_candidate_arriving_during_collection_prevents_stale_write(self):
        api = Mock()
        api.call.return_value = {"draft": False, "prerelease": True}
        with (
            patch("sys.argv", ["status", TAG]),
            patch.dict("os.environ", {"GITHUB_TOKEN": "test-only"}),
            patch.object(status, "GitHub", return_value=api),
            patch.object(status, "is_latest", side_effect=[True, False]),
            patch.object(status, "collect", return_value=("old", True)),
            patch.object(status, "update_issue") as update,
        ):
            status.main()
            update.assert_not_called()
