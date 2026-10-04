import base64
import hashlib
import io
import json
import tarfile
import unittest
from unittest.mock import Mock, patch

import ecosystem_dependencies as deps

LSP = "dougwhite/gorak-lsp-rs"
DESIGNER = "dougwhite/gorak-frame-designer"
OLD = "v0.1.0-alpha.1"
NEW = "v0.1.0-alpha.2"


def files():
    return {
        "ecosystem.toml": f'source_version = 1 # keep\ngorak_revision = "v0.1.0-alpha.1.dev.21"\nlsp_revision = "{OLD}"\nframe_designer_revision = "{OLD}"\n',
        "server.json": json.dumps({"repository": LSP, "tag": OLD, "sha256": "old"}),
        "package.json": json.dumps(
            {
                "name": "host",
                "version": "1.0.0",
                "dependencies": {
                    "gorak-frame-designer": "old-url",
                    "other": "unchanged",
                },
            }
        ),
        "package-lock.json": json.dumps(
            {
                "packages": {
                    "": {"dependencies": {"gorak-frame-designer": "old-url"}},
                    "node_modules/gorak-frame-designer": {
                        "integrity": "old",
                        "version": OLD[1:],
                    },
                }
            }
        ),
    }


def fetcher(name, data, checksum=None):
    sums = (
        (checksum or hashlib.sha256(data).hexdigest()) + "  " + name + "\n"
    ).encode()
    return lambda _release, _repo, asset: sums if asset == "SHA256SUMS" else data


def archive(version=NEW[1:]):
    buffer = io.BytesIO()
    data = json.dumps({"name": "gorak-frame-designer", "version": version}).encode()
    with tarfile.open(fileobj=buffer, mode="w:gz") as tar:
        info = tarfile.TarInfo("package/package.json")
        info.size = len(data)
        tar.addfile(info, io.BytesIO(data))
    return buffer.getvalue()


class Assets(unittest.TestCase):
    def test_lsp_updates_only_its_pin_and_manifest_digest(self):
        original = files()
        data = json.dumps(
            {
                "version": NEW[1:],
                "platforms": {
                    "win32-x64": {"sha256": "a" * 64},
                    "linux-x64": {"sha256": "b" * 64},
                },
                "noticesSha256": "c" * 64,
            }
        ).encode()
        result = deps.update_files(
            original, LSP, {"tag_name": NEW}, fetcher("release.json", data)
        )
        self.assertEqual(result["package.json"], original["package.json"])
        self.assertEqual(result["package-lock.json"], original["package-lock.json"])
        self.assertIn("source_version = 1 # keep", result["ecosystem.toml"])
        self.assertIn(f'frame_designer_revision = "{OLD}"', result["ecosystem.toml"])
        self.assertEqual(
            json.loads(result["server.json"])["sha256"],
            hashlib.sha256(data).hexdigest(),
        )

    def test_bad_checksum_and_incomplete_lsp_stop(self):
        data = json.dumps({"version": NEW[1:], "platforms": {}}).encode()
        for fetch in [
            fetcher("release.json", data, "0" * 64),
            fetcher("release.json", data),
        ]:
            with self.assertRaises(ValueError):
                deps.update_files(files(), LSP, {"tag_name": NEW}, fetch)

    def test_designer_regenerates_lock_without_scripts_and_checks_integrity(self):
        original = files()
        data = archive()
        expected = "sha512-" + base64.b64encode(hashlib.sha512(data).digest()).decode()

        def run(args, cwd, **kwargs):
            self.assertIn("--ignore-scripts", args)
            self.assertIn("--package-lock-only", args)
            pkg = json.loads((cwd / "package.json").read_text())
            url = pkg["dependencies"]["gorak-frame-designer"]
            self.assertEqual(pkg["dependencies"]["other"], "unchanged")
            (cwd / "package-lock.json").write_text(
                json.dumps(
                    {
                        "packages": {
                            "": {"dependencies": {"gorak-frame-designer": url}},
                            "node_modules/gorak-frame-designer": {
                                "integrity": expected,
                                "resolved": url,
                                "version": NEW[1:],
                            },
                        }
                    }
                )
            )

        result = deps.update_files(
            original,
            DESIGNER,
            {"tag_name": NEW},
            fetcher(f"gorak-frame-designer-{NEW[1:]}.tgz", data),
            run,
        )
        self.assertEqual(result["server.json"], original["server.json"])
        self.assertIn(f'lsp_revision = "{OLD}"', result["ecosystem.toml"])
        self.assertEqual(
            json.loads(result["package-lock.json"])["packages"][
                "node_modules/gorak-frame-designer"
            ]["integrity"],
            expected,
        )

    def test_wrong_archive_version_stops_before_npm(self):
        data = archive(OLD[1:])
        run = Mock()
        with self.assertRaises(ValueError):
            deps.update_files(
                files(),
                DESIGNER,
                {"tag_name": NEW},
                fetcher(f"gorak-frame-designer-{NEW[1:]}.tgz", data),
                run,
            )
        run.assert_not_called()

    def test_old_release_does_not_regress_or_download(self):
        fetch = Mock()
        original = files()
        self.assertEqual(
            deps.update_files(original, LSP, {"tag_name": "v0.0.9"}, fetch), original
        )
        fetch.assert_not_called()

    def test_mutated_lsp_pin_is_rejected(self):
        data = json.dumps(
            {
                "version": OLD[1:],
                "platforms": {
                    "win32-x64": {"sha256": "a" * 64},
                    "linux-x64": {"sha256": "b" * 64},
                },
                "noticesSha256": "c" * 64,
            }
        ).encode()
        with self.assertRaisesRegex(ValueError, "mutated"):
            deps.update_files(
                files(), LSP, {"tag_name": OLD}, fetcher("release.json", data)
            )

    def test_numeric_prereleases_and_final_release_order(self):
        self.assertGreater(
            deps.version("v0.1.0-alpha.10"), deps.version("v0.1.0-alpha.9")
        )
        self.assertGreater(deps.version("v0.1.0"), deps.version("v0.1.0-rc.99"))
        with self.assertRaises(ValueError):
            deps.version("../main")


