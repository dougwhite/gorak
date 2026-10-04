"""Publish a tested source snapshot and propose it in the four consumers."""

import base64
import json
import os
import re
import subprocess
import tomllib
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parent.parent
UPSTREAM = "dougwhite/gorak"
CONSUMERS = (
    "dougwhite/gorak-lsp-rs",
    "dougwhite/gorak-frame-designer",
    "dougwhite/gorak-vscode-ext",
    "dougwhite/openroad_demo",
)
PREFIX = "automation/gorak-"


class GitHub:
    def __init__(self, token: str):
        self.token = token

    def call(self, endpoint: str, method: str = "GET", data: dict | None = None):
        request = Request(
            "https://api.github.com/" + endpoint,
            data=json.dumps(data).encode("utf-8") if data is not None else None,
            headers={
                "Authorization": f"Bearer {self.token}",
                "Accept": "application/vnd.github+json",
                "Content-Type": "application/json",
                "X-GitHub-Api-Version": "2022-11-28",
                "User-Agent": "gorak-ecosystem",
            },
            method=method,
        )
        try:
            with urlopen(request, timeout=30) as response:
                return json.load(response)
        except HTTPError as error:
            if method == "GET" and error.code == 404:
                return None
            raise

    def pages(self, endpoint: str) -> list:
        result = []
        for page in range(1, 100):
            items = self.call(f"{endpoint}&per_page=100&page={page}")
            if not isinstance(items, list):
                raise ValueError("Expected a GitHub collection")
            result.extend(items)
            if len(items) < 100:
                return result
        raise ValueError("GitHub collection exceeds pagination limit")


def candidate_tag(version: str, run: str) -> str:
    match = re.fullmatch(r"(\d+\.\d+\.\d+)(?:(a|b|rc)(\d+))?", version)
    if not match or not run.isdecimal():
        raise ValueError("Expected a package release version and numeric CI run number")
    suffix = {"a": "alpha", "b": "beta", "rc": "rc"}.get(match[2])
    prerelease = f"{suffix}.{match[3]}." if suffix else ""
    return f"v{match[1]}-{prerelease}dev.{run}"


def update_manifest(original: str, tag: str, source_version: int) -> tuple[str, int]:
    pin = tomllib.loads(original)
    old = pin["source_version"]
    if (
        type(old) is not int
        or type(source_version) is not int
        or min(old, source_version) < 1
    ):
        raise ValueError("Source markers must be positive integers")
    if old > source_version:
        raise ValueError("Refusing to regress a consumer's source contract")
    text = original
    for key, value in [
        ("gorak_revision", json.dumps(tag)),
        ("source_version", str(source_version)),
    ]:
        text, count = re.subn(
            rf"(?m)^({key}[ \t]*=[ \t]*)([^#\r\n]*?)([ \t]*(?:#.*)?)$",
            lambda match, replacement=value: match[1] + replacement + match[3],
            text,
        )
        if count != 1:
            raise ValueError(f"Expected one top-level {key}")
    if tomllib.loads(text) != {
        **pin,
        "gorak_revision": tag,
        "source_version": source_version,
    }:
        raise ValueError("Pin update changed unrelated data")
    return text, old


def publish_candidate(api: GitHub, tag: str, sha: str) -> None:
    endpoint = f"repos/{UPSTREAM}"
    ref = api.call(f"{endpoint}/git/ref/tags/{quote(tag, safe='')}")
    if ref:
        if ref["object"]["type"] != "commit" or ref["object"]["sha"] != sha:
            raise ValueError("Candidate tag already identifies different code")
    else:
        api.call(
            f"{endpoint}/git/refs", "POST", {"ref": f"refs/tags/{tag}", "sha": sha}
        )
    release = api.call(f"{endpoint}/releases/tags/{quote(tag, safe='')}")
    if release:
        if release["draft"] or not release["prerelease"]:
            raise ValueError("Existing candidate must be a published prerelease")
        return
    api.call(
        f"{endpoint}/releases",
        "POST",
        {
            "tag_name": tag,
            "name": f"gorak development candidate {tag}",
            "prerelease": True,
            "make_latest": "false",
            "body": f"Tested source snapshot `{sha}` for downstream certification. "
            "This development tag identifies the merged source; it does not change the "
            "package version or publish wheels/executables. Final release waits for the "
            "complete extension and other consumers to be certified.",
        },
    )


