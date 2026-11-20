"""Find a join link in the location field or in the meeting text."""

from __future__ import annotations

import re

_URL_RE = re.compile(r"https?://[^\s<>\"']+", re.IGNORECASE)
_PLACES = (
    ("teams.microsoft.com", "Microsoft Teams"),
    ("teams.live.com", "Microsoft Teams"),
    ("meet.google.com", "Google Meet"),
    ("hangouts.google.com", "Google Meet"),
    ("zoom.us", "Zoom"),
    ("webex.com", "Webex"),
    ("skype.com", "Skype"),
    ("gotomeeting.com", "GoTo Meeting"),
)


def place_name(location: str) -> str:
    text = (location or "").strip()
    if not text:
        return ""
    if _is_url(text):
        return _label_for(text)
    return text


def find_meeting_url(*parts: str) -> str | None:
    """Prefer a known meeting service. A location that is only a URL is also a join link."""
    blobs = [part for part in parts if part and part.strip()]
    if not blobs:
        return None
    urls: list[str] = []
    for blob in blobs:
        urls.extend(_clean(match) for match in _URL_RE.findall(blob))
    for url in urls:
        if _service(url):
            return url
    location = blobs[0].strip()
    if _is_url(location):
        return _clean(location)
    return None


def meeting_url(meeting) -> str:
    """Stored join link, otherwise a link in the location field or the body."""
    stored = (getattr(meeting, "online_meeting_url", None) or "").strip()
    if stored.startswith(("http://", "https://")):
        return stored
    return find_meeting_url(
        getattr(meeting, "location", "") or "",
        getattr(meeting, "body_text", "") or "",
        getattr(meeting, "body_html", "") or "",
    ) or ""


def _is_url(value: str) -> bool:
    lowered = value.strip().lower()
    return lowered.startswith("http://") or lowered.startswith("https://")


def _service(url: str) -> str:
    lowered = url.lower()
    for host, label in _PLACES:
        if host in lowered:
            return label
    return ""


def _label_for(url: str) -> str:
    return _service(url) or "Online"


def _clean(url: str) -> str:
    return url.rstrip(").,]>\"'")
