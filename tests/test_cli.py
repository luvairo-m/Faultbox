import os
import subprocess
import sysconfig
from pathlib import Path


def test_installed_faultbox_shows_help() -> None:
    executable_name = "faultbox.exe" if os.name == "nt" else "faultbox"
    executable = Path(sysconfig.get_path("scripts")) / executable_name

    result = subprocess.run(
        [str(executable), "--help"],
        capture_output=True,
        text=True,
        check=True,
        timeout=10,
    )

    assert "faultbox" in result.stdout
    assert "--help" in result.stdout
