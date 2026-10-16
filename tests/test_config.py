from pathlib import Path

import pytest
from pydantic import ValidationError

from bff.config import Settings, private_file


@pytest.mark.parametrize(
    "origin",
    [
        "http://workspace.test",
        "https://workspace.test/",
        "https://user:pass@workspace.test",
        "https://workspace.test/path",
        "https://workspace.test:bad",
        "https://workspace.test\n",
    ],
)
def test_reject_unsafe_origin(settings, origin):
    with pytest.raises((ValueError, ValidationError)):
        Settings(**{**settings.model_dump(), "origin": origin})


def test_secret_permissions_and_symlink(tmp_path):
    path = tmp_path / "private"
    path.write_text("synthetic")
    path.chmod(0o644)
    with pytest.raises(ValueError):
        private_file(path)
    path.chmod(0o600)
    link = tmp_path / "link"
    link.symlink_to(path)
    with pytest.raises(OSError):
        private_file(link)
    with pytest.raises(ValueError):
        private_file(Path("relative"))
