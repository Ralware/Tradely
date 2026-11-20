import csv
import io
import time

from app.api import research
from app.main import app
from fastapi.testclient import TestClient


def test_search_api_export_and_refresh(tmp_path, monkeypatch):
    monkeypatch.setattr(research, "jobs", tmp_path)
    client = TestClient(app)
    url = "/api/backtests/research"
    assert client.get(url + "/hardware").status_code == 200
    assert client.post(url, json={"combinations": -1}).status_code == 422
    job = client.post(url, json={"combinations": 2, "mode": "cpu"}).json()["id"]
    deadline = time.monotonic() + 90
    while time.monotonic() < deadline:
        state = client.get(f"{url}/{job}").json()
        if state["status"] not in ("running", "starting"):
            break
        time.sleep(0.2)
    assert state["status"] == "completed", state
    assert state["completed"] == 2 and state["backend"] == "cpu"
    assert client.get(f"{url}/{job}").json() == state
    rows = list(csv.DictReader(io.StringIO(client.get(f"{url}/{job}/csv").text)))
    assert len(rows) == 2
    for row in state["top"]:
        assert row in rows
    assert all(row["funding_model"] == "HISTORICAL_SETTLEMENTS" for row in rows)


def test_cancel_then_resume_same_run(tmp_path, monkeypatch):
    monkeypatch.setattr(research, "jobs", tmp_path)
    client = TestClient(app)
    root = "/api/backtests/research"
    job = client.post(root, json={"combinations": 2, "mode": "gpu"}).json()["id"]
    url = f"{root}/{job}"
    assert client.delete(url).is_success

    def await_status():
        deadline = time.monotonic() + 120
        while time.monotonic() < deadline:
            state = client.get(url).json()
            if state["status"] not in ("starting", "running"):
                return state
            time.sleep(0.25)
        raise AssertionError("Research job did not finish")

    assert await_status()["status"] == "interrupted"
    assert client.post(url + "/resume").is_success
    state = await_status()
    assert state["status"] == "completed" and state["completed"] == 2
    assert client.post(url + "/resume").status_code == 409
