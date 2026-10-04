"""Propose published LSP/designer assets in the existing extension compatibility PR."""

import base64
import hashlib
import io
import json
import os
import re
import subprocess
import sys
import tarfile
import tempfile
import tomllib
from pathlib import Path
from urllib.parse import quote
from urllib.request import urlopen

from ecosystem_release import PREFIX, UPSTREAM, GitHub, update_manifest
from ecosystem_status import candidate_number

EXTENSION = "dougwhite/gorak-vscode-ext"
SOURCES = {
    "dougwhite/gorak-lsp-rs": "lsp_revision",
    "dougwhite/gorak-frame-designer": "frame_designer_revision",
}
START = "<!-- gorak-dependencies:start -->"
END = "<!-- gorak-dependencies:end -->"


def version(tag):
    match = re.fullmatch(r"v(\d+)\.(\d+)\.(\d+)(?:-([0-9A-Za-z.-]+))?", tag)
    if not match:
        raise ValueError("Expected a versioned release tag")
    pre = match[4]
    suffix = (
        (1, ())
        if pre is None
        else (
            0,
            tuple((0, int(p)) if p.isdecimal() else (1, p) for p in pre.split(".")),
        )
    )
    return (*map(int, match.groups()[:3]), suffix)


def latest_release(api, repo):
    releases = []
    for release in api.pages(f"repos/{repo}/releases?"):
        if release["draft"]:
            continue
        try:
            key = version(release["tag_name"])
        except ValueError:
            continue
        releases.append((key, release))
    if not releases:
        raise ValueError("No published dependency release")
    return max(releases, key=lambda item: item[0])[1]


def download(release, repo, name):
    url = f"https://github.com/{repo}/releases/download/{quote(release['tag_name'], safe='')}/{name}"
    assets = [asset for asset in release["assets"] if asset["name"] == name]
    if len(assets) != 1 or assets[0]["browser_download_url"] != url:
        raise ValueError(f"Missing or unexpected release asset: {name}")
    with urlopen(url, timeout=30) as response:
        data = response.read(50 * 1024 * 1024 + 1)
    if len(data) > 50 * 1024 * 1024:
        raise ValueError("Release asset exceeds size limit")
    return data


def verified_asset(release, repo, name, fetch=download):
    sums = fetch(release, repo, "SHA256SUMS").decode("utf-8")
    matches = re.findall(rf"(?m)^([0-9a-f]{{64}})  {re.escape(name)}$", sums)
    if len(matches) != 1:
        raise ValueError("Missing or ambiguous asset checksum")
    data = fetch(release, repo, name)
    if hashlib.sha256(data).hexdigest() != matches[0]:
        raise ValueError("Release checksum mismatch")
    return data


def contents(api, repo, path, ref):
    record = api.call(f"repos/{repo}/contents/{path}?ref={quote(ref, safe='')}")
    if not record or record.get("encoding") != "base64":
        raise ValueError(f"Missing text file: {path}")
    return base64.b64decode(record["content"]).decode("utf-8")


def change_pin(text, key, value):
    before = tomllib.loads(text)
    after, count = re.subn(
        rf'(?m)^({key}[ \t]*=[ \t]*)"[^"\r\n]+"',
        lambda m: m[1] + json.dumps(value),
        text,
    )
    if count != 1 or tomllib.loads(after) != {**before, key: value}:
        raise ValueError("Dependency pin changed unrelated manifest values")
    return after


