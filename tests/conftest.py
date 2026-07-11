import os
from pathlib import Path

import pytest


os.environ.setdefault("SDL_AUDIODRIVER", "dummy")
os.environ.setdefault("PYGAME_HIDE_SUPPORT_PROMPT", "hide")


@pytest.fixture
def fixture_dir() -> Path:
    return Path(__file__).with_name("fixtures")
