"""Exercise a built artifact outside the checkout, without services or Python on PATH."""

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import tempfile
from pathlib import Path


def smoke(binary: Path) -> None:
    fixture = (
        Path(__file__).resolve().parents[1] / "tests/fixtures/fm_example_frame.xml"
    )
    if os.name == "nt":
        # Parse both PowerShell entry points without executing downloads or elevation.
        script_root = Path(__file__).resolve().parents[1]
        for script in (
            script_root / "scripts/install.ps1",
            script_root / "src/gorak/install_scripts/system-update.ps1",
        ):
            subprocess.run(
                [
                    "powershell.exe",
                    "-NoProfile",
                    "-Command",
                    "$errors = $null; $tokens = $null; [System.Management.Automation.Language.Parser]::ParseFile($env:GORAK_PARSE_SCRIPT, [ref]$tokens, [ref]$errors) | Out-Null; if ($errors.Count) { $errors | Out-String | Write-Error; exit 1 }",
                ],
                env={**os.environ, "GORAK_PARSE_SCRIPT": str(script)},
                check=True,
            )
    with tempfile.TemporaryDirectory(prefix="gorak-binary-smoke-") as temporary:
        root = Path(temporary)
        portable = root / (
            "portable gorak.exe" if os.name == "nt" else "portable gorak"
        )
        shutil.copy2(binary, portable)
        env = {
            key: value
            for key, value in os.environ.items()
            if not key.startswith(("GORAK_", "PYTHON", "OR_UNITTEST_"))
        }
        env["PATH"] = (
            os.path.join(env.get("SystemRoot", r"C:\Windows"), "System32")
            if os.name == "nt"
            else "/nonexistent"
        )

        def run(executable: Path, *args: str, expected: int = 0) -> str:
            completed = subprocess.run(
                [str(executable), *args],
                cwd=root,
                env=env,
                capture_output=True,
                text=True,
                timeout=90,
            )
            if completed.returncode != expected:
                raise AssertionError(f"{args}: {completed.stdout}\n{completed.stderr}")
            return completed.stdout + completed.stderr

        identity = run(portable, "--version").strip()
        assert identity.startswith("gorak ")
        assert json.loads(run(portable, "--_build-info"))["tag"].startswith("v")
        assert "resources OK" in run(portable, "--_check-bundle")
        assert "--self-update" in run(portable, "--help")
        assert "manually" in run(portable, "--self-update", expected=1)
        run(portable, "new", "--nogit", "example")
        assert (root / "example/AGENTS.md").is_file()
        assert (root / "example/field_defaults.json").is_file()
        if os.name != "nt":
            # A synthetic Git command verifies that the bundle's library path
            # does not leak into external programs; no real Git is invoked.
            commands = root / "fake-bin"
            commands.mkdir()
            git = commands / "git"
            git.write_text(
                '#!/bin/sh\nprintf "%s" "${LD_LIBRARY_PATH-}" > "$GORAK_SMOKE_PATH_LOG"\n'
            )
            git.chmod(0o700)
            saved = dict(env)
            env.update(
                {
                    "PATH": str(commands),
                    "LD_LIBRARY_PATH": "/nonexistent-original",
                    "GORAK_SMOKE_PATH_LOG": str(root / "loader-path.txt"),
                }
            )
            run(portable, "new", "with-git")
            assert (root / "loader-path.txt").read_text() == "/nonexistent-original"
            env.clear()
            env.update(saved)
        run(portable, "encode", str(fixture), "--output", str(root / "frame.w4gl"))
        assert "[framesource]" in (root / "frame.w4gl").read_text()
        assert "--database" in run(portable, "--_writer", "--help")
        with portable.open("rb") as stream:
            digest = hashlib.file_digest(stream, "sha256").hexdigest()
        installation = root / "managed installation"
        run(portable, "--_install", "--root", str(installation), "--sha256", digest)
        installed = installation / "bin" / ("gorak.exe" if os.name == "nt" else "gorak")
        assert run(installed, "--version").strip() == identity
        assert (
            json.loads((installation / "installation.json").read_text())["sha256"]
            == digest
        )
        # Repeat replacement through staging, including the previous-copy path.
        run(portable, "--_install", "--root", str(installation), "--sha256", digest)
        assert (
            installed.with_name(installed.name + ".previous").read_bytes()
            == portable.read_bytes()
        )
        assert run(installed, "--version").strip() == identity
        assert "checksum" in run(
            portable,
            "--_install",
            "--root",
            str(installation),
            "--sha256",
            "0" * 64,
            expected=1,
        )
        assert run(installed, "--version").strip() == identity
        print(
            f"PASS: {identity}: portable, resources, XML conversion, writer dispatch, managed install, replacement, checksum refusal"
        )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("binary", type=Path)
    smoke(parser.parse_args().binary.resolve())
