"""Tool: get current weather for a city using Open-Meteo (free, no API key)."""

import httpx
from agents import function_tool


@function_tool
async def get_weather(city: str) -> str:
    """Get current weather for a city (e.g. 'London', 'Tokyo', 'New York')."""
    async with httpx.AsyncClient() as client:
        geo = await client.get(
            "https://geocoding-api.open-meteo.com/v1/search",
            params={"name": city, "count": 1},
        )
        results = geo.json().get("results")
        if not results:
            return f"Could not find location '{city}'."
        loc = results[0]
        lat, lon = loc["latitude"], loc["longitude"]

        weather = await client.get(
            "https://api.open-meteo.com/v1/forecast",
            params={
                "latitude": lat,
                "longitude": lon,
                "current": "temperature_2m,relative_humidity_2m,wind_speed_10m,weather_code",
                "temperature_unit": "celsius",
            },
        )
        cur = weather.json()["current"]
        return (
            f"{loc['name']}, {loc.get('country', '')}: "
            f"{cur['temperature_2m']}°C, "
            f"Humidity: {cur['relative_humidity_2m']}%, "
            f"Wind: {cur['wind_speed_10m']} km/h"
        )
