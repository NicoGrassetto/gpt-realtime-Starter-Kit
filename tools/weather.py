"""Example tool: get current weather for a city."""

from tools.registry import tool


@tool(description="Get current weather for a location")
def get_weather(city: str, units: str = "celsius") -> dict:
    """Return simulated weather data. Replace with a real API call."""
    return {
        "city": city,
        "temperature": 22 if units == "celsius" else 72,
        "units": units,
        "condition": "partly cloudy",
    }
