import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

DATA = Path(__file__).resolve().parent / "data"


@pytest.fixture(scope="session")
def data_dir() -> Path:
    return DATA


@pytest.fixture(scope="session")
def att_ess_csv() -> Path:
    return DATA / "ATT-ESS-example.csv"


@pytest.fixture(scope="session")
def combined_federal_csv() -> Path:
    return DATA / "Combined-Federal_example.csv"


@pytest.fixture(scope="session")
def combined_state_csv() -> Path:
    return DATA / "Combined-State_example.csv"


@pytest.fixture(scope="session")
def tnu_starter_csv() -> Path:
    return DATA / "TNU Starter example.csv"
