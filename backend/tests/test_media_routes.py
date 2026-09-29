import subprocess, shutil
from pathlib import Path
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from app.api import media_routes

@pytest.fixture(scope="module")
def video(tmp_path_factory):
    p = tmp_path_factory.mktemp("v") / "clip.mp4"
    if shutil.which("ffmpeg"):
        subprocess.run(["ffmpeg","-y","-f","lavfi","-i","testsrc=duration=3:size=320x240:rate=15",
                        "-f","lavfi","-i","sine=duration=3","-c:v","libx264","-c:a","aac",
                        "-movflags","+faststart","-shortest",str(p)],
                       check=True, capture_output=True)
    else:
        p.write_bytes(bytes(range(256)) * 4000)  # ~1 MB of bytes
    return p

@pytest.fixture()
def client(video, monkeypatch):
    monkeypatch.setattr(media_routes, "get_job_file", lambda job_id: video if job_id == "ok" else None)
    app = FastAPI(); app.include_router(media_routes.router)
    return TestClient(app)

def test_play_is_inline_and_full(client, video):
    r = client.get("/api/media/ok/play")
    assert r.status_code == 200
    assert r.headers["content-disposition"].startswith("inline")
    assert r.headers["accept-ranges"] == "bytes"
    assert r.headers["content-type"].startswith("video/mp4")
    assert len(r.content) == video.stat().st_size

def test_download_is_attachment(client):
    r = client.get("/api/media/ok/download")
    assert r.status_code == 200
    assert r.headers["content-disposition"].startswith("attachment")

def test_range_returns_206(client, video):
    size = video.stat().st_size
    r = client.get("/api/media/ok/play", headers={"Range": "bytes=100-199"})
    assert r.status_code == 206
    assert r.headers["content-range"] == f"bytes 100-199/{size}"
    assert len(r.content) == 100
    assert r.content == video.read_bytes()[100:200]

def test_open_ended_and_suffix_range(client, video):
    size = video.stat().st_size
    r = client.get("/api/media/ok/play", headers={"Range": "bytes=500-"})
    assert r.status_code == 206 and len(r.content) == size - 500
    r = client.get("/api/media/ok/play", headers={"Range": "bytes=-50"})
    assert r.status_code == 206 and r.content == video.read_bytes()[-50:]

def test_bad_range_416(client, video):
    size = video.stat().st_size
    r = client.get("/api/media/ok/play", headers={"Range": f"bytes={size+10}-"})
    assert r.status_code == 416

def test_head_and_missing(client):
    assert client.head("/api/media/ok/play").status_code == 200
    assert client.get("/api/media/nope/play").status_code == 404
