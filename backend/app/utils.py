import hashlib
import json
from datetime import datetime
from typing import Any


def json_dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), default=str)


def json_loads(value: str | None, default: Any) -> Any:
    if not value:
        return default
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return default


def digest_text(parts: list[str]) -> str:
    return hashlib.sha256("\n".join(parts).encode()).hexdigest()


def iso(value: datetime | None) -> str | None:
    return value.isoformat() + "Z" if value else None
