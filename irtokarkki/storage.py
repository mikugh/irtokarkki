"""Where the web app keeps the shopping list and favourite stores.

On Vercel: an Upstash Redis database (added from the Vercel Marketplace), spoken to over its
REST API. Locally: user_data.json in the project folder (kept out of git).
Values are anything JSON can hold. Names in use: "list", "stores".
"""
import json
import os
import threading
from pathlib import Path
from typing import Any

import requests

from .core import ROOT

FILE_PATH = ROOT / "user_data.json"


class StorageNotConfigured(RuntimeError):
    pass


class MemoryStorage:
    def __init__(self):
        self._data: dict[str, Any] = {}

    def get(self, name: str) -> Any | None:
        return json.loads(json.dumps(self._data.get(name)))  # a copy, like the real stores give

    def set(self, name: str, value: Any) -> None:
        self._data[name] = json.loads(json.dumps(value))


class FileStorage:
    def __init__(self, path: Path = FILE_PATH):
        self.path = Path(path)
        self._lock = threading.Lock()

    def _read(self) -> dict:
        return json.loads(self.path.read_text(encoding="utf-8")) if self.path.exists() else {}

    def get(self, name: str) -> Any | None:
        with self._lock:
            return self._read().get(name)

    def set(self, name: str, value: Any) -> None:
        with self._lock:
            data = self._read()
            data[name] = value
            self.path.write_text(json.dumps(data, indent=1, ensure_ascii=False), encoding="utf-8")


class RedisStorage:
    def __init__(self, url: str, token: str, prefix: str = "irtokarkki:"):
        self.url = url.rstrip("/")
        self._token = token
        self.prefix = prefix

    def _command(self, *args: str) -> Any:
        resp = requests.post(self.url, json=list(args), headers={"Authorization": f"Bearer {self._token}"}, timeout=15)
        resp.raise_for_status()
        return resp.json().get("result")

    def get(self, name: str) -> Any | None:
        raw = self._command("GET", self.prefix + name)
        return None if raw is None else json.loads(raw)

    def set(self, name: str, value: Any) -> None:
        self._command("SET", self.prefix + name, json.dumps(value, ensure_ascii=False))


def load_storage() -> MemoryStorage | FileStorage | RedisStorage:
    url = os.environ.get("KV_REST_API_URL") or os.environ.get("UPSTASH_REDIS_REST_URL")
    token = os.environ.get("KV_REST_API_TOKEN") or os.environ.get("UPSTASH_REDIS_REST_TOKEN")
    if url and token:
        return RedisStorage(url, token)
    if os.environ.get("VERCEL"):  # Vercel's disk is read-only and wiped: never fall back to a file there
        raise StorageNotConfigured("Storage isn't connected: add Upstash Redis to the Vercel project.")
    return FileStorage()
