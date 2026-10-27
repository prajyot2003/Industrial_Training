"""Offline tests: external APIs are mocked with responses shaped like the real ones.
Run: python test_app.py
"""
from unittest.mock import patch, MagicMock

import requests
from fastapi.testclient import TestClient

import app as m

c = TestClient(m.app)


def resp(status=200, data=None, bad_json=False):
    r = MagicMock(status_code=status, ok=200 <= status < 300)
    if bad_json:
        r.json.side_effect = ValueError
    else:
        r.json.return_value = data
    return r


GEO = {"results": [{"name": "New Delhi", "country": "India", "latitude": 28.63,
                    "longitude": 77.21, "timezone": "Asia/Kolkata"}]}
WX = {"current": {"time": "2026-10-27T18:45", "temperature_2m": 27.4,
                  "relative_humidity_2m": 52, "wind_speed_10m": 6.1, "weather_code": 1}}
STORED = {"id": "ff8081819782e69e01", "name": "weather-report:New Delhi",
          "createdAt": "2026-10-27T13:15:00Z", "data": {"temperature_c": 27.4}}


def route(method, url, **kw):
    if url == m.GEO_URL:
        return resp(data=GEO if kw["params"]["name"] != "zzzz" else {"generationtime_ms": 0.3})
    if url == m.WEATHER_URL:
        return resp(data=WX)
    return resp(200, STORED)


with patch.object(m.requests, "request", side_effect=route):
    w = c.get("/weather/Delhi").json()
    assert w["temperature_c"] == 27.4 and w["conditions"] == "Mainly clear", w
    assert c.get("/weather/zzzz").status_code == 404                     # city not found
    r = c.post("/reports", json={"city": "Delhi", "note": "lab demo"})
    assert r.status_code == 201 and r.json()["report_id"] == STORED["id"], r.json()
    assert c.get(f"/reports/{STORED['id']}").status_code == 200
    assert c.post("/reports", json={"city": "x"}).status_code == 422      # bad input

with patch.object(m.requests, "request") as req:
    for upstream, expected in [
        (resp(404, {"error": "not found"}), 404),
        (resp(400, {"error": True, "reason": "Latitude must be in range"}), 502),
        (resp(429, {}), 503),
        (resp(500, {}), 502),
        (resp(bad_json=True), 502),
        (resp(data={"results": [{"name": "X"}]}), 502),                  # schema mismatch
    ]:
        req.side_effect, req.return_value = None, upstream
        assert c.get("/weather/Delhi").status_code == expected, expected

    req.side_effect = requests.Timeout
    assert c.get("/weather/Delhi").status_code == 504
    req.side_effect = requests.ConnectionError
    assert c.get("/weather/Delhi").status_code == 502

print("all checks passed")
