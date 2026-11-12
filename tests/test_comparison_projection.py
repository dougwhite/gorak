"""Comparison projects layouts once while keeping complete metadata and validation."""

from copy import deepcopy
from dataclasses import replace
from pathlib import Path

import pytest
from lxml import etree

from gorak import parser
from gorak.contract_source import equivalent
from gorak.domain import Component
from gorak.errors import ProjectError

FIXTURES = [
    "fm_example_frame.xml",
    "fm_complex_frame.xml",
    "p4_example_procedure.xml",
    "uc_example_userclass.xml",
]
XSI = "{http://www.w3.org/2001/XMLSchema-instance}type"


@pytest.mark.parametrize("fixture", FIXTURES)
def test_metadata_projection_preserves_every_nonlayout_value(fixture: str) -> None:
    node = etree.parse(str(Path("tests/fixtures") / fixture)).find("COMPONENT")
    assert node is not None
    before = etree.tostring(node)
    expected = replace(parser.parse_component_node(node), markup=None)
    assert parser.parse_component_node(node, project_markup=False) == expected
    assert etree.tostring(node) == before


@pytest.mark.parametrize("project_markup", [False, True])
@pytest.mark.parametrize(
    "contents",
    [
        "<script><?unsupported content?></script>",
        "<queries/><queries/>",
        '<frmflow><row oidref="missing"/></frmflow>',
    ],
)
def test_metadata_only_parser_keeps_validation(
    project_markup: bool, contents: str
) -> None:
    node = etree.fromstring(
        f'<COMPONENT xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" '
        f'name="panel" xsi:type="framesource">{contents}</COMPONENT>'
    )
    with pytest.raises(ProjectError):
        parser.parse_component_node(node, project_markup=project_markup)


def test_comparison_does_not_serialize_discarded_markup(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    node = etree.parse("tests/fixtures/fm_example_frame.xml").find("COMPONENT")
    assert node is not None
    monkeypatch.setattr(
        parser,
        "encode_frame_markup",
        lambda *args, **kwargs: pytest.fail("Comparison serialized unused markup"),
    )
    assert equivalent(node, deepcopy(node))


@pytest.mark.parametrize("changed_metadata", [False, True])
def test_comparison_still_validates_deferred_layout(changed_metadata: bool) -> None:
    node = etree.fromstring(
        '<COMPONENT xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" '
        'name="panel" xsi:type="framesource"><topform><childfields>'
        '<row xsi:type="!invalid"/></childfields></topform></COMPONENT>'
    )
    other = deepcopy(node)
    if changed_metadata:
        etree.SubElement(other, "windowtitle").text = "Changed"
    with pytest.raises(ValueError, match="Invalid tag name"):
        equivalent(node, other)


@pytest.mark.parametrize("exact_styles", [False, True])
@pytest.mark.parametrize(
    "change",
    ["same", "script", "title", "coordinate", "mode", "style", "field", "order"],
)
def test_comparison_matches_full_metadata_projection(
    exact_styles: bool, change: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    original = etree.parse("tests/fixtures/fm_example_frame.xml").find("COMPONENT")
    assert original is not None
    changed = deepcopy(original)
    if change == "script":
        changed.find("script").text = "initialize()={ return; }"
    elif change == "title":
        etree.SubElement(changed, "windowtitle").text = "Changed"
    elif change == "coordinate":
        etree.SubElement(changed.find("topform"), "xleft").text = "1234"
    elif change == "mode":
        etree.SubElement(
            changed.find("topform/childfields/row"), "defaultvalue"
        ).text = "2"
    elif change == "style":
        changed.find("fielddefaults/row/width").text = "456"
    elif change == "field":
        fields = changed.find("topform/childfields")
        assert fields is not None
        fields.append(deepcopy(fields.find("row")))
    elif change == "order":
        fields = changed.find("topform/childfields")
        assert fields is not None
        fields[:] = list(reversed(fields))
    actual = equivalent(original, changed, exact_styles=exact_styles)
    parse = parser.parse_component_node

    def full_projection(node: etree._Element, **kwargs: bool) -> Component:
        kwargs.pop("project_markup", None)
        return replace(parse(node, **kwargs), markup=None)

    monkeypatch.setattr(parser, "parse_component_node", full_projection)
    assert equivalent(original, changed, exact_styles=exact_styles) == actual


def test_metadata_only_field_template_keeps_native_validation() -> None:
    node = etree.fromstring(
        '<COMPONENT xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" '
        'name="field" xsi:type="fieldtemplate">'
        '<framefield xsi:type="entryfield"><name>value</name></framefield>'
        "</COMPONENT>"
    )
    assert parser.parse_component_node(node, project_markup=False) == replace(
        parser.parse_component_node(node), markup=None
    )
    node.append(deepcopy(node[0]))
    for project_markup in (False, True):
        with pytest.raises(ProjectError, match="duplicate"):
            parser.parse_component_node(node, project_markup=project_markup)


def test_comparison_preserves_unknown_palette_projection_errors() -> None:
    node = etree.fromstring(
        '<COMPONENT xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" '
        'name="panel" xsi:type="framesource"><fielddefaults><row>'
        "<clienttext>unknown_field</clienttext><childfields>"
        '<row xsi:type="unknown_field"><width>5</width></row>'
        "</childfields></row></fielddefaults><topform><childfields>"
        '<row xsi:type="unknown_field"><name>value</name></row>'
        "</childfields></topform></COMPONENT>"
    )
    with pytest.raises(ProjectError, match="Unsupported XML type: unknown_field"):
        equivalent(node, node)
