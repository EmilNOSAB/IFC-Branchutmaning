"""DGN level structure from config/levels.yaml (idempotent: existing levels are reused)."""

from __future__ import annotations

from typing import Dict


def create_levels(backend, levels_cfg: Dict) -> Dict[str, int]:
    return backend.ensure_levels(levels_cfg["levels"])
