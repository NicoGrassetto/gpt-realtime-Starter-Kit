"""Tool decorator and registry for Realtime API function calling.

Usage:
    from tools.registry import tool, registry

    @tool(description="Get current weather")
    def get_weather(city: str, units: str = "celsius") -> dict:
        return {"temp": 22}

    # At startup
    schemas = registry.get_schemas()       # list[dict] for session.update tools[]
    result  = registry.execute("get_weather", {"city": "Paris"})
"""

from __future__ import annotations

import inspect
import json
from typing import Any, Callable, get_type_hints

# JSON-schema type mapping from Python types
_TYPE_MAP: dict[type, str] = {
    str: "string",
    int: "integer",
    float: "number",
    bool: "boolean",
    list: "array",
    dict: "object",
}


class ToolRegistry:
    """Collects @tool-decorated functions and generates JSON schemas."""

    def __init__(self) -> None:
        self._tools: dict[str, _RegisteredTool] = {}

    def register(
        self,
        fn: Callable,
        *,
        name: str | None = None,
        description: str | None = None,
    ) -> Callable:
        tool_name = name or fn.__name__
        tool_desc = description or fn.__doc__ or ""
        self._tools[tool_name] = _RegisteredTool(
            fn=fn,
            name=tool_name,
            description=tool_desc.strip(),
            schema=_build_schema(fn, tool_name, tool_desc.strip()),
        )
        return fn

    def get_schemas(self) -> list[dict[str, Any]]:
        """Return tool definitions for session.update `tools` array."""
        return [t.schema for t in self._tools.values()]

    def execute(self, name: str, arguments: dict[str, Any] | str) -> Any:
        """Run a registered tool by name. *arguments* can be a dict or JSON string."""
        if name not in self._tools:
            raise KeyError(f"Unknown tool: {name}. Available: {list(self._tools)}")
        if isinstance(arguments, str):
            arguments = json.loads(arguments)
        return self._tools[name].fn(**arguments)

    async def execute_async(self, name: str, arguments: dict[str, Any] | str) -> Any:
        """Run a tool — awaits if the function is async, otherwise calls sync."""
        if name not in self._tools:
            raise KeyError(f"Unknown tool: {name}. Available: {list(self._tools)}")
        if isinstance(arguments, str):
            arguments = json.loads(arguments)
        result = self._tools[name].fn(**arguments)
        if inspect.isawaitable(result):
            result = await result
        return result

    def list_tools(self) -> list[str]:
        return list(self._tools.keys())

    def __len__(self) -> int:
        return len(self._tools)


class _RegisteredTool:
    __slots__ = ("fn", "name", "description", "schema")

    def __init__(self, fn: Callable, name: str, description: str, schema: dict):
        self.fn = fn
        self.name = name
        self.description = description
        self.schema = schema


def _build_schema(fn: Callable, name: str, description: str) -> dict[str, Any]:
    """Auto-generate a Realtime API tool schema from type hints."""
    sig = inspect.signature(fn)
    hints = get_type_hints(fn)

    properties: dict[str, Any] = {}
    required: list[str] = []

    for param_name, param in sig.parameters.items():
        if param_name in ("self", "cls"):
            continue
        prop: dict[str, Any] = {}
        hint = hints.get(param_name, str)
        prop["type"] = _TYPE_MAP.get(hint, "string")

        if param.default is not inspect.Parameter.empty:
            prop["default"] = param.default
        else:
            required.append(param_name)

        properties[param_name] = prop

    return {
        "type": "function",
        "name": name,
        "description": description,
        "parameters": {
            "type": "object",
            "properties": properties,
            "required": required,
            "additionalProperties": False,
        },
    }


# Singleton registry — shared across the process
registry = ToolRegistry()


def tool(
    fn: Callable | None = None,
    *,
    name: str | None = None,
    description: str | None = None,
) -> Callable:
    """Decorator to register a function as a Realtime API tool.

    Can be used with or without arguments::

        @tool
        def my_func(x: str) -> str: ...

        @tool(description="Do something")
        def my_func(x: str) -> str: ...
    """

    def decorator(f: Callable) -> Callable:
        registry.register(f, name=name, description=description)
        return f

    if fn is not None:
        return decorator(fn)
    return decorator
