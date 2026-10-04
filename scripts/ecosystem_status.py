"""Maintain one active ecosystem issue from exact downstream PR heads and CI runs."""

import argparse
import os
import re
import time
from urllib.parse import quote

from ecosystem_release import CONSUMERS, UPSTREAM, GitHub

START = "<!-- gorak-status:start -->"
END = "<!-- gorak-status:end -->"
TRACKER = "<!-- gorak-ecosystem-tracker -->"
CANDIDATE = re.compile(r"<!-- gorak-ecosystem-candidate: ([^\s]+) -->")


def candidate_number(tag: str) -> int:
    match = re.fullmatch(r"v\d+\.\d+\.\d+-(?:(?:alpha|beta|rc)\.\d+\.)?dev\.(\d+)", tag)
    if not match:
        raise ValueError("Expected a development candidate tag")
    return int(match[1])


def is_latest(api: GitHub, tag: str) -> bool:
    requested = candidate_number(tag)
    releases = api.pages(f"repos/{UPSTREAM}/releases?")
    numbers = []
    for release in releases:
        if release["draft"] or not release["prerelease"]:
            continue
        try:
            numbers.append(candidate_number(release["tag_name"]))
        except ValueError:
            continue
    return bool(numbers) and requested == max(numbers)


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
        opened = [pr for pr in matches if pr["state"] == "open"]
        if opened:
            matches = opened
        elif matches:
            matches = [max(matches, key=lambda pr: pr.get("number", 0))]
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
        f"Latest candidate: [{tag}](https://github.com/{UPSTREAM}/releases/tag/{tag})\n\n"
        "Background compatibility checks can wait until the owner asks to bring the "
        "ecosystem up to speed. Intermediate candidates need no separate review.\n\n"
        "| Consumer / PR | PR state | Checked head | CI |\n"
        "| --- | --- | --- | --- |\n" + "\n".join(rows) + "\n\n"
        "CI success is evidence for review, not release approval. Review findings below "
        "apply only to the recorded head; any new commit needs another review.\n"
        f"{END}"
    )
    return block, pending


def update_issue(api: GitHub, tag: str, block: str, *, new_work: bool = False) -> str:
    requested = candidate_number(tag)
    marker = f"<!-- gorak-ecosystem-candidate: {tag} -->"
    issues = [
        issue
        for issue in api.pages(f"repos/{UPSTREAM}/issues?state=all")
        if "pull_request" not in issue
        and (
            TRACKER in (issue.get("body") or "")
            or CANDIDATE.search(issue.get("body") or "")
        )
    ]
    opened = [issue for issue in issues if issue["state"] == "open"]
    if len(opened) > 1:
        raise ValueError(
            "Multiple active ecosystem tracking issues; resolve before updating"
        )
    # A delayed retry must not resurrect a completed round or create another issue.
    for issue in issues:
        previous = CANDIDATE.search(issue.get("body") or "")
        if not previous:
            raise ValueError("Tracking issue is missing its candidate marker")
        if candidate_number(previous[1]) > requested or (
            issue["state"] == "closed" and previous[1] == tag and not new_work
        ):
            return issue["html_url"]
    if not opened and new_work:
        # A changed runtime dependency starts work even if the gorak tag is unchanged.
        opened = [
            issue
            for issue in issues
            if CANDIDATE.search(issue.get("body") or "")[1] == tag
        ]
        if len(opened) > 1:
            raise ValueError("Multiple completed issues for the current candidate")
    if opened:
        issue = opened[0]
        body = issue.get("body") or ""
        if (
            body.count(START) != 1
            or body.count(END) != 1
            or body.index(START) > body.index(END)
        ):
            raise ValueError(
                "Invalid status markers; refusing to overwrite review notes"
            )
        previous = CANDIDATE.search(body)
        if len(CANDIDATE.findall(body)) != 1:
            raise ValueError("Expected exactly one candidate marker")
        updated = body[: body.index(START)] + block + body[body.index(END) + len(END) :]
        updated = CANDIDATE.sub(lambda _: marker, updated, count=1)
        # Migrate the old per-candidate header; keep all owner/review notes intact.
        legacy_header = f"Candidate: [{previous[1]}](https://github.com/{UPSTREAM}/releases/tag/{previous[1]})"
        updated = "\n".join(
            line for line in updated.split("\n") if not line.startswith(legacy_header)
        )
        if TRACKER not in updated:
            updated = TRACKER + "\n" + updated
        title = "Coordinate latest gorak candidate"
        if updated != body or issue.get("title") != title or issue["state"] == "closed":
            api.call(
                f"repos/{UPSTREAM}/issues/{issue['number']}",
                "PATCH",
                {
                    "body": updated,
                    "title": title,
                    **({"state": "open"} if issue["state"] == "closed" else {}),
                },
            )
        return issue["html_url"]
    issue = api.call(
        f"repos/{UPSTREAM}/issues",
        "POST",
        {
            "title": "Coordinate latest gorak candidate",
            "body": f"{TRACKER}\n{marker}\n\n"
            + block
            + "\n\n## Coordinator review\n\nAwaiting owner-requested consumer review. "
            "Ask Codex: `Bring the ecosystem up to the latest candidate using scripts/COORDINATE.md`.\n\n"
            "Merges and releases require owner instructions. Close this issue after the latest "
            "candidate's consumer PRs have been reviewed and merged. A future candidate starts "
            "a new coordination round; no release is implied by closing this issue.\n",
        },
    )
    return issue["html_url"]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("tag")
    parser.add_argument("--wait-seconds", type=int, default=0)
    parser.add_argument(
        "--new-work",
        action="store_true",
        help="A changed dependency PR starts a coordination round",
    )
    args = parser.parse_args()
    if not 0 <= args.wait_seconds <= 1200:
        parser.error("wait-seconds must be between 0 and 1200")
    api = GitHub(os.environ["GITHUB_TOKEN"])
    release = api.call(f"repos/{UPSTREAM}/releases/tags/{quote(args.tag, safe='')}")
    if not release or release["draft"] or not release["prerelease"]:
        raise ValueError("Expected a published gorak candidate prerelease")
    deadline = time.monotonic() + args.wait_seconds
    while True:
        if not is_latest(api, args.tag):
            print(
                "A newer candidate supersedes this run; leaving the active issue alone"
            )
            return
        block, pending = collect(api, args.tag)
        # Collection spans several API calls; check again before mutating the issue.
        if not is_latest(api, args.tag):
            print(
                "A newer candidate arrived while collecting; leaving the active issue alone"
            )
            return
        print(update_issue(api, args.tag, block, new_work=args.new_work))
        args.new_work = False
        if not pending or time.monotonic() >= deadline:
            if pending:
                print(
                    "Some checks remain pending; rerun status refresh or ask the coordinator"
                )
            return
        time.sleep(min(30, max(0, deadline - time.monotonic())))


if __name__ == "__main__":
    main()
