"""Auto-discover tool modules and expose the registry.

Importing this package scans all .py files in tools/ (except __init__ and
registry), which triggers their @tool decorators to register functions.

Usage:
    from tools import get_tool_schemas, execute_tool, execute_tool_async
"""

from __future__ import annotations

import importlib
import pathlib

from tools.registry import registry

# Auto-discover: import every .py sibling so @tool decorators run
_package_dir = pathlib.Path(__file__).parent
for _file in sorted(_package_dir.glob("*.py")):
    if _file.stem in ("__init__", "registry"):
        continue
    importlib.import_module(f"tools.{_file.stem}")


def get_tool_schemas() -> list[dict]:
    """JSON schemas for session.update `tools` array."""
    return registry.get_schemas()


def execute_tool(name: str, arguments) -> object:
    """Synchronously execute a registered tool."""
    return registry.execute(name, arguments)


async def execute_tool_async(name: str, arguments) -> object:
    """Execute a registered tool (awaits if async)."""
    return await registry.execute_async(name, arguments)
