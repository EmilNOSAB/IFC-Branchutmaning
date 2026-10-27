import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from common.config import load_config  # noqa: E402
from geometry.landxml_reader import read_landxml  # noqa: E402


@pytest.fixture(scope="session")
def cfg():
    return load_config(mode="full")


@pytest.fixture(scope="session")
def landxml(cfg):
    return read_landxml(cfg.file("landxml"))


@pytest.fixture(scope="session")
def design_full():
    from model.railway_model import RailwayModelBuilder
    b = RailwayModelBuilder(load_config(mode="full"))
    return b, b.build()


@pytest.fixture(scope="session")
def design_preview():
    from model.railway_model import RailwayModelBuilder
    b = RailwayModelBuilder(load_config(mode="preview"))
    return b, b.build()
