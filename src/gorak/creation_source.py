"""Prepare new applications from verified readable inputs with bounded XML memory."""

from collections.abc import Mapping
from pathlib import Path

from lxml import etree

from . import comparison_inputs
from .operation_progress import report
from .parser import NS
from .portable_source import restore_application, restore_component
from .project import ProjectError
from .source_xml import MAX_DOCUMENT_BYTES, from_bytes
from .xml_writer import document, prepare_submission


def prepare_application(
    root: Path,
    folder: Path,
    sources: list[Path],
    destination: Path,
    proof: Mapping[str, str],
) -> tuple[set[str], list[tuple[str, str]]]:
    """Retain exactly the input bytes verified against the push's initial snapshot."""
    comparison_inputs.set_proof(root, proof)
    manifest = folder / "app.json"
    with comparison_inputs.capture(root, manifest, application=True):
        application = restore_application(
            comparison_inputs.path_for_read(manifest).parent
        )
    dependencies = {
        row.findtext("appname", "").casefold()
        for row in application.findall("included_apps/row")
        if not row.findtext("imgfilename")
    }
    targets: list[tuple[str, str]] = []
    with etree.xmlfile(str(destination), encoding="UTF-8") as output:
        output.write_declaration()
        with output.element("OPENROAD", nsmap=NS):
            # Match the old document parse (including XML newline normalization)
            # without keeping all the application's components alive together.
            output.write(from_bytes(document([application]))[0])
            report(f"Preparing upload: {folder.name}", 0, len(sources))
            for index, source in enumerate(sources, 1):
                with comparison_inputs.capture(root, source):
                    component = restore_component(
                        comparison_inputs.path_for_read(source)
                    )
                payload = from_bytes(document([component]))
                prepare_submission(payload)
                output.write(payload[0])
                targets.append((folder.name, str(payload[0].get("name"))))
                report(f"Preparing upload: {folder.name}", index, len(sources))
                del component, payload
    if destination.stat().st_size > MAX_DOCUMENT_BYTES:
        raise ProjectError("Source XML exceeds the 512 MiB document limit")
    return dependencies, targets
