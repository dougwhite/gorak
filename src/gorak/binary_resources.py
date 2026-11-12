"""Offline validation of resources that static freezing cannot infer."""

import tempfile
from importlib.resources import files
from pathlib import Path
from zipfile import ZipFile

from sqlalchemy.dialects import registry

from .cli import remote_script_resources
from .comparison_cache import implementation_key
from .writer_launch import build_writer_archive


def check_bundle() -> None:
    """Private build smoke check; never contact SSH, ODBC or OpenROAD."""
    for resource in remote_script_resources():
        if not resource.read_bytes():
            raise ValueError(f"Empty packaged helper: {resource.name}")
    if not files("gorak").joinpath("install_scripts/system-update.ps1").read_bytes():
        raise ValueError("Missing protected system updater")
    for name in (
        "AGENTS.md",
        "field_defaults.json",
        "native_styles.json",
        "xml_shapes.json",
        "xml_bases.json",
        "builtin_images.json",
    ):
        if not files("gorak.templates").joinpath(name).read_bytes():
            raise ValueError(f"Empty packaged template: {name}")
    # Loading the SQLAlchemy plugin is offline and must not import native ODBC.
    registry.load("ingres.pyodbc")
    implementation_key()
    with tempfile.TemporaryDirectory(prefix="gorak-bundle-check-") as temporary:
        archive = Path(temporary) / "writer.pyz"
        build_writer_archive(archive)
        with ZipFile(archive) as bundle:
            if "gorak/writer_settings.py" not in bundle.namelist():
                raise ValueError("Missing writer source")
    print("gorak bundle resources OK")
