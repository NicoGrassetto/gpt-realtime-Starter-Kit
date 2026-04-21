"""Tool exports for the RealtimeAgent.

Usage:
    from tools import ALL_TOOLS
"""

from tools.dogs import get_dog_image
from tools.github import get_github_user_info
from tools.time import get_local_time
from tools.weather import get_weather

ALL_TOOLS = [get_weather, get_dog_image, get_local_time, get_github_user_info]
