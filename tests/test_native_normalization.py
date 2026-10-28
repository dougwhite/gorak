"""Trivial child lists preserve the established complete XML signatures."""

import pytest
from lxml import etree

from gorak.importer import signature as raw_signature
from gorak.native_normalization import signature


@pytest.mark.parametrize("pixel_geometry", [False, True])
@pytest.mark.parametrize(
    "source,expected",
    [
        ("<literal/>", "<literal/>"),
        ("<literal> \t\n </literal>", "<literal> \t\n </literal>"),
        (
            '<literal key="value"> before&#13;after </literal>',
            '<literal key="value"> before&#13;after </literal>',
        ),
        ("<root> <child/> </root>", "<root> <child/> </root>"),
        (
            "<root>before<child>inside</child>after</root>",
            "<root>before<child>inside</child>after</root>",
        ),
        (
            "<root>before<?vendor data?> after&#13; </root>",
            "<root>before<?vendor data?> after&#13; </root>",
        ),
        ("<root><!--comment--></root>", "<root><!--comment--></root>"),
        (
            '<root xmlns:unused="urn:unused"><unary><leaf/></unary></root>',
            '<root xmlns:unused="urn:unused"><unary><leaf/></unary></root>',
        ),
        (
            "<root><unary><z/><a/></unary></root>",
            "<root><unary><a/><z/></unary></root>",
        ),
        (
            "<root><unary><z/>literal tail<a/></unary></root>",
            "<root><unary><z/>literal tail<a/></unary></root>",
        ),
        (
            "<root><unary><z/><?vendor data?><a/></unary></root>",
            "<root><unary><z/><?vendor data?><a/></unary></root>",
        ),
    ],
)
def test_trivial_lists_preserve_text_tail_special_nodes_and_nested_ordering(
    source: str, expected: str, pixel_geometry: bool
) -> None:
    node = etree.fromstring(source)
    before = etree.tostring(node)
    assert signature(node, pixel_geometry=pixel_geometry) == raw_signature(
        etree.fromstring(expected)
    )
    assert etree.tostring(node) == before


@pytest.mark.parametrize("opaque", ["extension", "taggedvalues", "frmflow"])
def test_unary_opaque_ancestors_preserve_nested_property_order(opaque: str) -> None:
    node = etree.fromstring(
        f"<root><unary><{opaque}><nested><z/><a/></nested></{opaque}></unary></root>"
    )
    before = etree.tostring(node)
    assert signature(node, pixel_geometry=True) == raw_signature(node)
    assert etree.tostring(node) == before
