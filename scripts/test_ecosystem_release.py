import base64
import io
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import ecosystem_release as release

TAG = "v0.1.0-alpha.1.dev.42"
REPO = "dougwhite/gorak-vscode-ext"
BASE = 'source_version = 1 # contract\ngorak_revision = "v0.1.0-alpha.1"\nlsp_revision = "v0.9.0-alpha.5"\n'


def encoded(text):
    return {
        "encoding": "base64",
        "sha": "blob",
        "content": base64.b64encode(text.encode()).decode(),
    }


def proposal(state="open", branch=release.PREFIX + "older", body=""):
    return {
        "number": 1,
        "state": state,
        "body": body,
        "head": {"repo": {"full_name": REPO}, "ref": branch},
        "base": {"ref": "main"},
    }


class FakeConsumer:
    def __init__(self, prs=None, branch_text=None):
        self.prs = prs or []
        self.branch_text = branch_text
        self.writes = []

    def pages(self, endpoint):
        return self.prs

    def call(self, endpoint, method="GET", data=None):
        if method != "GET":
            self.writes.append((endpoint, method, data))
            if method == "PUT":
                self.branch_text = base64.b64decode(data["content"]).decode()
            return {"html_url": "https://github.com/dougwhite/gorak-vscode-ext/pull/9"}
        if endpoint == f"repos/{REPO}":
            return {"default_branch": "main"}
        if "/git/ref/heads/main" in endpoint:
            return {"object": {"sha": "base"}}
        if "/git/ref/heads/" in endpoint:
            return (
                {"object": {"sha": "human-fixes"}}
                if self.branch_text is not None
                else None
            )
        if "/contents/" in endpoint:
            return encoded(BASE if endpoint.endswith("ref=main") else self.branch_text)
        raise AssertionError(endpoint)


class Candidate(unittest.TestCase):
    def test_package_versions_and_development_tags(self):
        self.assertEqual(release.candidate_tag("0.1.0a1", "42"), TAG)
        self.assertEqual(release.candidate_tag("0.2.0rc3", "42"), "v0.2.0-rc.3.dev.42")
        self.assertEqual(release.candidate_tag("0.2.0", "42"), "v0.2.0-dev.42")
        for version, run in [("main", "42"), ("0.2.0", "../bad")]:
            with self.assertRaises(ValueError):
                release.candidate_tag(version, run)

    def test_preserve_comments_and_other_dependency_pins(self):
        text, old = release.update_manifest(BASE, TAG, 2)
        self.assertEqual(old, 1)
        self.assertIn("source_version = 2 # contract", text)
        self.assertIn('lsp_revision = "v0.9.0-alpha.5"', text)

    def test_reject_bad_contracts(self):
        for marker in [True, 0, "2"]:
            with self.assertRaises(ValueError):
                release.update_manifest(BASE, TAG, marker)
        with self.assertRaises(ValueError):
            release.update_manifest(BASE.replace("= 1 #", "= 2 #"), TAG, 1)

    def test_immutable_candidate_and_retry(self):
        api = release.GitHub("test-only")
        with patch.object(
            api,
            "call",
            side_effect=[
                {"object": {"type": "commit", "sha": "tested"}},
                {"draft": False, "prerelease": True},
            ],
        ) as call:
            release.publish_candidate(api, TAG, "tested")
            self.assertEqual(call.call_count, 2)
        with patch.object(
            api, "call", return_value={"object": {"type": "commit", "sha": "wrong"}}
        ):
            with self.assertRaises(ValueError):
                release.publish_candidate(api, TAG, "tested")

    def test_publish_only_prerelease(self):
        api = release.GitHub("test-only")
        with patch.object(api, "call", side_effect=[None, {}, None, {}]) as call:
            release.publish_candidate(api, TAG, "tested")
            payload = call.call_args_list[-1].args[2]
            self.assertTrue(payload["prerelease"])
            self.assertEqual(payload["make_latest"], "false")


