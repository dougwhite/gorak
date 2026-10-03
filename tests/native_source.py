"""Write native synthetic fixtures through the current public source contract."""

from pathlib import Path

from lxml import etree

from gorak.component_defaults import encode_source_w4gl, write_component_defaults
from gorak.export import apply_field_default_inheritance
from gorak.parser import parse_component_node


def write_component(path: Path, node: etree._Element) -> None:
    component = parse_component_node(node)
    apply_field_default_inheritance(
        path.parent.parent, path.parent.name, [component], source_nodes=[node]
    )
    path.write_text(encode_source_w4gl(component))
    if component.markup is not None:
        path.with_suffix(".wml").write_text(component.markup)
        write_component_defaults(path, component.props["fielddefaults"])
