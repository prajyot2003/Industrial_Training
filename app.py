"""API Engineering lab — live weather service built on real, keyless public APIs.

  Open-Meteo Geocoding  https://geocoding-api.open-meteo.com/v1/search      (GET)
  Open-Meteo Forecast   https://api.open-meteo.com/v1/forecast              (GET)
  restful-api.dev       https://api.restful-api.dev/objects                 (POST + GET)

Task 1: Explore   -> README notes + this app's own docs at /docs
Task 2: GET/POST  -> call()
Task 3: Parse     -> Pydantic models + parse()
Task 4: Integrate -> /weather/{city} (2 APIs chained), POST /reports, GET /reports/{id}
Task 5: Errors    -> timeouts, network errors, 4xx/5xx, bad JSON, schema mismatch, city not found
"""
import os

import requests
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field, ValidationError

GEO_URL = os.getenv("GEO_URL", "https://geocoding-api.open-meteo.com/v1/search")
WEATHER_URL = os.getenv("WEATHER_URL", "https://api.open-meteo.com/v1/forecast")
STORE_URL = os.getenv("STORE_URL", "https://api.restful-api.dev/objects")
TIMEOUT = float(os.getenv("UPSTREAM_TIMEOUT", "5"))

app = FastAPI(title="Live Weather API Lab", version="2.0")


# ---------- Task 3: models for parsing upstream JSON ----------
class Place(BaseModel):
    name: str
    country: str = ""
    latitude: float
    longitude: float
    timezone: str = "auto"


class Current(BaseModel):
    time: str
    temperature_2m: float
    relative_humidity_2m: float
    wind_speed_10m: float
    weather_code: int


class Stored(BaseModel):
    id: str
    name: str
    data: dict
    createdAt: str | None = None


class ReportIn(BaseModel):
    city: str = Field(min_length=2, max_length=60)
    note: str = Field("", max_length=200)


# WMO weather codes used by Open-Meteo (subset)
WMO = {0: "Clear sky", 1: "Mainly clear", 2: "Partly cloudy", 3: "Overcast", 45: "Fog",
       51: "Light drizzle", 61: "Light rain", 63: "Rain", 65: "Heavy rain", 71: "Light snow",
       80: "Rain showers", 95: "Thunderstorm"}


# ---------- Task 2 + 5: the only function that talks to external APIs ----------
def call(method: str, url: str, params: dict | None = None, json: dict | None = None):
    try:
        r = requests.request(method, url, params=params, json=json, timeout=TIMEOUT)
    except requests.Timeout:
        raise HTTPException(504, f"Upstream timed out after {TIMEOUT}s")
    except requests.ConnectionError:
        raise HTTPException(502, "Upstream unreachable")

    try:
        body = r.json()
    except ValueError:
        raise HTTPException(502, f"Upstream sent invalid JSON (HTTP {r.status_code})")

    if r.status_code == 404:
        raise HTTPException(404, "Not found upstream")
    if r.status_code == 429:
        raise HTTPException(503, "Upstream rate limit hit, try again later")
    if not r.ok:
        # Open-Meteo errors look like {"error": true, "reason": "..."}
        reason = body.get("reason") or body.get("error") if isinstance(body, dict) else None
        raise HTTPException(502, f"Upstream HTTP {r.status_code}: {reason or 'error'}")
    return body


def parse(model, data):
    try:
        return model.model_validate(data)
    except ValidationError:
        raise HTTPException(502, "Upstream JSON did not match expected schema")


# ---------- Task 4: integration ----------
def find_city(city: str) -> Place:
    data = call("GET", GEO_URL, params={"name": city, "count": 1})
    results = data.get("results")  # key is absent when nothing matches
    if not results:
        raise HTTPException(404, f"City '{city}' not found")
    return parse(Place, results[0])


def weather_for(city: str) -> dict:
    place = find_city(city)
    data = call("GET", WEATHER_URL, params={
        "latitude": place.latitude,
        "longitude": place.longitude,
        "current": "temperature_2m,relative_humidity_2m,wind_speed_10m,weather_code",
        "timezone": place.timezone,
    })
    now = parse(Current, data.get("current"))
    return {
        "city": place.name,
        "country": place.country,
        "lat": place.latitude,
        "lon": place.longitude,
        "observed_at": now.time,
        "temperature_c": now.temperature_2m,
        "humidity_pct": now.relative_humidity_2m,
        "wind_kmh": now.wind_speed_10m,
        "conditions": WMO.get(now.weather_code, f"WMO code {now.weather_code}"),
    }


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/weather/{city}")
def get_weather(city: str):
    """GET geocoding -> GET forecast -> one combined response."""
    return weather_for(city)


@app.post("/reports", status_code=201)
def create_report(req: ReportIn):
    """Fetch live weather, then POST it to restful-api.dev as a stored snapshot."""
    snapshot = weather_for(req.city)
    saved = parse(Stored, call("POST", STORE_URL, json={
        "name": f"weather-report:{snapshot['city']}",
        "data": {**snapshot, "note": req.note},
    }))
    return {"report_id": saved.id, "created_at": saved.createdAt, "report": saved.data}


@app.get("/reports/{report_id}")
def get_report(report_id: str):
    saved = parse(Stored, call("GET", f"{STORE_URL}/{report_id}"))
    return {"report_id": saved.id, "report": saved.data}
