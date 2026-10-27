import os

import pytest

from common import miniyaml
from common.config import REPO_ROOT

FILES = ["model_config.yaml", "object_mapping.yaml", "levels.yaml"]


@pytest.mark.parametrize("name", FILES)
def test_miniyaml_equals_pyyaml(name):
    yaml = pytest.importorskip("yaml")
    text = open(os.path.join(REPO_ROOT, "config", name), encoding="utf-8").read()
    assert miniyaml.loads(text) == yaml.safe_load(text)


def test_miniyaml_subset():
    doc = miniyaml.loads("""
a: 1
b: [1, 2.5, x, 'q: r', [3, 4]]
c:
  - k: v
    n: 60E1
  - plain
d: {x: true, y: null}
e: "say \\"hi\\""   # comment
""")
    assert doc == {"a": 1, "b": [1, 2.5, "x", "q: r", [3, 4]], "c": [{"k": "v", "n": "60E1"}, "plain"],
                   "d": {"x": True, "y": None}, "e": 'say "hi"'}
