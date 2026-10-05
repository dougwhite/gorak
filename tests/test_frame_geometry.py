import pytest
from lxml import etree

from gorak.frame_geometry import geometry_signature, normalized_markup
from gorak.importer import signature


def frame(value: int, kind: str) -> etree._Element:
    return etree.fromstring(
        f"""<COMPONENT xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" name="panel" xsi:type="{kind}"><script>initialize()={{}}</script><topform><width>{value}</width><childfields><row xsi:type="entryfield"><name>input</name><xleft>{value}</xleft></row><row_class>formfield</row_class></childfields></topform></COMPONENT>""".encode()
    )


@pytest.mark.parametrize("kind", ["framesource", "frametemplate"])
@pytest.mark.parametrize(
    ("left", "right", "different"), [(321, 323, 333), (1042, 1040, 1055)]
)
def test_geometry_equivalence_is_exact_logical_pixels_only(
    kind: str, left: int, right: int, different: int
) -> None:
    expected, actual = frame(left, kind), frame(right, kind)
    assert signature(expected) != signature(actual)
    assert geometry_signature(expected) == geometry_signature(actual)
    assert normalized_markup(expected, actual) is not None
    assert geometry_signature(expected) != geometry_signature(frame(different, kind))
    actual.find("script").text = "initialize()={ MESSAGE 'unexpected'; }"
    assert normalized_markup(expected, actual) is None


@pytest.mark.parametrize("kind", ["framesource", "frametemplate"])
def test_geometry_does_not_hide_opaque_content_changes(kind: str) -> None:
    a, b = frame(321, kind), frame(323, kind)
    for node, value in [(a, "321"), (b, "323")]:
        opaque = etree.SubElement(node.find("topform"), "opaque")
        etree.SubElement(opaque, "width").text = value
    assert geometry_signature(a) != geometry_signature(b)
    assert normalized_markup(a, b) is None
