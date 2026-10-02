"""Build historical compressed fixtures to test migration and legacy overlays."""

from pathlib import Path

from lxml import etree

from gorak.domain import Component
from gorak.field_defaults import diff_defaults, effective_defaults
from gorak.parser import FRAME_MARKUP_CHILDREN, encode_frame_markup
from gorak.project import read_json, write_json


def apply_field_default_inheritance(
    root: Path,
    app: str,
    components: list[Component],
    *,
    source_nodes: list[etree._Element] | None = None,
) -> None:
    """Factor defaults and reproject authoritative markup against the saved palette."""

    native = {node.get("name"): node for node in source_nodes or []}

    repo_path = root / "field_defaults.json"
    app_path = root / app / "field_defaults.json"
    repo_defaults = read_json(repo_path) if repo_path.is_file() else None
    app_defaults = read_json(app_path) if app_path.is_file() else None

    for component in components:
        props = component.props
        frame_defaults = props.pop("fielddefaults", None)
        if not isinstance(frame_defaults, dict):
            continue

        if repo_defaults is None:
            repo_defaults = frame_defaults
            write_json(repo_path, repo_defaults)

        if app_defaults is None:
            app_defaults = diff_defaults(repo_defaults, frame_defaults)
            app_path.parent.mkdir(parents=True, exist_ok=True)
            write_json(app_path, app_defaults)

        parent_defaults = effective_defaults(repo_defaults, app_defaults, {})
        frame_override = diff_defaults(parent_defaults, frame_defaults)
        if frame_override:
            props["fielddefaults"] = frame_override
        if component.markup is not None and component.name in native:
            # Inheritance can retain extra styles or change their ordinals. The
            # first projection used only the native frame palette, so its omitted
            # values and selectors must be reconsidered before saving the WML.
            defaults = effective_defaults(parent_defaults, {}, frame_override)
            if defaults == frame_defaults:
                continue
            component.markup = encode_frame_markup(
                [
                    child
                    for child in native[component.name]
                    if child.tag in FRAME_MARKUP_CHILDREN
                ],
                defaults,
            )
