"""Prompt loader — reads .prompty files and extracts the system block.

Usage:
    from prompts import load_prompt, list_prompts

    text = load_prompt("default")
    text = load_prompt("transcriber")
"""

from __future__ import annotations

import pathlib
import re

_PROMPTS_DIR = pathlib.Path(__file__).parent


def list_prompts() -> list[str]:
    """Return names (stems) of all available .prompty files."""
    return sorted(p.stem for p in _PROMPTS_DIR.glob("*.prompty"))


def load_prompt(name: str = "default") -> str:
    """Load a .prompty file and return the system prompt text.

    Extracts everything after ``system:`` up to the next role marker or EOF.
    """
    path = _PROMPTS_DIR / f"{name}.prompty"
    if not path.exists():
        raise FileNotFoundError(
            f"Unknown prompt '{name}'. Available: {list_prompts()}"
        )

    text = path.read_text(encoding="utf-8")
    match = re.search(
        r"^system:\s*\n(.+?)(?:\n(?:user|assistant):|\Z)",
        text,
        re.DOTALL | re.MULTILINE,
    )
    if match:
        return match.group(1).strip()

    # Fallback: return everything after the YAML frontmatter
    parts = text.split("---", 2)
    if len(parts) >= 3:
        return parts[2].strip()

    return text.strip()