class Proposal(unittest.TestCase):
    def setUp(self):
        self.api = Mock()
        self.root = Mock()
        self.release = {"tag_name": NEW, "id": 12}
        self.original = files()
        self.updated = {**self.original, "server.json": "updated"}
        self.pr = {
            "number": 4,
            "state": "open",
            "body": "<!-- gorak-candidate: v0.1.0-alpha.1.dev.21 -->\nHuman note",
            "head": {"repo": {"full_name": deps.EXTENSION}, "ref": deps.PREFIX + "old"},
            "base": {"ref": "main"},
        }
        self.api.pages.return_value = [self.pr]
        self.root.pages.return_value = [
            {"tag_name": "v0.1.0-alpha.1.dev.21", "draft": False, "prerelease": True}
        ]

        def call(endpoint, method="GET", data=None):
            if endpoint == f"repos/{deps.EXTENSION}":
                return {"default_branch": "main"}
            if "/git/ref/heads/" in endpoint:
                return {"object": {"sha": "human-head"}}
            if "/git/commits/" in endpoint:
                return {"tree": {"sha": "base-tree"}}
            return {"sha": "new", "html_url": "pr-url"}

        self.api.call.side_effect = call

    def invoke(self):
        def content(_api, repo, path, ref):
            return (
                "source_version = 1\n" if repo == deps.UPSTREAM else self.original[path]
            )

        with (
            patch.object(deps, "latest_release", return_value=self.release),
            patch.object(deps, "contents", side_effect=content),
            patch.object(deps, "update_files", return_value=self.updated),
        ):
            return deps.propose(self.api, self.root, LSP, NEW)

    def test_existing_pr_keeps_human_notes_branch_and_uses_atomic_commit(self):
        self.assertTrue(self.invoke())
        writes = [call for call in self.api.call.call_args_list if len(call.args) > 1]
        tree = next(call for call in writes if call.args[0].endswith("/git/trees"))
        self.assertEqual(tree.args[2]["base_tree"], "base-tree")
        commit = next(call for call in writes if call.args[0].endswith("/git/commits"))
        self.assertEqual(commit.args[2]["parents"], ["human-head"])
        ref = next(call for call in writes if "/git/refs/heads/" in call.args[0])
        self.assertFalse(ref.args[2]["force"])
        self.assertIn(deps.PREFIX + "old", ref.args[0].replace("%2F", "/"))
        pr = writes[-1]
        self.assertIn("Human note", pr.args[2]["body"])
        self.assertIn("/pulls/4", pr.args[0])

    def test_retry_after_commit_before_pr_opens_existing_branch(self):
        self.api.pages.return_value = []
        self.updated = self.original
        self.assertTrue(self.invoke())
        writes = [call for call in self.api.call.call_args_list if len(call.args) > 1]
        self.assertEqual(len(writes), 1)
        self.assertTrue(writes[0].args[0].endswith("/pulls"))

    def test_older_notification_and_unknown_source_never_write(self):
        with patch.object(deps, "latest_release", return_value={"tag_name": "v0.2.0"}):
            self.assertFalse(deps.propose(self.api, self.root, LSP, NEW))
        with self.assertRaises(ValueError):
            deps.propose(self.api, self.root, "evil/repo", NEW)
        self.api.call.assert_not_called()

    def test_duplicate_open_prs_and_invalid_markers_stop_before_writes(self):
        for prs in [[self.pr, self.pr], [{**self.pr, "body": deps.START}]]:
            self.api.reset_mock()
            self.api.pages.return_value = prs
            with self.assertRaises(ValueError):
                self.invoke()
            self.assertFalse(
                any(len(call.args) > 1 for call in self.api.call.call_args_list)
            )

    def test_closed_release_proposal_is_not_recreated_on_another_branch(self):
        self.api.pages.return_value = [
            {
                **self.pr,
                "state": "closed",
                "body": f"<!-- gorak-dependency: {LSP}@{NEW} -->",
            }
        ]
        self.assertFalse(self.invoke())
        self.assertFalse(
            any(len(call.args) > 1 for call in self.api.call.call_args_list)
        )

    def test_every_wakeup_reconciles_both_dependencies_even_if_one_changed(self):
        with (
            patch.object(deps, "latest_release", return_value={"tag_name": NEW}),
            patch.object(deps, "propose", side_effect=[True, False]) as propose,
        ):
            self.assertTrue(deps.reconcile(self.api, self.root))
            self.assertEqual(
                [call.args[2] for call in propose.call_args_list], [LSP, DESIGNER]
            )
