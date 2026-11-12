"""PyInstaller entry point; private modes share the bundled runtime."""

import os
import sys

if __name__ == "__main__":
    if sys.platform.startswith("linux"):
        # The bootloader prepends its private libraries for this process. Do not
        # leak that path to external Git/SSH/OpenROAD subprocesses. The current
        # dynamic loader retains its startup search path for bundled extensions.
        original = os.environ.get("LD_LIBRARY_PATH_ORIG")
        if original is None:
            os.environ.pop("LD_LIBRARY_PATH", None)
        else:
            os.environ["LD_LIBRARY_PATH"] = original
    if sys.argv[1:] == ["--_build-info"]:
        import json

        from gorak.build_info import build_info

        print(json.dumps(build_info(), sort_keys=True))
    elif sys.argv[1:] == ["--_check-bundle"]:
        from gorak.binary_resources import check_bundle

        check_bundle()
    elif sys.argv[1:2] == ["--_writer"]:
        from gorak.writer_worker import main

        raise SystemExit(main(sys.argv[2:]))
    elif sys.argv[1:2] == ["--_install"]:
        from gorak.binary_install import installer_main

        raise SystemExit(installer_main(sys.argv[2:]))
    else:
        from gorak.cli import main as cli_main

        cli_main()
