import difflib
import re

from .apps import installed_apps

MEDIA = {
    "pause": "pause", "stop the music": "pause", "play": "play", "resume": "play",
    "next": "next", "next track": "next", "next song": "next", "skip": "next",
    "skip this song": "next", "previous": "previous", "previous track": "previous",
    "volume up": "volume_up", "louder": "volume_up", "volume down": "volume_down",
    "quieter": "volume_down", "mute": "mute", "pause the music": "pause",
    "play music": "play", "play the music": "play",
}
OPEN = re.compile(r"^(?:open|launch|start|switch to|pull up|bring up)\s+(?:the\s+)?(.+?)(?:\s+app)?$")


def normalize(text: str) -> str:
    return re.sub(r"[^\w\s]", "", text.lower()).strip()


def match_app(name: str) -> str | None:
    apps = {a.lower(): a for a in installed_apps()}
    hit = difflib.get_close_matches(name, apps, n=1, cutoff=0.85)
    return apps[hit[0]] if hit else None


def fast_route(transcript: str) -> dict | None:
    text = normalize(transcript)
    if text in MEDIA:
        return {"intent": "media_control", "media_action": MEDIA[text]}
    if m := OPEN.match(text):
        if app := match_app(m.group(1)):
            return {"intent": "open_app", "app": app}
    return None
