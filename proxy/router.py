import time
from dataclasses import dataclass, field

from .apps import installed_apps
from .fastpath import fast_route
from .intents import INTENTS, MEDIA_ACTIONS, NO_APP, WINDOW_ACTIONS
from .jev import Jev

CONFIDENT = 0.7
SLOT_FOR_INTENT = {"open_app": "app", "media_control": "media_action",
                   "window_management": "window_action"}


@dataclass
class Route:
    intent: str
    confidence: float
    source: str
    ms: float
    slots: dict = field(default_factory=dict)
    probabilities: dict = field(default_factory=dict)
    slot_confidence: dict = field(default_factory=dict)

    @property
    def confident(self) -> bool:
        return self.confidence >= CONFIDENT


def build_state(transcript: str, app: str = "", selection: str = "") -> str:
    lines = [f"Transcript: {transcript}"]
    if app:
        lines.append(f"Frontmost app: {app}")
    if selection:
        lines.append(f"Selected text: {selection}")
    return "\n".join(lines)


def build_questions() -> dict:
    apps = {name: None for name in installed_apps()[:254]}
    return {
        "intent": {"type": "choice", "instructions": "What the user wants the voice assistant to do.",
                   "criteria": INTENTS},
        "app": {"type": "choice", "instructions": "Which application the user wants to open or switch to.",
                "criteria": {NO_APP: "No application is named.", **apps}},
        "media_action": {"type": "choice", "instructions": "Which playback action the user wants.",
                         "criteria": MEDIA_ACTIONS},
        "window_action": {"type": "choice", "instructions": "Which window action the user wants.",
                          "criteria": WINDOW_ACTIONS},
    }


class Router:
    def __init__(self, jev: Jev | None = None):
        self._jev = jev or Jev()
        self._questions = build_questions()

    def warm(self):
        self._jev.warm()

    def route(self, transcript: str, app: str = "", selection: str = "") -> Route:
        start = time.perf_counter()
        if not selection and (hit := fast_route(transcript)):
            intent = hit.pop("intent")
            return Route(intent, 1.0, "fastpath", (time.perf_counter() - start) * 1000, hit,
                         slot_confidence={k: 1.0 for k in hit})

        answers = self._jev.ask(build_state(transcript, app, selection), self._questions)["answers"]
        top = answers["intent"]
        intent = top["choice"]
        slots, slot_confidence = {}, {}
        if slot := SLOT_FOR_INTENT.get(intent):
            choice = answers[slot]["choice"]
            if choice != NO_APP:
                slots[slot] = choice
                slot_confidence[slot] = answers[slot]["probabilities"][choice]
        ms = (time.perf_counter() - start) * 1000
        return Route(intent, top["probabilities"][intent], "jev", ms, slots, top["probabilities"],
                     slot_confidence)
