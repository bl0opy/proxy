from functools import cache
from pathlib import Path

APP_DIRS = [Path("/Applications"), Path("/System/Applications"),
            Path("/System/Applications/Utilities"), Path.home() / "Applications"]


@cache
def app_paths() -> dict[str, Path]:
    found = {p.stem: p for d in reversed(APP_DIRS) if d.is_dir() for p in d.glob("*.app")}
    return dict(sorted(found.items(), key=lambda kv: kv[0].lower()))


def installed_apps() -> tuple[str, ...]:
    return tuple(app_paths())
