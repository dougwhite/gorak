from lxml import etree

from gorak.audit import audit_xml


def test_audit_reports_unsupported_nested_component_children() -> None:
    xml = etree.fromstring("""
        <OPENROAD xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">
            <COMPONENT name="fm_test" xsi:type="framesource">
                <script>initialize()={}</script>
                <topform />
                <unsupported>
                    <child />
                </unsupported>
            </COMPONENT>
        </OPENROAD>
    """)

    assert audit_xml(xml)["components"] == [
        {
            "name": "fm_test",
            "type": "framesource",
            "missing_paths": ["COMPONENT[fm_test]/unsupported"],
        }
    ]


def test_audit_allows_supported_frame_subtrees() -> None:
    xml = etree.fromstring("""
        <OPENROAD xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">
            <COMPONENT name="fm_test" xsi:type="framesource">
                <script>initialize()={}</script>
                <startmenu>
                    <childmenufields />
                </startmenu>
                <topform>
                    <childfields />
                </topform>
                <fielddefaults />
            </COMPONENT>
        </OPENROAD>
    """)

    assert audit_xml(xml)["components"][0]["missing_paths"] == []


def test_audit_reports_unsupported_application_metadata() -> None:
    xml = etree.fromstring("""
        <OPENROAD>
            <APPLICATION name="sample_app">
                <proc_start>fm_start</proc_start>
                <short_remark>Example app</short_remark>
                <included_apps />
                <long_remark>Not represented yet</long_remark>
            </APPLICATION>
        </OPENROAD>
    """)

    assert audit_xml(xml)["application"] == {
        "name": "sample_app",
        "missing_paths": ["APPLICATION[sample_app]/long_remark"],
    }
