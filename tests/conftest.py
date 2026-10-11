import os
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent

# The suite imports and runs the hook scripts under plugins/. Never leave
# bytecode there: plugins/ is packed into the npm mirror, and
# scripts/validate-npm-package.sh rejects any packed file git does not track.
sys.dont_write_bytecode = True
os.environ["PYTHONDONTWRITEBYTECODE"] = "1"


@pytest.fixture
def repo_root() -> Path:
    return REPO_ROOT
