import hashlib
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from contextlib import contextmanager

ROOT = Path(__file__).resolve().parents[2]


def utc(value):
    """Normalize dates to end of day and timestamps to UTC; reject naive timestamps."""
    if len(str(value)) == 10:
        value += "T23:59:59Z"
    dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if dt.tzinfo is None:
        raise ValueError("timestamp requires timezone")
    if dt.microsecond:
        raise ValueError("仅支持整秒时间；拒绝小数秒以避免截断造成 as_of 泄漏")
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def now():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def dump(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False),
        encoding="utf-8",
    )


def digest(value):
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, ensure_ascii=False, allow_nan=False).encode()
    ).hexdigest()


@contextmanager
def connect(path):
    if not Path(path).is_file():
        raise ValueError("数据库不存在；运行 demo 或 import 创建")
    con = sqlite3.connect(path)
    try:
        con.row_factory = sqlite3.Row
        con.execute("PRAGMA foreign_keys=ON")
        if con.execute("PRAGMA user_version").fetchone()[0] not in (1, 2):
            raise ValueError("数据库版本不兼容；运行 demo 重建到新路径")
        with con:
            yield con
    finally:
        con.close()