def propose(api: GitHub, repo: str, tag: str, source_version: int) -> str:
    endpoint = f"repos/{repo}"
    repository = api.call(endpoint)
    default = repository["default_branch"]
    branch = PREFIX + tag
    proposals = [
        pr
        for pr in api.pages(f"{endpoint}/pulls?state=all")
        if pr["head"]["repo"]
        and pr["head"]["repo"]["full_name"] == repo
        and pr["head"]["ref"].startswith(PREFIX)
    ]
    for pr in proposals:
        if pr["state"] == "closed" and (
            pr["head"]["ref"] == branch
            or f"<!-- gorak-candidate: {tag} -->" in (pr.get("body") or "")
        ):
            return f"{repo}: candidate already handled in PR #{pr['number']}"
    opened = [
        pr for pr in proposals if pr["state"] == "open" and pr["base"]["ref"] == default
    ]
    if len(opened) > 1:
        raise ValueError(f"{repo}: more than one open gorak automation PR")
    existing = opened[0] if opened else None
    if existing:
        branch = existing["head"]["ref"]
    branch_ref = api.call(f"{endpoint}/git/ref/heads/{quote(branch, safe='')}")
    base_content = api.call(
        f"{endpoint}/contents/ecosystem.toml?ref={quote(default, safe='')}"
    )
    if not base_content or base_content.get("encoding") != "base64":
        raise ValueError(f"{repo}: missing ecosystem.toml on the default branch")
    content = (
        api.call(f"{endpoint}/contents/ecosystem.toml?ref={quote(branch, safe='')}")
        if branch_ref
        else base_content
    )
    if not content or content.get("encoding") != "base64":
        raise ValueError(f"{repo}: missing ecosystem.toml")
    original = base64.b64decode(content["content"]).decode("utf-8")
    updated, _ = update_manifest(original, tag, source_version)
    old = tomllib.loads(base64.b64decode(base_content["content"]).decode("utf-8"))[
        "source_version"
    ]
    if updated == original and existing:
        return f"{repo}: already proposed {tag}"
    if not branch_ref:
        ref = api.call(f"{endpoint}/git/ref/heads/{quote(default, safe='')}")
        api.call(
            f"{endpoint}/git/refs",
            "POST",
            {"ref": f"refs/heads/{branch}", "sha": ref["object"]["sha"]},
        )
    # Contents API appends a commit to the branch, retaining all human fixes.
    if updated != original:
        api.call(
            f"{endpoint}/contents/ecosystem.toml",
            "PUT",
            {
                "branch": branch,
                "sha": content["sha"],
                "message": f"Propose gorak {tag} compatibility",
                "content": base64.b64encode(updated.encode("utf-8")).decode("ascii"),
            },
        )
    body = (
        f"<!-- gorak-candidate: {tag} -->\n"
        f"Test [{tag}](https://github.com/{UPSTREAM}/releases/tag/{tag}) from the latest tested gorak merge.\n\n"
        f"Source contract: `{old}` to `{source_version}`. "
        + (
            "**Contract changed: adapt this consumer before merging.**"
            if old != source_version
            else "Contract marker unchanged."
        )
        + "\n\nThis proposes compatibility. This repo's existing CI tests the new tagged "
        "source/fixtures; passing CI and review certify it. Only the gorak/source "
        "pins are changed. Existing downstream fixes are retained. No automatic "
        "merge, dependent release, or final gorak release.\n"
    )
    data = {"title": f"Certify gorak {tag} compatibility", "body": body}
    if existing:
        pr = api.call(f"{endpoint}/pulls/{existing['number']}", "PATCH", data)
    else:
        pr = api.call(
            f"{endpoint}/pulls", "POST", {**data, "head": branch, "base": default}
        )
    return f"{repo}: {pr['html_url']}"


def main() -> None:
    event = json.loads(
        Path(os.environ["GITHUB_EVENT_PATH"]).read_text(encoding="utf-8")
    )
    sha = os.environ["GITHUB_SHA"]
    if (
        event.get("ref") != "refs/heads/master"
        or os.environ.get("GITHUB_REPOSITORY") != UPSTREAM
    ):
        raise ValueError("Candidates may only be published from gorak master pushes")
    before = event["before"]
    paths = subprocess.check_output(
        ["git", "diff", "--name-only", before, sha], encoding="utf-8"
    ).splitlines()
    if not any(
        path.startswith(("src/", "tests/", "compatibility/", "scripts/"))
        or path in {"ecosystem.toml", "pyproject.toml", "uv.lock"}
        for path in paths
    ):
        print("No code or contract change; no candidate needed")
        return
    if not os.environ.get("ECOSYSTEM_PR_TOKEN"):
        raise ValueError(
            "Configure ECOSYSTEM_PR_TOKEN before enabling candidate propagation"
        )
    root_api = GitHub(os.environ["GITHUB_TOKEN"])
    latest = root_api.call(f"repos/{UPSTREAM}/git/ref/heads/master")
    if latest["object"]["sha"] != sha:
        print("A newer gorak merge supersedes this run; leaving downstream pins alone")
        return
    package = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    pin = tomllib.loads((ROOT / "ecosystem.toml").read_text(encoding="utf-8"))
    if type(pin.get("source_version")) is not int or pin["source_version"] < 1:
        raise ValueError("gorak source_version must be a positive integer")
    tag = candidate_tag(package["project"]["version"], os.environ["GITHUB_RUN_NUMBER"])
    publish_candidate(root_api, tag, sha)
    downstream_api = GitHub(os.environ["ECOSYSTEM_PR_TOKEN"])
    failures = []
    for repo in CONSUMERS:
        try:
            print(propose(downstream_api, repo, tag, pin["source_version"]))
        except (URLError, ValueError, KeyError, TimeoutError) as error:
            print(f"{repo}: propagation failed ({type(error).__name__})")
            failures.append(repo)
    if failures:
        raise ValueError(
            "Retry the CI run after resolving propagation failures: "
            + ", ".join(failures)
        )


if __name__ == "__main__":
    main()
