from functools import cache
from pathlib import Path

APP_DIRS = [Path("/Applications"), Path("/System/Applications"),
            Path("/System/Applications/Utilities"), Path.home() / "Applications"]


@cache
def installed_apps() -> tuple[str, ...]:
    names = {p.stem for d in APP_DIRS if d.is_dir() for p in d.glob("*.app")}
    return tuple(sorted(names, key=str.lower))
