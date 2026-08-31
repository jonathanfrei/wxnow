from __future__ import annotations

import json
from pathlib import Path

from platformdirs import user_cache_dir

MAX = 8


def _path() -> Path:
    p = Path(user_cache_dir("wxnow")) / "recents.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    return p


def load() -> list[str]:
    p = _path()
    if not p.exists():
        return []
    try:
        data = json.loads(p.read_text())
        return [str(x) for x in data if x][:MAX]
    except (OSError, json.JSONDecodeError, TypeError):
        return []


def remember(query: str) -> None:
    q = query.strip()
    if not q or q.lower() == "ip":
        return
    items = [q] + [x for x in load() if x.lower() != q.lower()]
    _path().write_text(json.dumps(items[:MAX]))
