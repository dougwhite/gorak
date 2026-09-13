import json
from pathlib import Path

import pytest
from lxml import etree

from gorak.parser import parse_component_node
from gorak.project import ProjectError
from gorak.xml_writer import document, new_application, new_component


def test_class_declarations_round_trip(tmp_path: Path) -> None:
    path = tmp_path / "example.w4gl"
    path.write_text("""[classsource]
superclass = "userobject"
[attributes]
items = "ARRAY OF VARCHAR(32) NOT NULL"
[methods]
Check = "PRIVATE METHOD RETURNING INTEGER NOT NULL"
===
METHOD Check() = { RETURN 1; }
""")
    node = new_component(path)
    parsed = parse_component_node(etree.fromstring(document([node]))[0])
    assert parsed.props["attributes"] == {"items": "ARRAY OF VARCHAR(32) NOT NULL"}
    assert parsed.props["methods"] == {
        "Check": "PRIVATE METHOD RETURNING INTEGER NOT NULL"
    }
    assert parsed.script == "METHOD Check() = { RETURN 1; }"


def test_app_includes_and_escaping(tmp_path: Path) -> None:
    folder = tmp_path / "example"
    folder.mkdir()
    (folder / "app.json").write_text(
        json.dumps(
            {
                "description": "A & B",
                "included_applications": [
                    "library",
                    {"name": "finance", "image": "finance.pkg"},
                ],
            }
        )
    )
    node = etree.fromstring(document([new_application(folder)]))[0]
    assert node.findtext("versshortremarks") == "A & B"
    assert node.findall("included_apps/row")[1].findtext("sequence") == "1"
    assert node.findall("included_apps/row")[2].findtext("imgfilename") == "finance.pkg"


@pytest.mark.parametrize(
    "metadata",
    [
        "[framesource]",
        '[proc4glsource]\nunknown = "lost"',
        'unknown = "lost"\n[proc4glsource]',
    ],
)
def test_unsupported_metadata_rejected(tmp_path: Path, metadata: str) -> None:
    path = tmp_path / "example.w4gl"
    path.write_text(metadata + "\n===\nPROCEDURE example() = { RETURN; }")
    with pytest.raises(ProjectError):
        new_component(path)


def test_application_uses_openroad_schema_order(tmp_path: Path) -> None:
    folder = tmp_path / "example"
    folder.mkdir()
    (folder / "app.json").write_text(
        json.dumps(
            {
                "starting_component": "start",
                "description": "Example",
                "database_name": "runtime",
                "database_type": "2",
            }
        )
    )
    assert [child.tag for child in new_application(folder)] == [
        "versshortremarks",
        "included_apps",
        "procstart",
        "databasename",
        "database_type",
    ]


def test_procedure_uses_openroad_schema_order(tmp_path: Path) -> None:
    path = tmp_path / "example.w4gl"
    path.write_text(
        '[proc4glsource]\nisnullable = "1"\ndatatype = "integer"\n===\nPROCEDURE example() = { RETURN 1; }'
    )
    assert [child.tag for child in new_component(path)] == [
        "script",
        "datatype",
        "isnullable",
    ]
