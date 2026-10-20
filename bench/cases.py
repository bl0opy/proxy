INTENTS = {
    "open_app": "Open, launch, or switch to an application.",
    "type_text": "Type or dictate the spoken words into the focused text field.",
    "rewrite_selection": "Rewrite, reformat, translate, or fix the currently selected text.",
    "web_search": "Search the web or open a website.",
    "media_control": "Play, pause, skip, or change volume of music or video.",
    "window_management": "Move, resize, minimize, close, or tile windows.",
    "calendar_reminder": "Create or read calendar events, reminders, timers, or alarms.",
    "ask_question": "A quick factual question answerable in a sentence.",
    "escalate_complex": "A multi-step task needing planning, files, or several apps.",
    "ignore_noise": "Not a command: background speech, filler, or an accidental trigger.",
}

FILLER_INTENTS = {
    f"extra_{i}": f"Placeholder action number {i} for an unrelated workflow."
    for i in range(1, 17)
}

CASES = [
    ("open spotify", "Finder", "", "open_app"),
    ("switch to slack", "Safari", "", "open_app"),
    ("hey sam just checking in on the deck for tomorrow", "Messages", "", "type_text"),
    ("type running ten minutes late sorry", "Slack", "", "type_text"),
    ("make this sound more professional", "Mail", "yo can u send me the file asap", "rewrite_selection"),
    ("translate this to spanish", "Notes", "Meeting moved to Thursday.", "rewrite_selection"),
    ("search for m1 max memory bandwidth", "Safari", "", "web_search"),
    ("go to github dot com", "Finder", "", "web_search"),
    ("skip this song", "Spotify", "", "media_control"),
    ("turn the volume down", "Safari", "", "media_control"),
    ("put this window on the left half", "Xcode", "", "window_management"),
    ("close all finder windows", "Finder", "", "window_management"),
    ("remind me at five to call mom", "Slack", "", "calendar_reminder"),
    ("set a timer for twenty minutes", "Terminal", "", "calendar_reminder"),
    ("how many ounces in a cup", "Safari", "", "ask_question"),
    ("find the pdf sam sent last week and summarize it into a note", "Mail", "", "escalate_complex"),
    ("uh yeah no i was telling him about the thing", "Zoom", "", "ignore_noise"),
]


def make_context(transcript: str, app: str, selection: str) -> str:
    lines = [f"Transcript: {transcript}", f"Frontmost app: {app}"]
    if selection:
        lines.append(f"Selected text: {selection}")
    return "\n".join(lines)
