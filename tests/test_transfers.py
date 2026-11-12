import subprocess
from copy import deepcopy
from pathlib import Path
from subprocess import CalledProcessError
from typing import Any

import pytest
from lxml import etree

from gorak import transfers as t
from gorak.connection import OpenRoadConnection
from gorak.project import ProjectError
from gorak.xml_writer import document, new_application, new_component


def connection() -> OpenRoadConnection:
    return OpenRoadConnection("local", "node", "test", None)


def source(root: Path, app: str = "sample", name: str = "hello") -> Path:
    folder = root / app
    folder.mkdir(exist_ok=True)
    (folder / "app.json").write_text("{}")
    path = folder / f"{name}.w4gl"
    path.write_text(
        '[proc4glsource]\ndatatype="integer"\n===\nPROCEDURE hello() = { RETURN 1; }'
    )
    return path


class Database:
    def __init__(self, monkeypatch: pytest.MonkeyPatch):
        self.tokens: dict[str, dict[str, object]] = {}
        self.nodes: dict[str, etree._Element] = {}
        self.imports: list[str] = []
        self.exports: list[str] = []
        self.deletions: list[str] = []
        self.reject: set[str] = set()
        self.reads = 0
        monkeypatch.setattr(t, "inventory", self.inventory)
        monkeypatch.setattr(t, "import_component_xml", self.importing)
        monkeypatch.setattr(t, "backup_application_xml", self.exporting)
        monkeypatch.setattr(t, "delete_database_source", self.deleting)

    def deleting(self, c: Any, app: str, component: str | None, log: Path) -> None:
        key = f"{app}/{component}" if component else app
        self.deletions.append(key)
        for name in list(self.tokens):
            if name == key or name.startswith(key + "/"):
                self.tokens.pop(name)
                self.nodes.pop(name)

    def inventory(self, c: Any, app: str | None = None) -> dict[str, dict[str, object]]:
        self.reads += 1
        return deepcopy(self.tokens)

    def importing(
        self,
        c: Any,
        app: str,
        name: str,
        path: Path,
        log: Path,
        *,
        create: bool = False,
    ) -> None:
        key = app if name == "-" else f"{app}/{name}"
        self.imports.append(key)
        if key in self.reject:
            raise ProjectError("synthetic rejected import")
        for node in etree.parse(str(path)).getroot():
            key = app if node.tag == "APPLICATION" else f"{app}/{node.get('name')}"
            old = self.tokens.get(key, {})
            self.tokens[key] = {
                "name": node.get("name", ""),
                "id": old.get("id", len(self.tokens) + 1),
                "count": int(str(old.get("count", 0))) + 1,
            }
            self.nodes[key] = deepcopy(node)

    def exporting(self, c: Any, app: str, path: Path) -> None:
        self.exports.append(app)
        path.write_bytes(
            document(
                [
                    deepcopy(n)
                    for k, n in self.nodes.items()
                    if k == app or k.startswith(app + "/")
                ]
            )
        )


