"""Row-type normalization retains the original native traversal boundaries."""

import pytest
from lxml import etree

from gorak.native_normalization import XSI, explicit_row_types


@pytest.mark.parametrize("position", [0, 1, 2])
def test_row_types_preserve_explicit_types_and_collection_order(position: int) -> None:
    root = etree.fromstring(
        '<items xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">'
        '<row name="first"/><row name="second" xsi:type="special"/></items>'
    )
    declaration = etree.Element("row_class")
    declaration.text = "base"
    root.insert(position, declaration)
    explicit_row_types(root)
    assert [row.get("name") for row in root] == ["first", "second"]
    assert [row.get(XSI) for row in root] == ["base", "special"]


@pytest.mark.parametrize("opaque", ["extension", "taggedvalues", "frmflow"])
def test_row_types_leave_opaque_descendants_untouched(opaque: str) -> None:
    root = etree.fromstring(
        f"<root><{opaque}><nested><row/><row_class>base</row_class>"
        f"</nested></{opaque}></root>"
    )
    original = etree.tostring(root)
    explicit_row_types(root)
    assert etree.tostring(root) == original


@pytest.mark.parametrize(
    "contents",
    [
        "<row/>",
        "<row/><row_class/>",
        '<row/><row_class explicit="yes">base</row_class>',
        "<row/><row_class><nested>base</nested></row_class>",
        "<row_class><?unsupported content?></row_class>",
    ],
)
def test_row_types_do_not_interpret_nonqualifying_declarations(contents: str) -> None:
    root = etree.fromstring(f"<root>{contents}</root>")
    original = etree.tostring(root)
    explicit_row_types(root)
    assert etree.tostring(root) == original


def test_row_types_use_only_first_duplicate_declaration() -> None:
    root = etree.fromstring(
        "<root><row/><row_class>first</row_class><row_class>second</row_class></root>"
    )
    explicit_row_types(root)
    assert root.find("row").get(XSI) == "first"
    assert root.findtext("row_class") == "second"
