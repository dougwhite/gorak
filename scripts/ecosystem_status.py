"""Maintain one candidate issue from exact downstream PR heads and CI runs."""

import argparse
import os
import time
from urllib.parse import quote

from ecosystem_release import CONSUMERS, UPSTREAM, GitHub

START = "<!-- gorak-status:start -->"
END = "<!-- gorak-status:end -->"


def collect(api: GitHub, tag: str) -> tuple[str, bool]:
    rows = []
    pending = False
    marker = f"<!-- gorak-candidate: {tag} -->"
    for repo in CONSUMERS:
        prs = api.pages(f"repos/{repo}/pulls?state=all")
        matches = [
            pr
            for pr in prs
            if marker in (pr.get("body") or "")
            and pr["head"]["repo"]
            and pr["head"]["repo"]["full_name"] == repo
        ]
        if len(matches) != 1:
            rows.append(
                f"| {repo.split('/')[1]} | Missing or ambiguous proposal | — | Needs attention |"
            )
            pending = True
            continue
        pr = matches[0]
        head = pr["head"]["sha"]
        runs = api.call(
            f"repos/{repo}/actions/runs?head_sha={head}&event=pull_request&per_page=100"
        )
        # Keep the latest attempt per workflow, ignoring unrelated publication workflows.
        latest = {}
        for run in sorted(
            runs["workflow_runs"], key=lambda item: item["id"], reverse=True
        ):
            latest.setdefault(run["workflow_id"], run)
        if not latest or any(run["status"] != "completed" for run in latest.values()):
            ci = "Pending"
            pending = True
        elif any(run["conclusion"] != "success" for run in latest.values()):
            ci = "Needs attention"
        else:
            ci = "Passed"
        state = (
            "Merged"
            if pr.get("merged_at")
            else ("Closed" if pr["state"] == "closed" else "Open")
        )
        links = ", ".join(f"[CI]({run['html_url']})" for run in latest.values())
        rows.append(
            f"| [{repo.split('/')[1]}]({pr['html_url']}) | {state} | `{head}` | {ci} {links} |"
        )
    block = (
        f"{START}\n"
        "| Consumer / PR | PR state | Checked head | CI |\n"
        "| --- | --- | --- | --- |\n" + "\n".join(rows) + "\n\n"
        "CI success is evidence for review, not release approval. Review findings below "
        "apply only to the recorded head; any new commit needs another review.\n"
        f"{END}"
    )
    return block, pending


def update_issue(api: GitHub, tag: str, block: str) -> str:
    marker = f"<!-- gorak-ecosystem-candidate: {tag} -->"
    issues = [
        issue
        for issue in api.pages(f"repos/{UPSTREAM}/issues?state=all")
        if "pull_request" not in issue and marker in (issue.get("body") or "")
    ]
    if len(issues) > 1:
        raise ValueError("Multiple candidate tracking issues; resolve before updating")
    if issues:
        issue = issues[0]
        body = issue.get("body") or ""
        if (
            body.count(START) != 1
            or body.count(END) != 1
            or body.index(START) > body.index(END)
        ):
            raise ValueError(
                "Invalid status markers; refusing to overwrite review notes"
            )
        updated = body[: body.index(START)] + block + body[body.index(END) + len(END) :]
        if updated != body:
            api.call(
                f"repos/{UPSTREAM}/issues/{issue['number']}", "PATCH", {"body": updated}
            )
        return issue["html_url"]
    issue = api.call(
        f"repos/{UPSTREAM}/issues",
        "POST",
        {
            "title": f"Coordinate gorak {tag}",
            "body": f"{marker}\nCandidate: [{tag}](https://github.com/{UPSTREAM}/releases/tag/{tag})\n\n"
            + block
            + "\n\n## Coordinator review\n\nAwaiting consumer review. "
            "Ask Codex: `Bring the ecosystem up to this candidate using scripts/COORDINATE.md`.\n\n"
            "Merges and releases require owner instructions. No release is implied by this issue.\n",
        },
    )
    return issue["html_url"]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("tag")
    parser.add_argument("--wait-seconds", type=int, default=0)
    args = parser.parse_args()
    if not 0 <= args.wait_seconds <= 1200:
        parser.error("wait-seconds must be between 0 and 1200")
    api = GitHub(os.environ["GITHUB_TOKEN"])
    release = api.call(f"repos/{UPSTREAM}/releases/tags/{quote(args.tag, safe='')}")
    if not release or release["draft"] or not release["prerelease"]:
        raise ValueError("Expected a published gorak candidate prerelease")
    deadline = time.monotonic() + args.wait_seconds
    while True:
        block, pending = collect(api, args.tag)
        print(update_issue(api, args.tag, block))
        if not pending or time.monotonic() >= deadline:
            if pending:
                print(
                    "Some checks remain pending; rerun status refresh or ask the coordinator"
                )
            return
        time.sleep(min(30, max(0, deadline - time.monotonic())))


if __name__ == "__main__":
    main()
