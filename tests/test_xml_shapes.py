import pytest
from lxml import etree

from gorak.errors import ProjectError
from gorak.xml_shapes import derives, order_children, set_scalar


def test_new_properties_follow_inherited_protocol_order() -> None:
    node = etree.fromstring(b"<row><width>1000</width><height>250</height></row>")
    set_scalar(node, "entryfield", "name", "input")
    set_scalar(node, "entryfield", "xleft", "100")
    assert [n.tag for n in node] == ["name", "xleft", "width", "height"]
    assert derives("entryfield", "formfield")
    assert not derives("classsource", "formfield")


def test_unknown_structured_properties_are_not_flattened() -> None:
    node = etree.fromstring(b"<COMPONENT><extension><opaque/></extension></COMPONENT>")
    with pytest.raises(ProjectError):
        set_scalar(node, "classsource", "extension", "replacement")
    assert node.find("extension/opaque") is not None
    node.append(etree.Element("unknown"))
    with pytest.raises(ProjectError):
        order_children(node, "classsource")
