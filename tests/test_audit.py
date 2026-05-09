from lxml import etree

from gorak.audit import audit_xml, filter_missing_only, filter_reports_missing_only


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
                <procstart>fm_start</procstart>
                <short_remark>Example app</short_remark>
                <versshortremarks>Example app</versshortremarks>
                <databasename>vnode::runtime_db</databasename>
                <database_type>1</database_type>
                <included_apps />
                <long_remark>Not represented yet</long_remark>
            </APPLICATION>
        </OPENROAD>
    """)

    assert audit_xml(xml)["application"] == {
        "name": "sample_app",
        "missing_paths": ["APPLICATION[sample_app]/long_remark"],
    }


def test_audit_allows_taggedvalues_and_flags_queries_and_extension() -> None:
    xml = etree.fromstring("""
        <OPENROAD xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">
            <COMPONENT name="uc_generated" xsi:type="classsource">
                <script />
                <taggedvalues />
                <queries />
                <extension />
            </COMPONENT>
        </OPENROAD>
    """)

    assert audit_xml(xml)["components"][0]["missing_paths"] == [
        "COMPONENT[uc_generated]/queries",
        "COMPONENT[uc_generated]/extension",
    ]


def test_filter_missing_only_removes_represented_application_and_components() -> None:
    report = {
        "path": ".openroad/app/app.xml",
        "application": {"name": "app", "missing_paths": []},
        "components": [
            {"name": "fm_ok", "type": "framesource", "missing_paths": []},
            {
                "name": "fm_missing",
                "type": "framesource",
                "missing_paths": ["COMPONENT[fm_missing]/mainbarbottom"],
            },
        ],
    }

    assert filter_missing_only(report) == {
        "path": ".openroad/app/app.xml",
        "application": None,
        "components": [
            {
                "name": "fm_missing",
                "type": "framesource",
                "missing_paths": ["COMPONENT[fm_missing]/mainbarbottom"],
            }
        ],
    }


def test_filter_reports_missing_only_removes_files_with_no_missing_paths() -> None:
    assert filter_reports_missing_only(
        [
            {
                "path": ".openroad/ok/ok.xml",
                "application": None,
                "components": [],
            },
            {
                "path": ".openroad/app/app.xml",
                "application": None,
                "components": [
                    {
                        "name": "fm_missing",
                        "type": "framesource",
                        "missing_paths": ["COMPONENT[fm_missing]/mainbarbottom"],
                    }
                ],
            },
        ]
    ) == [
        {
            "path": ".openroad/app/app.xml",
            "application": None,
            "components": [
                {
                    "name": "fm_missing",
                    "type": "framesource",
                    "missing_paths": ["COMPONENT[fm_missing]/mainbarbottom"],
                }
            ],
        }
    ]
