"""Tool: get current local time in a timezone using Python stdlib."""

from datetime import datetime, timezone as tz
from zoneinfo import ZoneInfo, available_timezones

from agents import function_tool


@function_tool
async def get_local_time(timezone: str = "America/New_York") -> str:
    """Get the current local time in an IANA timezone (e.g. 'Europe/London', 'Asia/Tokyo', 'America/New_York')."""
    if timezone not in available_timezones():
        return f"Unknown timezone '{timezone}'. Use IANA format like 'America/New_York' or 'Europe/London'."
    zone = ZoneInfo(timezone)
    now = datetime.now(tz.utc).astimezone(zone)
    utc_offset = now.strftime("%z")
    utc_offset = f"{utc_offset[:3]}:{utc_offset[3:]}"
    return f"{timezone}: {now.strftime('%Y-%m-%d %H:%M:%S')} (UTC offset {utc_offset})"
