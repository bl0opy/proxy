import re
from urllib.parse import quote_plus

SEARCH_URL = "https://www.google.com/search?q="
TYPE_TRIGGER = re.compile(r"^(?:please\s+)?(?:type|write|dictate|enter|say)(?:\s+out)?[\s,:]+", re.I)
SEARCH_TRIGGER = re.compile(
    r"^(?:please\s+)?(?:search(?:\s+the\s+web)?(?:\s+for)?|google|look\s+up|find\s+online|go\s+to|open|visit)\s+", re.I)
DOMAIN = re.compile(r"^[a-z0-9-]+(\.[a-z0-9-]+)*\.[a-z]{2,}(/\S*)?$", re.I)


def text_to_type(transcript: str) -> str:
    return TYPE_TRIGGER.sub("", transcript.strip(), count=1)


def search_target(transcript: str) -> str:
    query = SEARCH_TRIGGER.sub("", transcript.strip().rstrip(".?!"), count=1)
    spoken = re.sub(r"\s+dot\s+", ".", query, flags=re.I)
    spoken = re.sub(r"\s+slash\s+", "/", spoken, flags=re.I)
    if DOMAIN.match(spoken.replace(" ", "")):
        url = spoken.replace(" ", "").lower()
        return url if url.startswith("http") else f"https://{url}"
    return SEARCH_URL + quote_plus(query)