def test_first_push_then_both_warm_directions_do_no_conversion(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source(tmp_path)
    db = Database(monkeypatch)
    first = t.push(connection(), tmp_path, compile=False)
    assert first.succeeded == ["sample", "sample/hello"]
    assert not first.failed
    reads = db.reads
    monkeypatch.setattr(
        t, "new_component", lambda _: pytest.fail("unchanged source was reconstructed")
    )
    assert not t.push(connection(), tmp_path, compile=False).failed
    assert db.reads == reads
    assert not t.pull(connection(), tmp_path).failed
    assert db.exports == []
    assert list((tmp_path / ".openroad").iterdir()) == [
        tmp_path / ".openroad/transfers.json"
    ]


def test_push_ignores_receiver_changes_and_continues_after_component_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    a = source(tmp_path, name="a")
    b = source(tmp_path, name="b")
    db = Database(monkeypatch)
    t.push(connection(), tmp_path, compile=False)
    db.tokens["sample/a"]["count"] = 99
    a.write_text(a.read_text().replace("RETURN 1", "RETURN 2"))
    b.write_text(b.read_text().replace("RETURN 1", "RETURN 3"))
    db.reject.add("sample/a")
    result = t.push(connection(), tmp_path, compile=False)
    assert "sample/a" in result.failed
    assert "sample/b" in result.succeeded
    assert db.exports == []
    db.imports.clear()
    db.reject.clear()
    result = t.push(connection(), tmp_path, compile=False)
    assert db.imports == ["sample/a"]
    assert result.succeeded == ["sample/a"]


def test_failed_app_does_not_abort_independent_app(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source(tmp_path, app="aaa")
    source(tmp_path, app="bbb")
    db = Database(monkeypatch)
    db.reject.add("aaa")
    result = t.push(connection(), tmp_path, compile=False)
    assert "aaa" in result.failed
    assert "bbb/hello" in result.succeeded
    assert "aaa/hello" in result.skipped


def test_pull_rename_without_timestamp_and_receiver_edits(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = source(tmp_path)
    db = Database(monkeypatch)
    t.push(connection(), tmp_path, compile=False)
    path.write_text("local edits that must not prevent a pull")
    token = db.tokens.pop("sample/hello")
    token["name"] = "renamed"
    db.tokens["sample/renamed"] = token
    node = db.nodes.pop("sample/hello")
    node.set("name", "renamed")
    db.nodes["sample/renamed"] = node
    result = t.pull(connection(), tmp_path)
    assert not result.failed
    assert not path.exists()
    assert (path.parent / "renamed.w4gl").exists()
    assert t.status(connection(), tmp_path) == {"push": [], "pull": [], "conflicts": []}
    assert db.exports == ["sample"]


def test_missing_native_component_stays_pending_without_repeating_successes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source(tmp_path)
    db = Database(monkeypatch)
    t.push(connection(), tmp_path, compile=False)
    db.tokens["sample/missing"] = {"id": 100, "name": "missing", "count": 1}
    first = t.pull(connection(), tmp_path)
    assert "sample/missing" in first.failed
    assert first.succeeded == []
    second = t.pull(connection(), tmp_path)
    assert second.succeeded == []
    assert "sample/missing" in second.failed


def test_images_participate_in_local_hashes(tmp_path: Path) -> None:
    path = source(tmp_path)
    path.write_text(
        path.read_text().replace(
            'datatype="integer"',
            'datatype="integer"\nwindowicon={src="images/example.png"}',
        )
    )
    images = tmp_path / "sample/images"
    images.mkdir()
    (images / "example.png").write_bytes(b"first")
    before = t.hashes(tmp_path)
    (images / "example.png").write_bytes(b"second")
    assert t.hashes(tmp_path)["sample/hello"] != before["sample/hello"]


def test_new_target_does_not_reuse_old_checkpoint(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source(tmp_path)
    db = Database(monkeypatch)
    t.push(connection(), tmp_path, compile=False)
    db.imports.clear()
    db.tokens.clear()
    t.push(OpenRoadConnection("local", "node", "other", None), tmp_path, compile=False)
    assert db.imports == ["sample"]


def test_native_failure_continues_pull_batch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    for app in ["aaa", "bbb"]:
        source(tmp_path, app=app)
    db = Database(monkeypatch)
    t.push(connection(), tmp_path, compile=False)
    for token in db.tokens.values():
        token["count"] = 20
    original = db.exporting

    def export(c: Any, app: str, path: Path) -> None:
        if app == "aaa":
            raise ProjectError("export failed")
        original(c, app, path)

    monkeypatch.setattr(t, "backup_application_xml", export)
    result = t.pull(connection(), tmp_path)
    assert "aaa" in result.failed
    assert "bbb/hello" in result.succeeded


def test_prepared_conversion_preserves_compatibility_source(tmp_path: Path) -> None:
    from gorak.importer import signature
    from gorak.source_xml import from_bytes, read_tree
    from gorak.xml_writer import prepare_submission

    root = Path(__file__).parents[1] / "compatibility/project"
    from gorak.native_styles import resolution_scope, validation_scope

    with validation_scope(), resolution_scope():
        for folder in sorted(p.parent for p in root.glob("*/app.json")):
            names = sorted(p.stem for p in folder.glob("*.w4gl"))
            expected = from_bytes(
                document(
                    [
                        new_application(folder),
                        *[new_component(folder / f"{name}.w4gl") for name in names],
                    ]
                )
            )
            prepare_submission(expected)
            result = t.Result("push")
            output = tmp_path / f"{folder.name}.xml"
            t.prepare(folder, output, names, application=True, result=result)
            assert not result.failed
            assert signature(read_tree(output).getroot()) == signature(expected)


def test_edit_during_native_import_remains_pending(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = source(tmp_path)
    db = Database(monkeypatch)
    original = db.importing

    def importing(*args: Any, **kwargs: Any) -> None:
        original(*args, **kwargs)
        path.write_text(path.read_text().replace("RETURN 1", "RETURN 2"))

    monkeypatch.setattr(t, "import_component_xml", importing)
    result = t.push(connection(), tmp_path, compile=False)
    assert not result.failed
    assert t.status(connection(), tmp_path)["push"] == ["sample/hello"]


def test_invalid_app_manifest_does_not_stop_other_apps(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source(tmp_path, app="aaa")
    source(tmp_path, app="bbb")
    (tmp_path / "aaa/app.json").write_text("{broken")
    Database(monkeypatch)
    result = t.push(connection(), tmp_path, compile=False)
    assert "aaa" in result.failed
    assert "bbb/hello" in result.succeeded


def test_application_metadata_failure_keeps_failed_component_and_updates_good_one(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    a = source(tmp_path, name="a")
    b = source(tmp_path, name="b")
    db = Database(monkeypatch)
    t.push(connection(), tmp_path, compile=False)
    old_a = etree.tostring(db.nodes["sample/a"])
    a.write_text("[framesource]\n===\nmissing markup")
    b.write_text(b.read_text().replace("RETURN 1", "RETURN 2"))
    (a.parent / "app.json").write_text('{"description":"changed"}')
    db.imports.clear()
    result = t.push(connection(), tmp_path, compile=False)
    assert "sample" in result.failed
    assert "sample/a" in result.failed
    assert "sample/b" in result.succeeded
    assert db.imports == ["sample/b"]
    assert etree.tostring(db.nodes["sample/a"]) == old_a


def test_compiler_failure_does_not_repeat_source_import(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from gorak import compiler

    source(tmp_path)
    db = Database(monkeypatch)

    def compile(c: Any, app: str, name: str, log: Path) -> compiler.CompileResult:
        log.write_text("synthetic failure")
        return compiler.CompileResult(False, log)

    monkeypatch.setattr(compiler, "compile_source", compile)
    result = t.push(connection(), tmp_path)
    assert "sample/hello" in result.failed
    assert "compilation failed" in result.failed["sample/hello"]
    db.imports.clear()
    assert not t.push(connection(), tmp_path, compile=False).failed
    assert db.imports == []


def test_local_rename_is_reported_instead_of_creating_duplicate(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = source(tmp_path)
    db = Database(monkeypatch)
    t.push(connection(), tmp_path, compile=False)
    path.rename(path.with_name("renamed.w4gl"))
    db.imports.clear()
    result = t.push(connection(), tmp_path, compile=False)
    assert "sample/hello" in result.failed
    assert "sample/renamed" in result.skipped
    assert db.imports == []


def test_compile_failures_report_without_stopping_other_compiles(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from gorak import compiler

    for name in ["a", "b"]:
        source(tmp_path, name=name)
    Database(monkeypatch)
    called: list[str] = []

    def compile(c: Any, app: str, name: str, log: Path) -> compiler.CompileResult:
        called.append(name)
        log.write_text("E_TEST: rejected" if name == "a" else "ok")
        return compiler.CompileResult(name != "a", log)

    monkeypatch.setattr(compiler, "compile_source", compile)
    result = t.push(connection(), tmp_path)
    assert called == ["a", "b"]
    assert "sample/a" in result.failed
    assert "sample/b" in result.succeeded


def test_receiver_only_edit_is_left_alone_on_no_change_pull(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = source(tmp_path)
    db = Database(monkeypatch)
    t.push(connection(), tmp_path, compile=False)
    path.write_text(path.read_text().replace("RETURN 1", "RETURN 7"))
    assert not t.pull(connection(), tmp_path).failed
    assert "RETURN 7" in path.read_text()
    assert db.exports == []


def test_case_only_rename_keeps_new_source(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = source(tmp_path)
    db = Database(monkeypatch)
    t.push(connection(), tmp_path, compile=False)
    token = db.tokens.pop("sample/hello")
    token["name"] = "Hello"
    db.tokens["sample/Hello"] = token
    node = db.nodes.pop("sample/hello")
    node.set("name", "Hello")
    db.nodes["sample/Hello"] = node
    result = t.pull(connection(), tmp_path)
    assert not result.failed
    assert (path.parent / "Hello.w4gl").exists()
    assert t.status(connection(), tmp_path) == {"push": [], "pull": [], "conflicts": []}


def test_changes_during_export_remain_pending_without_second_export(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source(tmp_path)
    db = Database(monkeypatch)
    t.push(connection(), tmp_path, compile=False)
    db.tokens["sample/hello"]["count"] = 2
    original = db.exporting

    def export(c: Any, app: str, path: Path) -> None:
        original(c, app, path)
        db.tokens["sample/hello"]["count"] = 3

    monkeypatch.setattr(t, "backup_application_xml", export)
    result = t.pull(connection(), tmp_path)
    assert not result.failed
    assert db.exports == ["sample"]
    assert t.status(connection(), tmp_path)["pull"] == ["sample/hello"]


def test_catalog_spelling_does_not_force_repeated_pull(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source(tmp_path, name="Hello")
    db = Database(monkeypatch)
    original = db.inventory

    def inventory(*args: Any, **kwargs: Any) -> dict[str, dict[str, object]]:
        return {key.lower(): value for key, value in original(*args, **kwargs).items()}

    monkeypatch.setattr(t, "inventory", inventory)
    assert not t.push(connection(), tmp_path, compile=False).failed
    db.tokens["sample/Hello"]["count"] = 2
    first = t.pull(connection(), tmp_path)
    assert first.succeeded == ["sample/Hello"]
    assert not first.failed
    assert not t.pull(connection(), tmp_path).succeeded
    assert db.exports == ["sample"]
    assert t.status(connection(), tmp_path) == {"push": [], "pull": [], "conflicts": []}


def test_bulk_catalog_reads_are_constant_per_batch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    for app in ["aaa", "bbb", "ccc"]:
        source(tmp_path, app=app)
    db = Database(monkeypatch)
    assert not t.push(connection(), tmp_path, compile=False).failed
    assert db.reads == 2
    for value in db.tokens.values():
        value["count"] = 2
    assert not t.pull(connection(), tmp_path).failed
    assert db.reads == 3


def test_missing_application_manifest_is_reported(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source(tmp_path)
    db = Database(monkeypatch)
    t.push(connection(), tmp_path, compile=False)
    db.tokens["sample"]["count"] = 99
    del db.nodes["sample"]
    result = t.pull(connection(), tmp_path)
    assert "sample" in result.failed
    assert t.Ledger(tmp_path, connection()).entries["sample"]["database"]["count"] != 99


def test_single_edit_only_prepares_selected_component(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    edited = source(tmp_path, name="edited")
    source(tmp_path, name="unchanged")
    Database(monkeypatch)
    t.push(connection(), tmp_path, compile=False)
    edited.write_text(edited.read_text().replace("RETURN 1", "RETURN 2"))
    original = t.prepare

    def preparing(folder: Path, *args: Any, **kwargs: Any) -> list[str]:
        assert folder == tmp_path / "sample"
        assert args[1] == ["edited"]
        return original(folder, *args, **kwargs)

    monkeypatch.setattr(t, "prepare", preparing)
    result = t.push(connection(), tmp_path, compile=False)
    assert result.succeeded == ["sample/edited"]
    assert not result.failed
    assert not t.status(connection(), tmp_path)["push"]


def test_pull_preserves_manifest_format(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import json

    source(tmp_path)
    Database(monkeypatch)
    t.push(connection(), tmp_path, compile=False)
    assert not t.pull(connection(), tmp_path, full=True).failed
    manifest = tmp_path / "sample/app.json"
    payload = json.loads(manifest.read_text())
    assert manifest.read_text() == json.dumps(payload, indent=4) + "\n"


def test_cold_push_reads_sender_without_copying_tree(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source(tmp_path)
    Database(monkeypatch)
    original = t.prepare

    def preparing(folder: Path, *args: Any, **kwargs: Any) -> list[str]:
        assert folder == tmp_path / "sample"
        return original(folder, *args, **kwargs)

    monkeypatch.setattr(t, "prepare", preparing)
    assert not t.push(connection(), tmp_path, compile=False).failed
    assert not t.status(connection(), tmp_path)["push"]


def test_pull_indexes_application_directory_once(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from gorak import export

    source(tmp_path, name="one")
    source(tmp_path, name="two")
    Database(monkeypatch)
    t.push(connection(), tmp_path, compile=False)
    original = export.case_variants

    def variants(path: Path) -> list[Path]:
        assert path.parent != tmp_path / "sample"
        return original(path)

    monkeypatch.setattr(export, "case_variants", variants)
    result = t.pull(connection(), tmp_path, full=True)
    assert not result.failed
    assert not list((tmp_path / "sample").glob(".gorak-stage-*"))


def test_pull_checkpoints_written_bytes_without_rereading(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source(tmp_path)
    Database(monkeypatch)
    t.push(connection(), tmp_path, compile=False)
    original = t.hashes

    def hashing(root: Path, *args: Any, **kwargs: Any) -> dict[str, str]:
        captured = kwargs.get("captured")
        assert captured
        for path in (root / "sample").iterdir():
            if path.suffix in {".w4gl", ".wml"} or path.name == "app.json":
                assert captured[path] == t.digest(path.read_bytes())
        assert original(root, *args) == original(root, *args, **kwargs)
        return original(root, *args, **kwargs)

    monkeypatch.setattr(t, "hashes", hashing)
    assert not t.pull(connection(), tmp_path, full=True).failed


@pytest.mark.parametrize("cold", [True, False])
def test_preparation_uses_exact_captured_bytes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, cold: bool
) -> None:
    path = source(tmp_path)
    db = Database(monkeypatch)
    if not cold:
        assert not t.push(connection(), tmp_path, compile=False).failed
    intended = path.read_text().replace("RETURN 1", "RETURN 2")
    path.write_text(intended)
    original = new_component

    def transient(p: Path) -> etree._Element:
        path.write_text(intended.replace("RETURN 2", "RETURN 9"))
        try:
            return original(p)
        finally:
            path.write_text(intended)

    monkeypatch.setattr(t, "new_component", transient)
    assert not t.push(connection(), tmp_path, compile=False).failed
    assert b"RETURN 2" in etree.tostring(db.nodes["sample/hello"])
    assert b"RETURN 9" not in etree.tostring(db.nodes["sample/hello"])
    assert t.status(connection(), tmp_path)["push"] == []


def rename_objects(db: Database, renames: dict[str, str]) -> None:
    tokens = deepcopy(db.tokens)
    nodes = deepcopy(db.nodes)
    for old in renames:
        del db.tokens[old]
        del db.nodes[old]
    for old, new in renames.items():
        name = new.split("/")[-1]
        db.tokens[new] = {**tokens[old], "name": name}
        db.nodes[new] = nodes[old]
        db.nodes[new].set("name", name)


@pytest.mark.parametrize(
    "renames",
    [
        {"sample/a": "sample/b", "sample/b": "sample/a"},
        {"sample/a": "sample/b", "sample/b": "sample/c"},
    ],
)
@pytest.mark.parametrize("lowercase_catalog", [False, True])
def test_pull_rename_batch_preserves_destinations(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    renames: dict[str, str],
    lowercase_catalog: bool,
) -> None:
    if lowercase_catalog:
        renames = {
            old.rsplit("/", 1)[0] + "/" + old.rsplit("/", 1)[1].upper(): new.rsplit(
                "/", 1
            )[0]
            + "/"
            + new.rsplit("/", 1)[1].upper()
            for old, new in renames.items()
        }
    for key in renames:
        source(tmp_path, name=key.split("/")[1])
    db = Database(monkeypatch)
    if lowercase_catalog:
        original = db.inventory

        def inventory(*args: Any, **kwargs: Any) -> dict[str, dict[str, object]]:
            return {
                key.lower(): value for key, value in original(*args, **kwargs).items()
            }

        monkeypatch.setattr(t, "inventory", inventory)
    assert not t.push(connection(), tmp_path, compile=False).failed
    rename_objects(db, renames)
    result = t.pull(connection(), tmp_path)
    assert not result.failed
    for key in renames.values():
        assert (tmp_path / (key + ".w4gl")).is_file()
        assert (
            t.Ledger(tmp_path, connection()).entries[key]["database"] == db.tokens[key]
        )
    assert t.status(connection(), tmp_path) == {"push": [], "pull": [], "conflicts": []}


def test_component_asset_does_not_replace_unrelated_source(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from PIL import Image

    path = source(tmp_path, name="picture")
    source(tmp_path, name="other")
    path.write_text("[framesource]\n===\n")
    path.with_suffix(".wml").write_text(
        '<frame><topform><bgbitmap src="images/picture.png"/></topform></frame>'
    )
    (path.parent / "app.json").write_text('{"description":"images/picture.png"}')
    image = tmp_path / "sample/images/picture.png"
    image.parent.mkdir()
    Image.new("RGB", (2, 2), "red").save(image)
    db = Database(monkeypatch)
    assert not t.push(connection(), tmp_path, compile=False).failed
    db.imports.clear()
    Image.new("RGB", (2, 2), "blue").save(image)
    assert t.status(connection(), tmp_path)["push"] == ["sample/picture"]
    assert not t.push(connection(), tmp_path, compile=False).failed
    assert db.imports == ["sample/picture"]
    Image.new("RGB", (2, 2), "green").save(image.with_name("unused.png"))
    assert t.status(connection(), tmp_path)["push"] == []


@pytest.mark.parametrize(
    "part", ["sample", "sample/hello.w4gl", "sample/images", ".openroad"]
)
@pytest.mark.parametrize("operation", ["push", "pull", "status"])
def test_transfers_reject_symlink_boundaries(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, part: str, operation: str
) -> None:
    root = tmp_path / "project"
    root.mkdir()
    source(root)
    db = Database(monkeypatch)
    assert not t.push(connection(), root, compile=False).failed
    path = root / part
    outside = tmp_path / "outside"
    if path.exists():
        path.rename(outside)
    else:
        outside.mkdir()
    try:
        path.symlink_to(outside, target_is_directory=outside.is_dir())
    except OSError:
        pytest.skip("symlink permission unavailable")
    db.imports.clear()
    db.exports.clear()
    with pytest.raises(ProjectError, match="Symlinked"):
        getattr(t, operation)(connection(), root)
    assert not db.imports and not db.exports


def test_failed_compile_retries_without_reimport(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from gorak import compiler

    source(tmp_path)
    db = Database(monkeypatch)
    calls = []

    def compiling(c: Any, app: str, name: str, log: Path) -> compiler.CompileResult:
        calls.append(name)
        log.write_text("error" if len(calls) == 1 else "ok")
        return compiler.CompileResult(len(calls) > 1, log)

    monkeypatch.setattr(compiler, "compile_source", compiling)
    assert t.push(connection(), tmp_path).failed
    assert t.status(connection(), tmp_path)["compile"] == ["sample/hello"]
    db.imports.clear()
    assert not t.push(connection(), tmp_path).failed
    assert calls == ["hello", "hello"]
    assert db.imports == []
    assert not (tmp_path / ".openroad/compile-pending.json").exists()


@pytest.mark.parametrize("reject", [False, True])
def test_case_insensitive_includes_order_and_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, reject: bool
) -> None:
    source(tmp_path, app="aaa")
    source(tmp_path, app="bbb")
    (tmp_path / "aaa/app.json").write_text('{"included_applications":["BBB"]}')
    db = Database(monkeypatch)
    if reject:
        db.reject.add("bbb")
    result = t.push(connection(), tmp_path, compile=False)
    if reject:
        assert "bbb" in result.failed and "aaa" in result.skipped
        assert db.imports == ["bbb"]
    else:
        assert not result.failed
        assert db.imports == ["bbb", "aaa"]


def test_status_discovers_application_rename(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source(tmp_path)
    db = Database(monkeypatch)
    t.push(connection(), tmp_path, compile=False)
    rename_objects(db, {"sample": "renamed", "sample/hello": "renamed/hello"})
    assert t.status(connection(), tmp_path)["pull"] == ["renamed", "renamed/hello"]
    assert t.pull(connection(), tmp_path, dry_run=True).succeeded == [
        "renamed",
        "renamed/hello",
    ]


def test_pull_setup_failure_continues_other_apps(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import shutil

    for app in ["aaa", "bbb"]:
        source(tmp_path, app=app)
    db = Database(monkeypatch)
    t.push(connection(), tmp_path, compile=False)
    for token in db.tokens.values():
        token["count"] = 99
    shutil.rmtree(tmp_path / "aaa")
    (tmp_path / "aaa").write_text("obstruction")
    result = t.pull(connection(), tmp_path)
    assert "aaa" in result.failed
    assert "bbb/hello" in result.succeeded
    assert (
        t.Ledger(tmp_path, connection()).entries["bbb/hello"]["database"]["count"] == 99
    )


def test_application_name_swap_keeps_both_checkpoints(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    for app in ["aaa", "bbb"]:
        source(tmp_path, app=app)
    db = Database(monkeypatch)
    t.push(connection(), tmp_path, compile=False)
    rename_objects(
        db,
        {
            "aaa": "bbb",
            "bbb": "aaa",
            "aaa/hello": "bbb/hello",
            "bbb/hello": "aaa/hello",
        },
    )
    assert not t.pull(connection(), tmp_path).failed
    ledger = t.Ledger(tmp_path, connection())
    for key in db.tokens:
        assert ledger.entries[key]["database"] == db.tokens[key]
    assert t.status(connection(), tmp_path) == {"push": [], "pull": [], "conflicts": []}


def test_preparation_captures_markup_assets_and_absent_companions(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from PIL import Image

    path = source(tmp_path)
    path.write_text("[framesource]\n===\n")
    wml = path.with_suffix(".wml")
    wml.write_text(
        '<frame><topform><bgbitmap src="images/picture.png"/></topform></frame>'
    )
    asset = path.parent / "images/picture.png"
    asset.parent.mkdir()
    Image.new("RGB", (2, 2), "red").save(asset)
    from gorak.xml_writer import prepare_submission

    expected_node = new_component(path)
    prepare_submission(expected_node)
    expected = document([expected_node])
    original_markup, original_png = wml.read_bytes(), asset.read_bytes()
    db = Database(monkeypatch)

    def transient(p: Path) -> etree._Element:
        wml.write_text('<frame><topform bgcolor="5"/></frame>')
        Image.new("RGB", (2, 2), "blue").save(asset)
        p.with_suffix(".icons.json").write_text("{}")
        try:
            return new_component(p)
        finally:
            wml.write_bytes(original_markup)
            asset.write_bytes(original_png)
            p.with_suffix(".icons.json").unlink()

    monkeypatch.setattr(t, "new_component", transient)
    assert not t.push(connection(), tmp_path, compile=False).failed
    assert etree.tostring(
        etree.fromstring(document([db.nodes["sample/hello"]])), method="c14n"
    ) == etree.tostring(etree.fromstring(expected), method="c14n")
    assert not t.status(connection(), tmp_path)["push"]


def test_persistent_asset_dependencies_skip_reparse_but_detect_content_changes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from PIL import Image

    path = source(tmp_path)
    path.write_text("[framesource]\n===\n")
    markup = path.with_suffix(".wml")
    markup.write_text(
        '<frame><topform><bgbitmap src="images/one.png"/></topform></frame>'
    )
    assets = path.parent / "images"
    assets.mkdir()
    for name in ["one", "two"]:
        Image.new("RGB", (2, 2), "red").save(assets / (name + ".png"))
    Database(monkeypatch)
    assert not t.push(connection(), tmp_path, compile=False).failed
    # Each call reloads metadata from disk, as a new command would.
    original = t.image_dependencies
    monkeypatch.setattr(
        t, "image_dependencies", lambda *a: pytest.fail("unchanged source reparsed")
    )
    assert not t.push(connection(), tmp_path, compile=False).failed
    Image.new("RGB", (2, 2), "blue").save(assets / "one.png")
    assert t.status(connection(), tmp_path)["push"] == ["sample/hello"]
    monkeypatch.setattr(t, "image_dependencies", original)
    markup.write_text(markup.read_text().replace("one.png", "two.png"))
    assert not t.push(connection(), tmp_path, compile=False).failed
    Image.new("RGB", (2, 2), "green").save(assets / "one.png")
    assert t.status(connection(), tmp_path)["push"] == []
    Image.new("RGB", (2, 2), "blue").save(assets / "two.png")
    assert t.status(connection(), tmp_path)["push"] == ["sample/hello"]


@pytest.mark.parametrize("value", ["images/", "images/../a"])
def test_image_like_constant_text_pushes_normally(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, value: str
) -> None:
    path = source(tmp_path)
    path.write_text(
        '[constsource]\ndatatype="varchar(20)"\n'
        f'defaultstring="{value}"\nversshortremarks="{value}"\n===\n'
    )
    Database(monkeypatch)
    assert not t.push(connection(), tmp_path, compile=False).failed
    assert t.status(connection(), tmp_path) == {"push": [], "pull": [], "conflicts": []}
    assert not t.push(connection(), tmp_path, compile=False).succeeded


@pytest.mark.parametrize(
    "name,content",
    [
        (
            "frame.wml",
            '<frame remark="images/../a"><bitmap src="images/a.png"/></frame>',
        ),
        (
            "frame.w4gl",
            '[framesource]\nwindowicon="images/a.png"\nversshortremarks="images/../a"\n===',
        ),
        (
            "class.w4gl",
            '[icons]\nentries=[{id="1",src="images/a.png",path="images/../a"}]\n===',
        ),
        (
            "app.json",
            '{"window_icon":{"src":"images/a.png","path":"images/../a"},"description":"images/"}',
        ),
        (
            "field_defaults.json",
            '{"styles":[{"bitmap":{"src":"images/a.png"},"remark":"images/"}]}',
        ),
        ("frame.fielddefaults.json", '{"bitmap":{"src":"images/a.png"}}'),
    ],
)
def test_dependencies_follow_only_image_fields(
    tmp_path: Path, name: str, content: str
) -> None:
    assert t.image_dependencies(tmp_path / name, content.encode()) == {
        tmp_path / "images/a.png"
    }
    with pytest.raises(ProjectError):
        t.image_dependencies(
            tmp_path / name, content.replace("images/a.png", "images/../a").encode()
        )


def test_old_dependency_cache_is_refreshed(tmp_path: Path) -> None:
    path = source(tmp_path)
    cache: dict[str, Any] = {
        "sample/hello.w4gl": {
            "hash": t.digest(path.read_bytes()),
            "paths": ["sample/images/incorrect.png"],
        }
    }
    assert t.hashes(tmp_path, dependency_cache=cache) == t.hashes(tmp_path)
    assert cache["sample/hello.w4gl"]["paths"] == []
    assert cache["sample/hello.w4gl"]["version"] == 3


@pytest.mark.parametrize("old_cache", [False, True])
def test_separator_in_metadata_preserves_icon_dependency(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, old_cache: bool
) -> None:
    from PIL import Image

    path = source(tmp_path)
    path.write_text(
        '[framesource]\nversshortremarks="before === after"\n'
        'windowicon={src="images/icon.png"}\n===\n'
    )
    path.with_suffix(".wml").write_text("<frame><topform/></frame>")
    icon = path.parent / "images/icon.png"
    icon.parent.mkdir()
    Image.new("RGB", (2, 2), "red").save(icon)
    db = Database(monkeypatch)
    assert not t.push(connection(), tmp_path, compile=False).failed
    db.imports.clear()
    if old_cache:
        ledger = t.Ledger(tmp_path, connection())
        ledger.asset_dependencies["sample/hello.w4gl"] = {
            "version": 2,
            "hash": t.digest(path.read_bytes()),
            "paths": [],
        }
        ledger.save()
    Image.new("RGB", (2, 2), "blue").save(icon)
    # Both commands reload the ledger, including any old cached empty list.
    assert t.status(connection(), tmp_path)["push"] == ["sample/hello"]
    assert t.push(connection(), tmp_path, compile=False).succeeded == ["sample/hello"]
    assert db.imports == ["sample/hello"]
    assert t.status(connection(), tmp_path)["push"] == []


def edit_local(path: Path, value: int) -> None:
    path.write_text(path.read_text().replace("RETURN 1", f"RETURN {value}"))


def edit_database(db: Database, key: str, value: int) -> None:
    xml = etree.tostring(db.nodes[key])
    assert b"RETURN 1" in xml
    db.nodes[key] = etree.fromstring(
        xml.replace(b"RETURN 1", f"RETURN {value}".encode())
    )
    db.tokens[key]["count"] = int(str(db.tokens[key]["count"])) + 1


@pytest.mark.parametrize("direction", ["push", "pull"])
@pytest.mark.parametrize(
    ("inside_app", "target"),
    [
        (False, "sample/both"),
        (False, "sample!both"),
        (False, "sample"),
        (True, "both"),
        (True, None),
        (False, None),
    ],
)
def test_cli_conflict_aborts_before_any_transfer(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    direction: str,
    inside_app: bool,
    target: str | None,
) -> None:
    from gorak import cli

    (tmp_path / "gorak.json").write_text('{"name":"example"}')
    path = source(tmp_path, name="both")
    local_only = source(tmp_path, name="local_only")
    source(tmp_path, name="database_only")
    db = Database(monkeypatch)
    assert not t.push(connection(), tmp_path, compile=False).failed
    db.imports.clear()
    edit_local(path, 2)
    edit_local(local_only, 4)
    edit_database(db, "sample/both", 3)
    edit_database(db, "sample/database_only", 5)
    ledger = tmp_path / ".openroad/transfers.json"
    before = ledger.read_bytes()
    monkeypatch.chdir(path.parent if inside_app else tmp_path)
    monkeypatch.setattr(cli, "resolve_openroad_connection", lambda *_: connection())
    args = [direction, *([target] if target else [])]
    with pytest.raises(SystemExit) as error:
        cli.main(args)
    assert error.value.code == 1
    assert "sample/both" in capsys.readouterr().err
    assert db.imports == db.exports == []
    assert ledger.read_bytes() == before
    assert "RETURN 2" in path.read_text()

    cli.main([*args, "--force"])
    component_scope = target in {"sample/both", "sample!both", "both"}
    if direction == "push":
        assert db.imports == (
            ["sample/both"] if component_scope else ["sample/both", "sample/local_only"]
        )
        assert b"RETURN 2" in etree.tostring(db.nodes["sample/both"])
    else:
        assert db.exports == ["sample"]
        assert "RETURN 3" in path.read_text()
        database_only = path.with_name("database_only.w4gl")
        assert ("RETURN 5" in database_only.read_text()) is not component_scope


@pytest.mark.parametrize("prefer", ["push", "pull"])
def test_two_way_sync_resolves_conflict_and_moves_independent_edits(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, prefer: str
) -> None:
    both = source(tmp_path, name="both")
    local_only = source(tmp_path, name="local_only")
    database_only = source(tmp_path, name="database_only")
    db = Database(monkeypatch)
    assert not t.push(connection(), tmp_path, compile=False).failed
    db.imports.clear()
    edit_local(both, 2)
    edit_local(local_only, 4)
    edit_database(db, "sample/both", 3)
    edit_database(db, "sample/database_only", 5)
    with pytest.raises(ProjectError, match="Transfer conflicts"):
        t.execute_transfer(connection(), tmp_path, direction="sync", compile=False)
    assert db.imports == db.exports == []
    reads = db.reads
    t.execute_transfer(
        connection(), tmp_path, direction="sync", prefer=prefer, compile=False
    )
    # One plan, one scoped check per import, and one post-import checkpoint read.
    assert db.reads == reads + 2 + len(db.imports)
    assert "RETURN 5" in database_only.read_text()
    assert b"RETURN 4" in etree.tostring(db.nodes["sample/local_only"])
    expected = "RETURN 2" if prefer == "push" else "RETURN 3"
    assert expected in both.read_text()
    assert expected.encode() in etree.tostring(db.nodes["sample/both"])
    assert t.status(connection(), tmp_path) == {"push": [], "pull": [], "conflicts": []}


def test_app_manifest_push_detects_implicit_overwrite(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = source(tmp_path)
    db = Database(monkeypatch)
    assert not t.push(connection(), tmp_path, compile=False).failed
    db.imports.clear()
    (path.parent / "app.json").write_text('{"description":"Local application edit"}')
    edit_database(db, "sample/hello", 3)
    status = t.status(connection(), tmp_path)
    assert status["push"] == ["sample"]
    assert status["pull"] == ["sample/hello"]
    assert status["conflicts"] == [
        {
            "local": "sample",
            "database": "sample/hello",
            "reason": "Application push would overwrite a database change",
        }
    ]
    with pytest.raises(ProjectError, match="Application push would overwrite"):
        t.execute_transfer(connection(), tmp_path, direction="push", compile=False)
    assert db.imports == db.exports == []
    t.execute_transfer(
        connection(), tmp_path, direction="sync", prefer="pull", compile=False
    )
    assert "RETURN 3" in path.read_text()
    assert t.status(connection(), tmp_path)["push"] == ["sample"]
    assert not db.imports


def test_scoped_conflict_follows_workbench_rename(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = source(tmp_path)
    db = Database(monkeypatch)
    assert not t.push(connection(), tmp_path, compile=False).failed
    edit_local(path, 2)
    rename_objects(db, {"sample/hello": "sample/renamed"})
    with pytest.raises(ProjectError, match="Database object was renamed"):
        t.execute_transfer(
            connection(), tmp_path, direction="pull", scope="sample/hello"
        )
    assert db.exports == []
    t.execute_transfer(
        connection(), tmp_path, direction="pull", scope="sample/hello", prefer="pull"
    )
    assert not path.exists()
    assert path.with_name("renamed.w4gl").is_file()


def test_unbased_overlap_requires_an_explicit_direction(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source(tmp_path)
    db = Database(monkeypatch)
    t.execute_transfer(connection(), tmp_path, direction="push", compile=False)
    (tmp_path / ".openroad/transfers.json").unlink()
    db.imports.clear()

    def git_unavailable(*args: Any, **kwargs: Any) -> bytes:
        raise CalledProcessError(128, "git")

    monkeypatch.setattr(subprocess, "check_output", git_unavailable)
    with pytest.raises(ProjectError, match="No shared transfer checkpoint"):
        t.execute_transfer(connection(), tmp_path, direction="pull")
    assert db.imports == db.exports == []
    t.execute_transfer(connection(), tmp_path, direction="pull", prefer="pull")
    assert t.status(connection(), tmp_path)["conflicts"] == []


def test_application_scope_excludes_conflicts_in_other_apps(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from gorak import cli

    (tmp_path / "gorak.json").write_text('{"name":"example"}')
    selected = source(tmp_path, app="selected")
    other = source(tmp_path, app="other")
    db = Database(monkeypatch)
    t.execute_transfer(connection(), tmp_path, direction="push", compile=False)
    db.imports.clear()
    edit_local(selected, 2)
    edit_local(other, 3)
    edit_database(db, "other/hello", 4)
    monkeypatch.chdir(selected.parent)
    monkeypatch.setattr(cli, "resolve_openroad_connection", lambda *_: connection())
    cli.main(["push"])
    assert db.imports == ["selected/hello"]
    assert t.status(connection(), tmp_path)["conflicts"] == [
        {
            "local": "other/hello",
            "database": "other/hello",
            "reason": "Local and database changes overlap",
        }
    ]


def test_local_rename_is_an_add_and_a_tracked_delete(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = source(tmp_path)
    db = Database(monkeypatch)
    t.execute_transfer(connection(), tmp_path, direction="push")
    path.rename(path.with_name("renamed.w4gl"))
    state = t.status(connection(), tmp_path)
    assert state["push"] == ["sample/hello", "sample/renamed"]
    assert state["local_deletions"] == ["sample/hello"]
    assert "-> sample/hello (delete)" in t.format_status(state)
    t.execute_transfer(connection(), tmp_path, direction="sync")
    assert db.deletions == ["sample/hello"]
    assert "sample/renamed" in db.nodes
    assert "sample/hello" not in db.nodes


def test_pull_requires_a_local_application(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    origin = tmp_path / "origin"
    origin.mkdir()
    source(origin)
    db = Database(monkeypatch)
    assert not t.push(connection(), origin, compile=False).failed
    project = tmp_path / "project"
    project.mkdir()
    source(project, app="other")
    with pytest.raises(ProjectError, match="gorak app export sample"):
        t.execute_transfer(
            connection(), project, direction="pull", scope="sample", prefer="pull"
        )
    t.execute_transfer(connection(), project, direction="pull")
    assert db.exports == []
    assert not (project / "sample").exists()


def test_deleted_database_component_is_backed_up_after_conflict_resolution(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = source(tmp_path)
    db = Database(monkeypatch)
    assert not t.push(connection(), tmp_path, compile=False).failed
    db.tokens.pop("sample/hello")
    db.nodes.pop("sample/hello")
    assert t.status(connection(), tmp_path)["database_deletions"] == ["sample/hello"]
    edit_local(path, 2)
    with pytest.raises(ProjectError, match="Database object was deleted"):
        t.execute_transfer(connection(), tmp_path, direction="pull")
    assert "RETURN 2" in path.read_text()
    result = t.execute_transfer(connection(), tmp_path, direction="sync", prefer="pull")
    assert "Deleted sample/hello" in result
    assert not path.exists()
    backups = list((tmp_path / ".openroad/deletions").glob("*/sample/hello.w4gl"))
    assert len(backups) == 1 and "RETURN 2" in backups[0].read_text()
    assert "sample/hello" not in t.Ledger(tmp_path, connection()).entries


def test_app_export_initializes_transfer_history_and_app_import_creates_source(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    from gorak import cli, export
    from gorak.domain import Application

    database = Database(monkeypatch)
    origin = tmp_path / "origin"
    origin.mkdir()
    (origin / "gorak.json").write_text('{"name":"example"}')
    source(origin)
    monkeypatch.chdir(origin)
    monkeypatch.setattr(cli, "resolve_openroad_connection", lambda *_: connection())
    cli.main(["app", "import", "sample"])
    assert database.imports == ["sample"]

    project = tmp_path / "project"
    project.mkdir()
    (project / "gorak.json").write_text('{"name":"example"}')
    monkeypatch.chdir(project)
    monkeypatch.setattr(
        export, "read_applications", lambda *_: [Application("sample", "hello", "")]
    )
    monkeypatch.setattr(export, "read_components", lambda *_: [])
    monkeypatch.setattr(export, "backup_application_xml", database.exporting)
    monkeypatch.setattr(export, "record_component_sync_metadata", lambda *_: None)
    cli.main(["app", "export", "sample"])
    capsys.readouterr()
    cli.main(["status"])
    assert capsys.readouterr().out.strip() == "No pending transfers."
    edit_local(project / "sample/hello.w4gl", 2)
    cli.main(["push", "sample/hello"])
    assert database.imports == ["sample", "sample/hello"]


def test_delete_without_ledger_never_removes_database_source(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = source(tmp_path)
    db = Database(monkeypatch)
    t.execute_transfer(connection(), tmp_path, direction="push")
    path.unlink()
    (tmp_path / ".openroad/transfers.json").unlink()
    t.execute_transfer(connection(), tmp_path, direction="push", prefer="push")
    assert db.deletions == []
    assert "sample/hello" in db.nodes


@pytest.mark.parametrize("prefer", ["push", "pull"])
def test_application_delete_conflicts_with_new_workbench_component(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, prefer: str
) -> None:
    import shutil

    path = source(tmp_path)
    db = Database(monkeypatch)
    t.execute_transfer(connection(), tmp_path, direction="push")
    shutil.rmtree(path.parent)
    node = deepcopy(db.nodes["sample/hello"])
    node.set("name", "added")
    db.nodes["sample/added"] = node
    db.tokens["sample/added"] = {"id": 90, "name": "added", "count": 1}
    with pytest.raises(ProjectError, match="sample/added"):
        t.execute_transfer(connection(), tmp_path, direction="sync")
    assert db.deletions == db.exports == []
    t.execute_transfer(connection(), tmp_path, direction="sync", prefer=prefer)
    if prefer == "push":
        assert not db.nodes
        assert db.deletions == ["sample"]
    else:
        assert not db.deletions
        assert (tmp_path / "sample/added.w4gl").exists()
        assert (tmp_path / "sample/app.json").exists()


def test_force_push_restores_original_name_after_workbench_rename(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = source(tmp_path)
    db = Database(monkeypatch)
    t.execute_transfer(connection(), tmp_path, direction="push")
    edit_local(path, 2)
    rename_objects(db, {"sample/hello": "sample/renamed"})
    state = t.format_status(t.status(connection(), tmp_path))
    assert "<- sample/renamed (renamed from sample/hello)" in state
    assert "!! sample/hello <> sample/renamed" in state
    with pytest.raises(ProjectError, match="Database object was renamed"):
        t.execute_transfer(connection(), tmp_path, direction="sync")
    t.execute_transfer(connection(), tmp_path, direction="sync", prefer="push")
    assert db.deletions == ["sample/renamed"]
    assert b"RETURN 2" in etree.tostring(db.nodes["sample/hello"])
    assert t.status(connection(), tmp_path) == {"push": [], "pull": [], "conflicts": []}


def test_failed_rename_import_preserves_original_database_object(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = source(tmp_path)
    db = Database(monkeypatch)
    t.execute_transfer(connection(), tmp_path, direction="push")
    path.rename(path.with_name("renamed.w4gl"))
    db.reject.add("sample/renamed")
    with pytest.raises(ProjectError, match="original was kept"):
        t.execute_transfer(connection(), tmp_path, direction="push")
    assert db.deletions == []
    assert "sample/hello" in db.nodes


def test_failed_forced_rename_cleanup_is_retried(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = source(tmp_path)
    db = Database(monkeypatch)
    t.execute_transfer(connection(), tmp_path, direction="push")
    edit_local(path, 2)
    rename_objects(db, {"sample/hello": "sample/renamed"})

    def fail(*args: Any) -> None:
        raise ProjectError("synthetic deletion failure")

    monkeypatch.setattr(t, "delete_database_source", fail)
    with pytest.raises(ProjectError, match="synthetic deletion failure"):
        t.execute_transfer(connection(), tmp_path, direction="sync", prefer="push")
    assert "sample/hello" in db.nodes and "sample/renamed" in db.nodes
    assert t.status(connection(), tmp_path)["local_deletions"] == ["sample/renamed"]
    monkeypatch.setattr(t, "delete_database_source", db.deleting)
    t.execute_transfer(connection(), tmp_path, direction="sync")
    assert db.deletions == ["sample/renamed"]
    assert b"RETURN 2" in etree.tostring(db.nodes["sample/hello"])


def test_force_pull_archives_deleted_application_and_local_edits(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = source(tmp_path)
    db = Database(monkeypatch)
    t.execute_transfer(connection(), tmp_path, direction="push")
    (path.parent / "app.json").write_text('{"description":"Local change"}')
    edit_local(path, 2)
    db.deleting(connection(), "sample", None, tmp_path / "unused.log")
    with pytest.raises(ProjectError, match="Transfer conflicts"):
        t.execute_transfer(connection(), tmp_path, direction="sync")
    assert path.exists()
    summary = t.execute_transfer(
        connection(), tmp_path, direction="sync", prefer="pull"
    )
    assert "Deleted sample" in summary and "still pending" not in summary
    assert not path.parent.exists()
    backups = list((tmp_path / ".openroad/deletions").glob("*/sample/hello.w4gl"))
    assert len(backups) == 1 and "RETURN 2" in backups[0].read_text()
    assert t.status(connection(), tmp_path) == {"push": [], "pull": [], "conflicts": []}


def test_push_rechecks_catalog_before_native_delete(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = source(tmp_path)
    db = Database(monkeypatch)
    t.execute_transfer(connection(), tmp_path, direction="push")
    path.unlink()
    reads = db.reads

    def changing_inventory(c: Any) -> dict[str, dict[str, object]]:
        if db.reads > reads:
            db.tokens["sample/hello"]["count"] = 50
        return db.inventory(c)

    monkeypatch.setattr(t, "inventory", changing_inventory)
    with pytest.raises(ProjectError, match="Database source changed since planning"):
        t.execute_transfer(connection(), tmp_path, direction="push")
    assert db.deletions == []
    assert "sample/hello" in t.Ledger(tmp_path, connection()).entries


@pytest.mark.parametrize("git_state", ["clean", "dirty", "untracked"])
def test_first_pull_protects_uncommitted_source(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, git_state: str
) -> None:
    path = source(tmp_path)
    db = Database(monkeypatch)
    t.execute_transfer(connection(), tmp_path, direction="push")
    ledger = tmp_path / ".openroad/transfers.json"
    ledger.unlink()
    edit_database(db, "sample/hello", 3)

    def git(command: list[str], **kwargs: Any) -> bytes:
        if "status" in command:
            return b" M sample/hello.w4gl\x00" if git_state == "dirty" else b""
        assert "ls-files" in command
        entries = b"H sample/app.json\x00"
        if git_state != "untracked":
            entries += b"H sample/hello.w4gl\x00"
        return entries

    monkeypatch.setattr(subprocess, "check_output", git)
    if git_state == "clean":
        t.execute_transfer(connection(), tmp_path, direction="pull")
        assert "RETURN 3" in path.read_text()
        assert ledger.exists()
        assert t.status(connection(), tmp_path)["conflicts"] == []
    else:
        with pytest.raises(ProjectError, match="No shared transfer checkpoint"):
            t.execute_transfer(connection(), tmp_path, direction="pull")
        assert "RETURN 1" in path.read_text()
        assert not ledger.exists()
        assert db.exports == []


def test_pull_revalidates_receiver_after_export(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = source(tmp_path)
    db = Database(monkeypatch)
    t.execute_transfer(connection(), tmp_path, direction="push")
    edit_database(db, "sample/hello", 3)

    def exporting(*args: Any) -> None:
        db.exporting(*args)
        edit_local(path, 2)

    monkeypatch.setattr(t, "backup_application_xml", exporting)
    with pytest.raises(ProjectError, match="Local source changed since planning"):
        t.execute_transfer(connection(), tmp_path, direction="pull")
    assert "RETURN 2" in path.read_text()
    assert t.status(connection(), tmp_path)["conflicts"]


def test_pull_rename_preserves_destination_created_during_export(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = source(tmp_path)
    destination = path.with_name("renamed.w4gl")
    db = Database(monkeypatch)
    t.execute_transfer(connection(), tmp_path, direction="push")
    rename_objects(db, {"sample/hello": "sample/renamed"})

    def exporting(*args: Any) -> None:
        db.exporting(*args)
        destination.write_text("concurrent local source")

    monkeypatch.setattr(t, "backup_application_xml", exporting)
    with pytest.raises(ProjectError, match="Local source changed since planning"):
        t.execute_transfer(connection(), tmp_path, direction="pull")
    assert path.exists()
    assert destination.read_text() == "concurrent local source"
    assert "sample/hello" in t.Ledger(tmp_path, connection()).entries


@pytest.mark.parametrize("whole_app", [False, True])
def test_push_revalidates_receiver_after_preparation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, whole_app: bool
) -> None:
    path = source(tmp_path)
    db = Database(monkeypatch)
    t.execute_transfer(connection(), tmp_path, direction="push")
    if whole_app:
        (path.parent / "app.json").write_text('{"description":"changed"}')
    else:
        edit_local(path, 2)
    db.imports.clear()
    prepare = t.prepare

    def preparing(*args: Any, **kwargs: Any) -> list[str]:
        result = prepare(*args, **kwargs)
        edit_database(db, "sample/hello", 3)
        return result

    monkeypatch.setattr(t, "prepare", preparing)
    with pytest.raises(ProjectError, match="Database source changed since planning"):
        t.execute_transfer(connection(), tmp_path, direction="push")
    assert db.imports == []
    assert b"RETURN 3" in etree.tostring(db.nodes["sample/hello"])
    assert t.status(connection(), tmp_path)["conflicts"]


def test_scoped_rename_swap_refuses_without_losing_either_checkpoint(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    a = source(tmp_path, name="a")
    b = source(tmp_path, name="b")
    edit_local(b, 2)
    db = Database(monkeypatch)
    t.execute_transfer(connection(), tmp_path, direction="push")
    rename_objects(db, {"sample/a": "sample/b", "sample/b": "sample/a"})
    before = t.Ledger(tmp_path, connection()).path.read_bytes()

    with pytest.raises(ProjectError, match="Pull the whole rename group"):
        t.execute_transfer(
            connection(), tmp_path, direction="pull", scope="sample/a", dry_run=True
        )
    with pytest.raises(ProjectError, match="Pull the whole rename group"):
        t.execute_transfer(connection(), tmp_path, direction="pull", scope="sample/a")
    assert db.exports == []
    assert t.Ledger(tmp_path, connection()).path.read_bytes() == before
    t.execute_transfer(connection(), tmp_path, direction="sync")
    assert "RETURN 2" in a.read_text()
    assert "RETURN 1" in b.read_text()
    assert t.status(connection(), tmp_path) == {"push": [], "pull": [], "conflicts": []}


@pytest.mark.parametrize("scope", [None, "sample", "renamed"])
def test_application_rename_retry_includes_retained_components(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, scope: str | None
) -> None:
    original = source(tmp_path)
    db = Database(monkeypatch)
    t.execute_transfer(connection(), tmp_path, direction="push")
    rename_objects(db, {"sample": "renamed", "sample/hello": "renamed/hello"})
    with monkeypatch.context() as patch:

        def fail_projection(*args: Any, **kwargs: Any) -> None:
            raise ProjectError("synthetic component projection failure")

        patch.setattr(t, "project_component_files", fail_projection)
        with pytest.raises(
            ProjectError, match="synthetic component projection failure"
        ):
            t.execute_transfer(connection(), tmp_path, direction="pull")

    assert not (tmp_path / "sample/app.json").exists()
    assert original.exists()
    assert (tmp_path / "renamed/app.json").exists()
    assert t.status(connection(), tmp_path)["conflicts"] == []
    t.execute_transfer(connection(), tmp_path, direction="pull", scope=scope)
    assert not original.exists()
    assert (tmp_path / "renamed/hello.w4gl").exists()
    assert t.status(connection(), tmp_path) == {"push": [], "pull": [], "conflicts": []}


@pytest.mark.parametrize("whole_app", [False, True])
def test_acknowledged_deletion_clears_compilation_queue(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, whole_app: bool
) -> None:
    from gorak import compiler

    path = source(tmp_path)
    db = Database(monkeypatch)
    t.execute_transfer(connection(), tmp_path, direction="push")
    compiler.queue_compilation(tmp_path, [("sample", "hello")])
    path.unlink()
    if whole_app:
        (path.parent / "app.json").unlink()
        path.parent.rmdir()
    db.deleting(connection(), "sample", None if whole_app else "hello", path)
    monkeypatch.setattr(
        compiler, "compile_source", lambda *_: pytest.fail("Deleted target compiled")
    )
    t.execute_transfer(connection(), tmp_path, direction="sync", compile=True)
    assert "compile" not in t.status(connection(), tmp_path)
