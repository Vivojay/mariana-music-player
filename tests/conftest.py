import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def _append_mutmut_repository_root(root: Path = ROOT) -> None:
    """Expose root-only modules without shadowing mutmut's copied sources."""
    if "MUTANT_UNDER_TEST" not in os.environ or root.name != "mutants":
        return
    repository_root = str(root.parent)
    if repository_root not in sys.path:
        sys.path.append(repository_root)


_append_mutmut_repository_root()
os.environ.setdefault("MARIANA_RESOURCE_DIR", str(ROOT))
os.environ.setdefault("MARIANA_DATA_DIR", str(ROOT / "temp" / "pytest-runtime"))




@pytest.fixture
def fixture_dir() -> Path:
    return Path(__file__).with_name("fixtures")
