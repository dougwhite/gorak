from lxml import etree

from gorak.frame_geometry import geometry_signature, normalized_markup
from gorak.importer import signature


def frame(value: int) -> etree._Element:
    return etree.fromstring(
        f"""<COMPONENT xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" name="panel" xsi:type="framesource"><script>initialize()={{}}</script><topform><width>{value}</width><childfields><row xsi:type="entryfield"><name>input</name><xleft>{value}</xleft></row><row_class>formfield</row_class></childfields></topform></COMPONENT>""".encode()
    )


def test_geometry_equivalence_is_exact_logical_pixels_only() -> None:
    expected, actual = frame(321), frame(323)
    assert signature(expected) != signature(actual)
    assert geometry_signature(expected) == geometry_signature(actual)
    assert normalized_markup(expected, actual) is not None
    assert geometry_signature(expected) != geometry_signature(frame(333))
    actual.find("script").text = "initialize()={ MESSAGE 'unexpected'; }"
    assert normalized_markup(expected, actual) is None


def test_geometry_does_not_hide_opaque_content_changes() -> None:
    a, b = frame(321), frame(323)
    for node, value in [(a, "321"), (b, "323")]:
        opaque = etree.SubElement(node.find("topform"), "opaque")
        etree.SubElement(opaque, "width").text = value
    assert geometry_signature(a) != geometry_signature(b)