def update_files(files, source, release, fetch=download, run=subprocess.run):
    tag = release["tag_name"]
    key = SOURCES[source]
    old = tomllib.loads(files["ecosystem.toml"])[key]
    if version(tag) < version(old):
        return files
    changed = dict(files)
    changed["ecosystem.toml"] = change_pin(files["ecosystem.toml"], key, tag)
    if key == "lsp_revision":
        data = verified_asset(release, source, "release.json", fetch)
        manifest = json.loads(data)
        if manifest["version"] != tag[1:] or set(manifest["platforms"]) != {
            "win32-x64",
            "linux-x64",
        }:
            raise ValueError("LSP release must match tag and supply both platforms")
        for asset in [
            *manifest["platforms"].values(),
            {"sha256": manifest["noticesSha256"]},
        ]:
            if not re.fullmatch("[0-9a-f]{64}", asset["sha256"]):
                raise ValueError("Invalid LSP asset checksum")
        server = json.loads(files["server.json"])
        if server["repository"] != source:
            raise ValueError("Unexpected LSP repository")
        digest = hashlib.sha256(data).hexdigest()
        if tag == old and server["sha256"] != digest:
            raise ValueError("Pinned LSP release was mutated")
        changed["server.json"] = (
            json.dumps({**server, "tag": tag, "sha256": digest}, indent=2) + "\n"
        )
    else:
        name = f"gorak-frame-designer-{tag[1:]}.tgz"
        data = verified_asset(release, source, name, fetch)
        with tarfile.open(fileobj=io.BytesIO(data), mode="r:gz") as archive:
            entry = archive.getmember("package/package.json")
            if not entry.isfile() or entry.size > 1024 * 1024:
                raise ValueError("Invalid designer package manifest")
            package = json.load(archive.extractfile(entry))
        if package["name"] != "gorak-frame-designer" or package["version"] != tag[1:]:
            raise ValueError("Designer archive identity disagrees with tag")
        integrity = "sha512-" + base64.b64encode(hashlib.sha512(data).digest()).decode(
            "ascii"
        )
        lock = json.loads(files["package-lock.json"])
        if tag == old:
            if (
                lock["packages"]["node_modules/gorak-frame-designer"]["integrity"]
                != integrity
            ):
                raise ValueError("Pinned designer release was mutated")
            return files
        url = f"https://github.com/{source}/releases/download/{tag}/{name}"
        pkg = json.loads(files["package.json"])
        pkg["dependencies"]["gorak-frame-designer"] = url
        changed["package.json"] = json.dumps(pkg, indent=2) + "\n"
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "package.json").write_text(
                changed["package.json"], encoding="utf-8"
            )
            (root / "package-lock.json").write_text(
                files["package-lock.json"], encoding="utf-8"
            )
            # Resolve changed transitive dependencies without executing lifecycle scripts.
            run(
                [
                    "npm",
                    "install",
                    "--package-lock-only",
                    "--ignore-scripts",
                    "--no-audit",
                    "--no-fund",
                ],
                cwd=root,
                check=True,
                timeout=180,
                stdout=subprocess.DEVNULL,
            )
            changed["package-lock.json"] = (root / "package-lock.json").read_text(
                encoding="utf-8"
            )
        lock = json.loads(changed["package-lock.json"])
        dep = lock["packages"]["node_modules/gorak-frame-designer"]
        if (
            dep["integrity"] != integrity
            or dep["resolved"] != url
            or dep["version"] != tag[1:]
            or lock["packages"][""]["dependencies"]["gorak-frame-designer"] != url
        ):
            raise ValueError("Resolved designer lock does not match verified release")
    return changed


