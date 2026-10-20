import time
from dataclasses import dataclass
from typing import Callable

from . import mac
from .apps import app_paths
from .extract import search_target, text_to_type
from .router import Route

MEDIA = {
    "play": ("play/pause", lambda: mac.media_key(mac.NX_PLAY)),
    "pause": ("play/pause", lambda: mac.media_key(mac.NX_PLAY)),
    "next": ("next track", lambda: mac.media_key(mac.NX_NEXT)),
    "previous": ("previous track", lambda: mac.media_key(mac.NX_PREVIOUS)),
    "volume_up": ("volume +10", lambda: mac.change_volume(10)),
    "volume_down": ("volume -10", lambda: mac.change_volume(-10)),
    "mute": ("toggle mute", mac.toggle_mute),
}

WINDOW = {
    "left_half": lambda: mac.tile("left_half"),
    "right_half": lambda: mac.tile("right_half"),
    "maximize": lambda: mac.tile("maximize"),
    "minimize": mac.minimize_window,
    "close_window": mac.close_window,
    "close_all": mac.close_all_windows,
    "fullscreen": mac.toggle_fullscreen,
}

SYSTEM_TWO = {"rewrite_selection", "calendar_reminder", "ask_question", "escalate_complex"}

Plan = tuple[str, Callable[[], None] | None]


@dataclass
class Outcome:
    done: bool
    message: str
    ms: float = 0.0


def plan_open_app(route: Route, transcript: str, ctx: mac.Context) -> Plan:
    name = route.slots.get("app")
    if not name:
        return "no installed app matches", None
    return f"open {name}", lambda: mac.open_app(app_paths()[name])


def plan_type_text(route: Route, transcript: str, ctx: mac.Context) -> Plan:
    text = text_to_type(transcript)
    if not text:
        return "nothing to type", None
    return f"type {text!r}", lambda: mac.paste_text(text)


def plan_web_search(route: Route, transcript: str, ctx: mac.Context) -> Plan:
    url = search_target(transcript)
    return f"open {url}", lambda: mac.open_url(url)


def plan_media(route: Route, transcript: str, ctx: mac.Context) -> Plan:
    action = route.slots.get("media_action")
    if action not in MEDIA:
        return "unknown media action", None
    label, run = MEDIA[action]
    return label, run


def plan_window(route: Route, transcript: str, ctx: mac.Context) -> Plan:
    action = route.slots.get("window_action")
    if action not in WINDOW:
        return "unknown window action", None
    return f"{action.replace('_', ' ')} ({ctx.app or 'front window'})", WINDOW[action]


PLANNERS = {
    "open_app": plan_open_app,
    "type_text": plan_type_text,
    "web_search": plan_web_search,
    "media_control": plan_media,
    "window_management": plan_window,
}


def plan(route: Route, transcript: str, ctx: mac.Context) -> Plan:
    if route.intent == "ignore_noise":
        return "ignored", None
    if route.intent in SYSTEM_TWO:
        return f"{route.intent} needs System 2 (not built yet)", None
    return PLANNERS[route.intent](route, transcript, ctx)


def perform(route: Route, transcript: str, ctx: mac.Context, dry_run: bool = False) -> Outcome:
    if not route.confident:
        return Outcome(False, f"unsure ({route.intent} at {route.confidence:.2f}), not acting")
    description, run = plan(route, transcript, ctx)
    if run is None:
        return Outcome(False, description)
    if dry_run:
        return Outcome(False, f"would {description}")
    start = time.perf_counter()
    try:
        run()
    except mac.MacError as e:
        return Outcome(False, f"{description} failed: {e}", (time.perf_counter() - start) * 1000)
    return Outcome(True, description, (time.perf_counter() - start) * 1000)
