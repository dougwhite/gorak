"""Current readable reconstruction and native baselines for verified comparisons."""

from copy import deepcopy
from pathlib import Path

from lxml import etree

from .project import ProjectError


def read_document(path: Path) -> etree._Element:
    parser = etree.XMLParser(resolve_entities=False, no_network=True, strip_cdata=False)
    tree = etree.parse(str(path), parser)
    if tree.docinfo.doctype:
        raise ProjectError(f"Source XML must not contain a document type: {path}")
    return tree.getroot()


def cached_node(folder: Path, tag: str, name: str) -> etree._Element | None:
    """Read an older checkout baseline without mistaking exported source for new source."""
    cache = folder.parent / ".openroad" / folder.name
    files = sorted(
        cache.glob("*.xml"), key=lambda p: p.stat().st_mtime_ns, reverse=True
    )
    for path in files:
        root = read_document(path)
        matches = [
            n
            for n in root.findall(tag)
            if n.get("name", "").casefold() == name.casefold()
        ]
        if len(matches) > 1:
            raise ProjectError(f"Ambiguous cached source: {path}")
        if matches:
            return matches[0]
        # A newer full export authoritatively records component absence.
        if tag == "COMPONENT" and root.find("APPLICATION") is not None:
            return None
    return None


def overlay_component(node: etree._Element, path: Path) -> etree._Element:
    """Reconstruct edited source; preserve native serialization on a verified no-op."""
    from .component_edits import overlay_metadata
    from .contract_source import decode_component, equivalent
    from .parser import FRAME_COMPONENT_TYPES, NS

    if node.get(f"{{{NS['xsi']}}}type") not in FRAME_COMPONENT_TYPES:
        overlay_metadata(node, path)
        return node
    replacement = decode_component(path)
    from .query_metadata import overlay_queries

    # Enforce missing-sidecar protection against the authoritative baseline.
    overlay_queries(deepcopy(node), path)
    if equivalent(replacement, node):
        return node
    node.attrib.clear()
    node.attrib.update(replacement.attrib)
    node.text = replacement.text
    node[:] = list(replacement)
    return node


def restore_component(path: Path) -> etree._Element:
    """Reconstruct only from versioned readable files, never cached XML."""
    from .xml_writer import new_component

    return new_component(path)


def restore_application(folder: Path) -> etree._Element:
    """Reconstruct application metadata without cache or companion lookup."""
    from .xml_writer import new_application

    return new_application(folder)


def comparison_component(path: Path) -> etree._Element:
    """Preserve unrepresented baseline details for three-way comparison only."""
    baseline = cached_node(path.parent, "COMPONENT", path.stem)
    if baseline is not None:
        return overlay_component(deepcopy(baseline), path)
    return restore_component(path)


def comparison_application(folder: Path) -> etree._Element:
    from .parser import parse_application_xml
    from .xml_writer import document

    desired = restore_application(folder)
    baseline = cached_node(folder, "APPLICATION", folder.name)
    if baseline is None:
        return desired
    old = parse_application_xml(etree.fromstring(document([baseline])))
    new = parse_application_xml(etree.fromstring(document([desired])))
    if (
        old.application == new.application
        and old.included_applications == new.included_applications
    ):
        return baseline
    managed = {
        "versshortremarks",
        "included_apps",
        "procstart",
        "databasename",
        "database_type",
    }
    for child in list(baseline):
        if child.tag in managed:
            baseline.remove(child)
    baseline.extend(desired)
    order = [
        "versshortremarks",
        "extension",
        "taggedvalues",
        "included_apps",
        "procstart",
        "databasename",
        "database_type",
        "commandline",
        "windowicon",
        "globalsfile",
        "appflags",
    ]
    baseline[:] = sorted(baseline, key=lambda child: order.index(str(child.tag)))
    return baseline
