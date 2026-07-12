import os
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
os.environ.setdefault("MARIANA_RESOURCE_DIR", str(ROOT))
os.environ.setdefault("MARIANA_DATA_DIR", str(ROOT / "temp" / "pytest-runtime"))




@pytest.fixture
def fixture_dir() -> Path:
    return Path(__file__).with_name("fixtures")
