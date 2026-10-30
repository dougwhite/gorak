from copy import deepcopy
from pathlib import Path
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
        self.reject: set[str] = set()
        self.reads = 0
        monkeypatch.setattr(t, "inventory", self.inventory)
        monkeypatch.setattr(t, "import_component_xml", self.importing)
        monkeypatch.setattr(t, "backup_application_xml", self.exporting)

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
    assert t.status(connection(), tmp_path) == {"push": [], "pull": []}
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
    source(tmp_path)
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
    assert t.status(connection(), tmp_path) == {"push": [], "pull": []}


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
    assert t.status(connection(), tmp_path) == {"push": [], "pull": []}


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
