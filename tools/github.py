"""Tool: look up a GitHub user profile using the GitHub API (free, no API key, 60 req/hr)."""

import httpx
from agents import function_tool


@function_tool
async def get_github_user_info(username: str) -> str:
    """Look up a GitHub user's public profile (e.g. 'torvalds', 'gvanrossum')."""
    async with httpx.AsyncClient() as client:
        r = await client.get(f"https://api.github.com/users/{username}")
        if r.status_code == 404:
            return f"GitHub user '{username}' not found."
        u = r.json()
        return (
            f"{u['login']} ({u.get('name') or 'N/A'}): "
            f"{u['public_repos']} public repos, {u['followers']} followers. "
            f"Bio: {u.get('bio') or 'None'}"
        )
