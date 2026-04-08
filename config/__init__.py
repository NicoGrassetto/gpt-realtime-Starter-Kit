"""Config-driven session mode loader.

Usage:
    from config import load_session_config

    cfg = load_session_config("voice_assistant")
    # Returns a dict ready to be used as the `session` payload in session.update
"""

from __future__ import annotations

import copy
import pathlib
from typing import Any

import yaml

_CONFIG_DIR = pathlib.Path(__file__).parent
_MODES_DIR = _CONFIG_DIR / "modes"

_defaults: dict[str, Any] | None = None


def _load_defaults() -> dict[str, Any]:
    global _defaults
    if _defaults is None:
        with open(_CONFIG_DIR / "session_defaults.yaml", encoding="utf-8") as f:
            _defaults = yaml.safe_load(f) or {}
    return _defaults


def _deep_merge(base: dict, override: dict) -> dict:
    """Recursively merge *override* into a copy of *base*."""
    result = copy.deepcopy(base)
    for key, value in override.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = copy.deepcopy(value)
    return result


def list_modes() -> list[str]:
    """Return names of all available mode presets."""
    return sorted(p.stem for p in _MODES_DIR.glob("*.yaml"))


def load_session_config(mode: str = "voice_assistant") -> dict[str, Any]:
    """Load a session config by merging defaults with the named mode.

    Returns a dict suitable for ``{"type": "session.update", "session": <result>}``.
    """
    defaults = _load_defaults()

    mode_file = _MODES_DIR / f"{mode}.yaml"
    if not mode_file.exists():
        raise FileNotFoundError(
            f"Unknown mode '{mode}'. Available: {list_modes()}"
        )

    with open(mode_file, encoding="utf-8") as f:
        mode_cfg = yaml.safe_load(f) or {}

    session = mode_cfg.get("session", {})
    merged = _deep_merge(defaults.get("session", {}), session)
    return merged