class Consumer(unittest.TestCase):
    def test_new_candidate_opens_pr(self):
        api = FakeConsumer()
        release.propose(api, REPO, TAG, 2)
        self.assertEqual(
            [method for _, method, _ in api.writes], ["POST", "PUT", "POST"]
        )
        self.assertIn("Contract changed", api.writes[-1][2]["body"])

    def test_advance_keeps_human_branch_and_fixes(self):
        api = FakeConsumer([proposal()], BASE)
        release.propose(api, REPO, TAG, 2)
        self.assertEqual([method for _, method, _ in api.writes], ["PUT", "PATCH"])
        self.assertEqual(api.writes[0][2]["branch"], release.PREFIX + "older")
        self.assertEqual(api.writes[0][2]["sha"], "blob")

    def test_contract_warning_compares_with_default_branch(self):
        text, _ = release.update_manifest(BASE, "previous-candidate", 2)
        api = FakeConsumer([proposal()], text)
        release.propose(api, REPO, TAG, 2)
        self.assertIn("Contract changed", api.writes[-1][2]["body"])

    def test_retry_after_branch_commit_but_before_pr(self):
        text, _ = release.update_manifest(BASE, TAG, 2)
        api = FakeConsumer(branch_text=text)
        release.propose(api, REPO, TAG, 2)
        self.assertEqual([method for _, method, _ in api.writes], ["POST"])
        self.assertTrue(api.writes[0][0].endswith("/pulls"))

    def test_retry_after_branch_creation(self):
        api = FakeConsumer(branch_text=BASE)
        release.propose(api, REPO, TAG, 2)
        self.assertEqual([method for _, method, _ in api.writes], ["PUT", "POST"])

    def test_same_candidate_is_noop(self):
        text, _ = release.update_manifest(BASE, TAG, 2)
        api = FakeConsumer([proposal()], text)
        release.propose(api, REPO, TAG, 2)
        self.assertFalse(api.writes)

    def test_declined_candidate_is_not_reopened(self):
        for pr in [
            proposal("closed", release.PREFIX + TAG),
            proposal("closed", body=f"<!-- gorak-candidate: {TAG} -->"),
        ]:
            api = FakeConsumer([pr])
            release.propose(api, REPO, TAG, 2)
            self.assertFalse(api.writes)

    def test_forks_do_not_capture_update(self):
        pr = proposal()
        pr["head"]["repo"]["full_name"] = "someone/fork"
        api = FakeConsumer([pr])
        release.propose(api, REPO, TAG, 1)
        self.assertEqual(
            [method for _, method, _ in api.writes], ["POST", "PUT", "POST"]
        )

    def test_multiple_open_proposals_require_resolution(self):
        api = FakeConsumer([proposal(), proposal()])
        with self.assertRaises(ValueError):
            release.propose(api, REPO, TAG, 1)
        self.assertFalse(api.writes)

    def test_windows_console_output(self):
        with io.TextIOWrapper(io.BytesIO(), encoding="cp1252") as console:
            with patch("sys.stdout", console):
                print(release.propose(FakeConsumer(), REPO, TAG, 2))
            console.flush()


class MergeGate(unittest.TestCase):
    def run_merge(
        self,
        paths="src/gorak/parser.py\n",
        latest="tested",
        token="test-only",
        error=None,
    ):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            event = root / "event.json"
            event.write_text(
                json.dumps({"ref": "refs/heads/master", "before": "before"})
            )
            (root / "pyproject.toml").write_text('[project]\nversion = "0.1.0a1"\n')
            (root / "ecosystem.toml").write_text("source_version = 1\n")
            environment = {
                "GITHUB_EVENT_PATH": str(event),
                "GITHUB_SHA": "tested",
                "GITHUB_REPOSITORY": release.UPSTREAM,
                "GITHUB_RUN_NUMBER": "42",
                "GITHUB_TOKEN": "test-only",
                "ECOSYSTEM_PR_TOKEN": token,
            }
            api = release.GitHub("test-only")
            with (
                patch.dict(os.environ, environment),
                patch.object(release, "ROOT", root),
                patch.object(release.subprocess, "check_output", return_value=paths),
                patch.object(release, "GitHub", return_value=api),
                patch.object(api, "call", return_value={"object": {"sha": latest}}),
                patch.object(release, "publish_candidate") as publish,
                patch.object(
                    release, "propose", side_effect=error or ["proposed"] * 4
                ) as propose,
            ):
                failure = None
                try:
                    release.main()
                except ValueError as caught:
                    failure = caught
                return publish.call_count, propose.call_count, failure

    def test_docs_only_does_not_need_token_or_publish(self):
        self.assertEqual(
            self.run_merge(paths="README.md\nbranding/icon.svg\n", token=""),
            (0, 0, None),
        )

    def test_superseded_merge_does_not_publish(self):
        self.assertEqual(self.run_merge(latest="newer"), (0, 0, None))

    def test_missing_token_blocks_before_publication(self):
        publish, propose, error = self.run_merge(token="")
        self.assertEqual((publish, propose), (0, 0))
        self.assertIsInstance(error, ValueError)

    def test_code_merge_publishes_and_updates_all_four(self):
        self.assertEqual(self.run_merge(), (1, 4, None))

    def test_partial_failure_still_attempts_other_consumers(self):
        publish, propose, error = self.run_merge(
            error=[ValueError("test failure"), "ok", "ok", "ok"]
        )
        self.assertEqual((publish, propose), (1, 4))
        self.assertIsInstance(error, ValueError)


if __name__ == "__main__":
    unittest.main()
