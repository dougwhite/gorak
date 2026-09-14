from copy import deepcopy

import pytest
from lxml import etree

from gorak.defaults_writer import overlay_defaults
from gorak.errors import ProjectError
from gorak.field_defaults import parse_field_defaults_node


def test_existing_default_properties_roundtrip_without_changing_style_groups() -> None:
    node = etree.parse("tests/fixtures/fm_example_frame.xml").find("COMPONENT")
    assert node is not None
    container = node.find("fielddefaults")
    assert container is not None
    original = parse_field_defaults_node(container)
    desired = deepcopy(original)
    style = next(s for s in desired["field_styles"] if s["type"] == "entryfield")
    style["properties"]["width"] = "2000"
    overlay_defaults(node, desired)
    assert parse_field_defaults_node(container) == desired
    overlay_defaults(node, original)
    assert parse_field_defaults_node(container) == original


def test_unknown_style_identity_is_rejected() -> None:
    node = etree.parse("tests/fixtures/fm_example_frame.xml").find("COMPONENT")
    assert node is not None
    desired = parse_field_defaults_node(node.find("fielddefaults"))
    desired["field_styles"][0]["group"] = "invented"
    with pytest.raises(ProjectError, match="identities"):
        overlay_defaults(node, desired)
