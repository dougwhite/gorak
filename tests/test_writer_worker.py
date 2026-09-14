import json
import os
import subprocess
from pathlib import Path

import pytest

from gorak.writer_launch import build_writer_archive
from tests.test_writer_launch import interpreter


@pytest.mark.skipif(os.name == "nt", reason="POSIX fake executable fixture")
def test_packaged_worker_preserves_startup_and_exit_code(tmp_path: Path) -> None:
    archive = tmp_path / "worker.pyz"
    build_writer_archive(archive)
    base = tmp_path / "installation"
    binary = base / "ingres/bin/w4gldev"
    binary.parent.mkdir(parents=True)
    binary.write_text("""#!/usr/bin/python3
import os,json
from pathlib import Path
path=Path(os.environ['ING_SET_SOURCE'][8:])
print(json.dumps({'path':str(path),'sql':path.read_text(),'general':os.environ['ING_SET']}))
raise SystemExit(7)
""")
    binary.chmod(0o755)
    env = dict(
        os.environ,
        II_SYSTEM=str(base),
        ING_SET_SOURCE="set lockmode session where timeout=17",
        ING_SET="preserve general",
    )
    result = subprocess.run(
        [
            str(interpreter(tmp_path)),
            str(archive),
            "--database",
            "source",
            "--encoding",
            "ascii",
            "--",
            "rundbapp",
            "source",
            "app",
        ],
        env=env,
        text=True,
        capture_output=True,
    )
    assert result.returncode == 7
    report = json.loads(result.stdout)
    assert "timeout=17" in report["sql"] and "level=mvcc" in report["sql"]
    assert report["general"] == "preserve general"
    assert not Path(report["path"]).exists()
    assert env["ING_SET_SOURCE"] == "set lockmode session where timeout=17"


def test_worker_failure_does_not_echo_sensitive_settings(tmp_path: Path) -> None:
    archive = tmp_path / "worker.pyz"
    build_writer_archive(archive)
    env = dict(os.environ, II_SYSTEM=str(tmp_path), ING_SET_SOURCE="sensitive")
    result = subprocess.run(
        [
            str(interpreter(tmp_path)),
            str(archive),
            "--database",
            "source",
            "--encoding",
            "ascii",
            "--",
            "rundbapp",
            "source",
            "app",
        ],
        env=env,
        text=True,
        capture_output=True,
    )
    assert result.returncode == 1 and "sensitive" not in result.stderr
