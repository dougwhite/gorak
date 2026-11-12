# PyInstaller specification. Run through scripts/build_binary.py.
import json
import os
from pathlib import Path

from PyInstaller.utils.hooks import collect_all, collect_data_files, collect_submodules

root = Path(SPECPATH).parent
work = Path(os.environ["GORAK_BINARY_WORK"])
info = json.loads((work / "binary-build.json").read_text())
name = "gorak-" + info["platform"]
datas = collect_data_files("gorak")
for source in sorted((root / "src" / "gorak").rglob("*.py")):
    destination = Path("gorak") / source.parent.relative_to(root / "src" / "gorak")
    datas.append((str(source), destination.as_posix()))
datas.extend(
    [(str(work / "binary-build.json"), "gorak"), (str(root / "LICENSE"), "gorak")]
)
ingres_data, ingres_binaries, ingres_imports = collect_all("sqlalchemy_ingres")
a = Analysis(
    [str(root / "scripts" / "binary_entry.py")],
    pathex=[str(root / "src")],
    binaries=ingres_binaries,
    datas=datas + ingres_data,
    hiddenimports=collect_submodules("gorak") + ingres_imports + ["pyodbc"],
    hookspath=[],
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
)
# importlib.metadata hooks can discover editable-install metadata independently
# of explicit collection. Strip local installation URLs from the final TOC.
a.datas = [
    entry
    for entry in a.datas
    if not entry[0].replace("\\", "/").endswith("/direct_url.json")
]
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name=name,
    debug=False,
    strip=False,
    upx=False,
    console=True,
)