def propose(api, root_api, source, tag):
    if source not in SOURCES:
        raise ValueError("Unsupported dependency repository")
    version(tag)
    release = latest_release(api, source)
    if release["tag_name"] != tag:
        print("A newer dependency release supersedes this notification")
        return False
    endpoint = f"repos/{EXTENSION}"
    repository = api.call(endpoint)
    default = repository["default_branch"]
    proposals = api.pages(f"{endpoint}/pulls?state=all")
    opened = [
        pr
        for pr in proposals
        if pr["state"] == "open"
        if pr["head"]["repo"]
        and pr["head"]["repo"]["full_name"] == EXTENSION
        and pr["head"]["ref"].startswith(PREFIX)
        and pr["base"]["ref"] == default
    ]
    if len(opened) > 1:
        raise ValueError("Multiple open extension compatibility PRs")
    existing = opened[0] if opened else None
    branch = (
        existing["head"]["ref"]
        if existing
        else PREFIX + f"dependencies-{source.split('/')[1]}-{release['id']}"
    )
    if not existing and any(
        pr["state"] == "closed"
        and pr["head"]["repo"]
        and pr["head"]["repo"]["full_name"] == EXTENSION
        and (
            pr["head"]["ref"] == branch
            or f"<!-- gorak-dependency: {source}@{tag} -->" in (pr.get("body") or "")
        )
        for pr in proposals
    ):
        print("This dependency proposal was already handled")
        return False
    # Retry a partially created branch; never force-push or discard existing work.
    ref = api.call(f"{endpoint}/git/ref/heads/{quote(branch, safe='')}")
    if existing and not ref:
        raise ValueError("Existing compatibility PR lost its branch")
    base = ref or api.call(f"{endpoint}/git/ref/heads/{quote(default, safe='')}")
    read_ref = base["object"]["sha"]
    paths = ("ecosystem.toml", "server.json", "package.json", "package-lock.json")
    files = {path: contents(api, EXTENSION, path, read_ref) for path in paths}
    updated = dict(update_files(files, source, release))
    if updated == files and not ref:
        print(
            "Dependency already pinned, or requested update would regress its version"
        )
        return False
    releases = root_api.pages(f"repos/{UPSTREAM}/releases?")
    candidates = []
    for item in releases:
        if item["draft"] or not item["prerelease"]:
            continue
        try:
            candidates.append((candidate_number(item["tag_name"]), item["tag_name"]))
        except ValueError:
            continue
    if not candidates:
        raise ValueError("Publish a gorak candidate before dependency coordination")
    gorak_tag = max(candidates)[1]
    contract = tomllib.loads(contents(root_api, UPSTREAM, "ecosystem.toml", gorak_tag))
    updated["ecosystem.toml"], _ = update_manifest(
        updated["ecosystem.toml"], gorak_tag, contract["source_version"]
    )
    # Recheck after downloading/resolving; an older queued notification cannot win.
    if latest_release(api, source)["tag_name"] != tag:
        return False
    pin = tomllib.loads(updated["ecosystem.toml"])
    block = f"{START}\nTest released LSP `{pin['lsp_revision']}` and designer `{pin['frame_designer_revision']}`. Checksums and package lock are pinned; installed-VSIX CI must certify these exact assets.\n{END}"
    block = block.replace(
        END,
        f"<!-- gorak-dependency: dougwhite/gorak-lsp-rs@{pin['lsp_revision']} -->\n<!-- gorak-dependency: dougwhite/gorak-frame-designer@{pin['frame_designer_revision']} -->\n"
        + END,
    )
    body = (existing.get("body") or "") if existing else ""
    # Preserve discussion text while advancing the root candidate marker.
    body = re.sub(r"<!-- gorak-candidate: [^\s]+ -->", "", body)
    if START in body or END in body:
        if (
            body.count(START) != 1
            or body.count(END) != 1
            or body.index(START) > body.index(END)
        ):
            raise ValueError("Invalid dependency PR markers")
        body = body[: body.index(START)] + block + body[body.index(END) + len(END) :]
    else:
        body += "\n\n" + block
    body = f"<!-- gorak-candidate: {gorak_tag} -->\n" + body.strip() + "\n"
    if existing and updated == files and body == (existing.get("body") or ""):
        print("Dependency already proposed")
        return False
    if not ref:
        api.call(
            f"{endpoint}/git/refs",
            "POST",
            {"ref": "refs/heads/" + branch, "sha": base["object"]["sha"]},
        )
        ref = base
    if updated != files:
        parent = ref["object"]["sha"]
        commit = api.call(f"{endpoint}/git/commits/{parent}")
        tree = api.call(
            f"{endpoint}/git/trees",
            "POST",
            {
                "base_tree": commit["tree"]["sha"],
                "tree": [
                    {"path": path, "mode": "100644", "type": "blob", "content": text}
                    for path, text in updated.items()
                    if text != files[path]
                ],
            },
        )
        new = api.call(
            f"{endpoint}/git/commits",
            "POST",
            {
                "message": f"Certify {source.split('/')[1]} {tag} in gorak extension",
                "tree": tree["sha"],
                "parents": [parent],
            },
        )
        api.call(
            f"{endpoint}/git/refs/heads/{quote(branch, safe='')}",
            "PATCH",
            {"sha": new["sha"], "force": False},
        )
    payload = {"title": "Certify latest gorak ecosystem in extension", "body": body}
    if existing:
        pr = api.call(f"{endpoint}/pulls/{existing['number']}", "PATCH", payload)
    else:
        pr = api.call(
            f"{endpoint}/pulls", "POST", {**payload, "head": branch, "base": default}
        )
    print(pr["html_url"])
    return True


def reconcile(api, root_api):
    changed = False
    for source in SOURCES:
        tag = latest_release(api, source)["tag_name"]
        changed = propose(api, root_api, source, tag) or changed
    return changed


def main():
    if os.environ.get("GITHUB_REPOSITORY") != UPSTREAM:
        raise ValueError("Dependency coordination runs only in gorak")
    if sys.argv[1:] == ["--reconcile"] and not os.environ.get("ECOSYSTEM_PR_TOKEN"):
        # Docs-only root pushes can run before credentials are configured.
        # Code candidate publication separately requires this token.
        print("Dependency reconciliation skipped: ECOSYSTEM_PR_TOKEN is not configured")
        return
    api = GitHub(os.environ["ECOSYSTEM_PR_TOKEN"])
    root_api = GitHub(os.environ["GITHUB_TOKEN"])
    if sys.argv[1:] != ["--reconcile"]:
        if sys.argv[1:]:
            raise ValueError("Unexpected coordinator arguments")
        event = json.loads(
            Path(os.environ["GITHUB_EVENT_PATH"]).read_text(encoding="utf-8")
        )
        payload = (
            event.get("client_payload", {})
            if "client_payload" in event
            else event.get("inputs", {})
        )
        source, tag = payload["source"], payload["tag"]
        if source not in SOURCES:
            raise ValueError("Unsupported dependency repository")
        version(tag)
        publication = api.call(f"repos/{source}/releases/tags/{quote(tag, safe='')}")
        if not publication or publication["draft"]:
            raise ValueError(
                "Notification must identify a published dependency release"
            )
    # GitHub concurrency retains only the newest pending job. Every wake-up must
    # reconcile both dependencies; a replaced notification must not lose an update.
    changed = reconcile(api, root_api)
    with open(os.environ["GITHUB_OUTPUT"], "a", encoding="utf-8") as output:
        output.write(f"changed={str(changed).lower()}\n")


if __name__ == "__main__":
    main()
