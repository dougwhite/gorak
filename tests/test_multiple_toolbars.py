"""Every native toolbar row survives readable source and fidelity checks."""

from copy import deepcopy
from pathlib import Path

import pytest
from lxml import etree

from gorak.component_defaults import encode_source_w4gl
from gorak.contract_source import decode_component, equivalent
from gorak.errors import ProjectError
from gorak.parser import (
    MAINBAR_MARKUP_CHILDREN,
    NS,
    encode_frame_markup,
    parse_component_node,
)
from gorak.wml_writer import parse_markup


@pytest.mark.parametrize("kind", ["framesource", "frametemplate"])
@pytest.mark.parametrize("side", sorted(MAINBAR_MARKUP_CHILDREN))
def test_multiple_toolbars(tmp_path: Path, kind: str, side: str) -> None:
    native = etree.fromstring(
        f'<COMPONENT xmlns:xsi="{NS["xsi"]}" name="example" xsi:type="{kind}">'
        "<topform/>"
        f"<{side}>"
        + "".join(
            f"<row><name>bar{i}</name><childfields>"
            f'<row xsi:type="buttonfield"><name>go{i}</name>'
            f"<textlabel>Button {i}</textlabel><script>ON CLICK = {{ return {i}; }}</script>"
            "</row><row_class>formfield</row_class></childfields></row>"
            for i in range(3)
        )
        + f"<row_class>mainbar</row_class></{side}></COMPONENT>"
    )
    component = parse_component_node(native)
    path = tmp_path / "example.w4gl"
    path.write_text(encode_source_w4gl(component))
    path.with_suffix(".fielddefaults.json").write_text('{"absent": true}')
    wml = encode_frame_markup(
        [native.find("topform"), native.find(side)], explicit=True
    )
    path.with_suffix(".wml").write_text(wml)
    markup = parse_markup(wml)
    assert [bar.get("name") for bar in markup.findall(side)] == ["bar0", "bar1", "bar2"]
    restored = decode_component(path)
    assert len(restored.findall(side)) == 1
    assert len(restored.findall(f"{side}/row")) == 3
    assert (
        restored.findtext(f"{side}/row[3]/childfields/row/script")
        == "ON CLICK = { return 2; }"
    )
    assert equivalent(native, restored)
    assert parse_component_node(restored).markup == component.markup

    for mutation in ("drop", "edit", "reorder"):
        changed = deepcopy(native)
        bar = changed.find(side)
        assert bar is not None
        if mutation == "drop":
            bar.remove(bar.findall("row")[1])
        elif mutation == "edit":
            bar.find("row[2]/childfields/row/textlabel").text = "Changed"
        else:
            bar.insert(0, bar.findall("row")[1])
        assert not equivalent(native, changed)
        assert not equivalent(native, changed, exact_styles=False)


def test_other_frame_sections_still_unique(tmp_path: Path) -> None:
    path = tmp_path / "example.w4gl"
    path.write_text("[framesource]\n")
    path.with_suffix(".wml").write_text("<frame><topform/><topform/></frame>")
    with pytest.raises(ProjectError, match="duplicate frame section"):
        decode_component(path)


def test_empty_toolbar_collection() -> None:
    assert (
        parse_markup(encode_frame_markup([etree.fromstring("<mainbartop/>")])).find(
            "mainbartop"
        )
        is None
    )
