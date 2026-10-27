"""Configuration loading shared by all steps."""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any, Dict, Optional

from . import miniyaml

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def repo_path(path: str) -> str:
    if not path:
        return path
    if os.path.isabs(path):
        return path
    return os.path.normpath(os.path.join(REPO_ROOT, path))


@dataclass
class Config:
    model: Dict[str, Any]
    mapping: Dict[str, Any]
    levels: Dict[str, Any]
    mode: str

    @property
    def mode_settings(self) -> Dict[str, Any]:
        return self.model["modes"][self.mode]

    def file(self, key: str) -> str:
        return repo_path(self.model["files"][key])

    def category(self, name: str) -> Dict[str, Any]:
        try:
            return self.mapping["categories"][name]
        except KeyError:
            raise KeyError("Category %r is missing in config/object_mapping.yaml" % name)


def load_config(model_config: Optional[str] = None, mode: Optional[str] = None) -> Config:
    cfg_dir = os.path.join(REPO_ROOT, "config")
    model = miniyaml.load(model_config or os.path.join(cfg_dir, "model_config.yaml"))
    mapping = miniyaml.load(os.path.join(cfg_dir, "object_mapping.yaml"))
    levels = miniyaml.load(os.path.join(cfg_dir, "levels.yaml"))
    m = mode or model.get("mode", "full")
    if m not in model["modes"]:
        raise ValueError("Unknown mode %r (expected one of %s)" % (m, list(model["modes"])))
    return Config(model=model, mapping=mapping, levels=levels, mode=m)
