"""Helper functions for our test cases"""

from textwrap import dedent

from lxml import etree


def _wrap_xml(content: str) -> etree._Element:
    """Wraps inner XML content in standard OpenROAD boilerplate."""
    xml = dedent(
        """<OPENROAD xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">
           {content}
           </OPENROAD>"""
    ).format(content=dedent(content).strip())  # Use .format for clean embedding
    return etree.fromstring(xml)