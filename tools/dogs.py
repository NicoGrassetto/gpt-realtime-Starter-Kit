"""Tool: get a random dog image by breed using Dog CEO API (free, no API key)."""

import httpx
from agents import function_tool


@function_tool
async def get_dog_image(breed: str) -> str:
    """Get a random dog image URL for a given breed (e.g. 'labrador', 'poodle', 'husky')."""
    async with httpx.AsyncClient() as client:
        r = await client.get(
            f"https://dog.ceo/api/breed/{breed.lower()}/images/random"
        )
        data = r.json()
        if data.get("status") != "success":
            return f"Breed '{breed}' not found. Try common breeds like 'labrador', 'poodle', or 'husky'."
        return f"Here's a random {breed} image: {data['message']}"
