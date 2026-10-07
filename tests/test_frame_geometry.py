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


@pytest.mark.parametrize("kind", ["framesource", "frametemplate"])
@pytest.mark.parametrize("field_kind", ["entryfield", "menuitem"])
def test_field_modes_compose_with_geometry(kind: str, field_kind: str) -> None:
    from copy import deepcopy

    from gorak.contract_source import equivalent

    expected = frame(1000, kind)
    field = expected.find(".//row")
    field.set("{http://www.w3.org/2001/XMLSchema-instance}type", field_kind)
    etree.SubElement(field, "defaultvalue").text = "1"
    etree.SubElement(field, "defaultstring").text = "7"
    actual = deepcopy(expected)
    actual.find("topform/width").text = "1001"
    mode = actual.find(".//defaultvalue")
    mode.getparent().remove(mode)
    expected_bytes, actual_bytes = etree.tostring(expected), etree.tostring(actual)
    assert not equivalent(expected, actual)
    assert signature(expected) != signature(actual)
    assert normalized_markup(expected, actual) is not None
    assert normalized_markup(actual, expected) is not None
    assert etree.tostring(expected) == expected_bytes
    assert etree.tostring(actual) == actual_bytes

    for value in ["0", "2", "3", "", "99"]:
        changed = deepcopy(actual)
        etree.SubElement(changed.find(".//row"), "defaultvalue").text = value
        assert normalized_markup(expected, changed) is None
    for path, value in [("topform/width", "1020"), (".//defaultstring", "8")]:
        changed = deepcopy(actual)
        changed.find(path).text = value
        assert normalized_markup(expected, changed) is None


@pytest.mark.parametrize("location", ["component", "stylesheet", "opaque"])
def test_mode_normalization_does_not_escape_layout_fields(location: str) -> None:
    from copy import deepcopy

    expected = frame(1000, "framesource")
    if location == "component":
        parent = expected
    elif location == "stylesheet":
        parent = etree.SubElement(etree.SubElement(expected, "fielddefaults"), "row")
        parent.set("{http://www.w3.org/2001/XMLSchema-instance}type", "entryfield")
    else:
        parent = etree.SubElement(expected.find("topform"), "opaque")
    etree.SubElement(parent, "defaultvalue").text = "1"
    actual = deepcopy(expected)
    actual.find("topform/width").text = "1001"
    mode = actual.find(".//defaultvalue")
    mode.getparent().remove(mode)
    assert normalized_markup(expected, actual) is None


@pytest.mark.parametrize("container", ["extension", "taggedvalues"])
@pytest.mark.parametrize("shape", ["rectangleshape", "segmentshape"])
def test_shape_preparation_preserves_opaque_metadata(
    container: str, shape: str
) -> None:
    from gorak.xml_writer import prepare_submission

    root = frame(1000, "framesource")
    field = root.find("topform/childfields/row")
    field.set("{http://www.w3.org/2001/XMLSchema-instance}type", shape)
    opaque = etree.SubElement(root if container == "extension" else field, container)
    nested = etree.SubElement(opaque, "row")
    nested.set("{http://www.w3.org/2001/XMLSchema-instance}type", shape)
    etree.SubElement(nested, "name").text = "opaque_shape"
    original = etree.tostring(opaque)
    prepare_submission(root)
    assert field.findtext("width") == "0"
    if shape == "rectangleshape":
        assert field.findtext("height") == "0"
    assert etree.tostring(opaque) == original


@pytest.mark.parametrize("container", ["extension", "taggedvalues"])
@pytest.mark.parametrize("shape", ["rectangleshape", "segmentshape"])
def test_tracking_keeps_nested_opaque_shape_coordinates_exact(
    container: str, shape: str
) -> None:
    from copy import deepcopy

    from gorak.native_normalization import signature as tracking_signature

    a = frame(1000, "framesource")
    opaque = etree.SubElement(a.find("topform/childfields/row"), container)
    nested = etree.SubElement(opaque, "row")
    nested.set("{http://www.w3.org/2001/XMLSchema-instance}type", shape)
    etree.SubElement(nested, "width").text = "321"
    b = deepcopy(a)
    b.find(f".//{container}/row/width").text = "323"
    assert tracking_signature(a, pixel_geometry=True) != tracking_signature(
        b, pixel_geometry=True
    )
