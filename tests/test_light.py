"""The tray icon's image and the sync's unchanged-file shortcut."""

import io
import json
import urllib.error

import sync
import winapi


def test_dot_icon_is_a_round_dot():
    data = winapi.dot_icon_bytes((0x6A, 0x75, 0xF7))
    assert len(data) == 40 + 32 * 32 * 4 + 32 * 32 // 8
    pixels = data[40:40 + 32 * 32 * 4]
    alpha = lambda x, y: pixels[((31 - y) * 32 + x) * 4 + 3]
    assert alpha(16, 16) == 255  # solid middle
    assert alpha(0, 0) == 0      # clear corners


class FakeResponse:
    def __init__(self, status, body, etag):
        self.status, self._body, self.headers = status, body, {"ETag": etag}

    def read(self):
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def test_unchanged_file_comes_from_the_cache(monkeypatch):
    sync._CACHE.clear()
    sent = []
    doc = {"content": "", "sha": "abc"}

    def fake_urlopen(req, timeout, context):
        sent.append(req.get_header("If-none-match"))
        if len(sent) == 1:
            return FakeResponse(200, json.dumps(doc).encode(), '"e1"')
        raise urllib.error.HTTPError(req.full_url, 304, "Not Modified", {}, io.BytesIO(b""))

    monkeypatch.setattr(sync.urllib.request, "urlopen", fake_urlopen)
    f = sync.GitHubFile("o/r", "t")
    assert f._call("GET") == (200, doc)
    assert f._call("GET") == (200, doc)  # the 304 hands back the cached copy
    assert sent == [None, '"e1"']
