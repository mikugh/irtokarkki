import pytest

from tarjoushaukka import storage


class FakeResponse:
    def __init__(self, body):
        self.body = body

    def json(self):
        return self.body

    def raise_for_status(self):
        pass


def test_file_storage_round_trip(tmp_path):
    s = storage.FileStorage(tmp_path / "user_data.json")
    assert s.get("list") is None
    s.set("list", [{"type": "word", "text": "kahvi", "flyers": False}])
    assert storage.FileStorage(tmp_path / "user_data.json").get("list")[0]["text"] == "kahvi"


def test_memory_storage_round_trip():
    s = storage.MemoryStorage()
    assert s.get("stores") is None
    s.set("stores", ["a"])
    assert s.get("stores") == ["a"]


def test_redis_storage_speaks_upstash_rest(monkeypatch):
    sent = []

    def fake_post(url, json, headers, timeout):
        sent.append((url, json, headers["Authorization"]))
        return FakeResponse({"result": '["a"]' if json[0] == "GET" else "OK"})

    monkeypatch.setattr(storage.requests, "post", fake_post)
    r = storage.RedisStorage("https://x.upstash.io", "tok")
    r.set("stores", ["a"])
    assert r.get("stores") == ["a"]
    assert sent[0] == ("https://x.upstash.io", ["SET", "tarjoushaukka:stores", '["a"]'], "Bearer tok")
    assert sent[1][1] == ["GET", "tarjoushaukka:stores"]


def test_redis_storage_missing_key_is_none(monkeypatch):
    monkeypatch.setattr(storage.requests, "post", lambda url, json, headers, timeout: FakeResponse({"result": None}))
    assert storage.RedisStorage("https://x.upstash.io", "tok").get("list") is None


def test_load_storage_picks_backend(monkeypatch):
    for v in ("KV_REST_API_URL", "KV_REST_API_TOKEN", "UPSTASH_REDIS_REST_URL", "UPSTASH_REDIS_REST_TOKEN", "VERCEL"):
        monkeypatch.delenv(v, raising=False)
    assert isinstance(storage.load_storage(), storage.FileStorage)
    monkeypatch.setenv("VERCEL", "1")
    with pytest.raises(storage.StorageNotConfigured):
        storage.load_storage()
    monkeypatch.setenv("UPSTASH_REDIS_REST_URL", "https://y.upstash.io")
    monkeypatch.setenv("UPSTASH_REDIS_REST_TOKEN", "t2")
    assert isinstance(storage.load_storage(), storage.RedisStorage)
    monkeypatch.setenv("KV_REST_API_URL", "https://x.upstash.io")
    monkeypatch.setenv("KV_REST_API_TOKEN", "t")
    assert storage.load_storage().url == "https://x.upstash.io"
