"""Import inventory validates trailing XML without materializing applications."""

from pathlib import Path

import pytest
from lxml import etree

from gorak.project import ProjectError
from gorak.source_xml import contains_components, read_tree


@pytest.mark.parametrize(
    "xml",
    [
        "<OPENROAD/>",
        "<OPENROAD><APPLICATION/><COMPONENT/><COMPONENT/></OPENROAD>",
        "<OPENROAD><extension><COMPONENT/></extension></OPENROAD>",
        "<OPENROAD><!-- comment --><APPLICATION/></OPENROAD>",
    ],
)
def test_streamed_component_presence_matches_full_parser(
    tmp_path: Path, xml: str
) -> None:
    path = tmp_path / "application.xml"
    path.write_text(xml)
    assert contains_components(path) == bool(read_tree(path).findall("COMPONENT"))


@pytest.mark.parametrize(
    "xml",
    [
        "<OPENROAD><COMPONENT/><broken></OPENROAD>",
        "<!DOCTYPE OPENROAD><OPENROAD><COMPONENT/></OPENROAD>",
        "<OPENROAD><COMPONENT/>" + "<deep>" * 256 + "</deep>" * 256 + "</OPENROAD>",
    ],
)
def test_validation_does_not_stop_after_first_component(
    tmp_path: Path, xml: str
) -> None:
    path = tmp_path / "application.xml"
    path.write_text(xml)
    with pytest.raises((ProjectError, etree.XMLSyntaxError)):
        contains_components(path)
