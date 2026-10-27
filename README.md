# API Engineering — Connect Systems and Exchange Data

A FastAPI **live weather service** built on real, keyless public APIs, containerised with Docker and deployed on AWS EC2.

| API | Used for | Method |
|---|---|---|
| Open-Meteo Geocoding — `https://geocoding-api.open-meteo.com/v1/search` | City name → latitude/longitude | GET |
| Open-Meteo Forecast — `https://api.open-meteo.com/v1/forecast` | Current weather for coordinates | GET |
| restful-api.dev — `https://api.restful-api.dev/objects` | Store and fetch weather reports | POST, GET |

| Task | Where in `app.py` |
|---|---|
| 1. Explore API + docs | Notes below · this app's Swagger docs at `/docs` |
| 2. GET and POST | `call()` — the only function that talks to external APIs |
| 3. Parse JSON | Pydantic models `Place`, `Current`, `Stored`, `ReportIn` + `parse()` |
| 4. Integrate | `GET /weather/{city}`, `POST /reports`, `GET /reports/{id}` |
| 5. Errors | Timeout → 504, unreachable → 502, 404 → 404, city not found → 404, rate limit → 503, other 4xx/5xx → 502, bad JSON / schema → 502, bad input → 422 |

## Task 1 — API exploration notes

**Open-Meteo Geocoding** (docs: https://open-meteo.com/en/docs/geocoding-api)
- `GET /v1/search?name=Delhi&count=1`
- Returns `{"results": [{"name", "country", "latitude", "longitude", "timezone", ...}]}`
- When no city matches, the `results` key is **missing entirely**, not an empty list. The app handles this.

**Open-Meteo Forecast** (docs: https://open-meteo.com/en/docs)
- `GET /v1/forecast?latitude=28.65&longitude=77.23&current=temperature_2m,relative_humidity_2m,wind_speed_10m,weather_code`
- Returns `{"current": {"time", "temperature_2m", ...}, "current_units": {...}}`
- `weather_code` is a WMO code (0 = clear, 3 = overcast, 61 = rain, 95 = thunderstorm).
- Errors come back as HTTP 400 with `{"error": true, "reason": "..."}`.
- Free for non-commercial use, no key, about 10,000 calls/day.

**restful-api.dev** (docs: https://restful-api.dev)
- `POST /objects` with `{"name": "...", "data": {...}}` stores a real object and returns it with an `id` and `createdAt`.
- `GET /objects/{id}` fetches it back. No key, but there is a daily request limit on the free tier.

Try them directly:

```bash
curl "https://geocoding-api.open-meteo.com/v1/search?name=Delhi&count=1"
curl "https://api.open-meteo.com/v1/forecast?latitude=28.65&longitude=77.23&current=temperature_2m,weather_code"
curl -X POST https://api.restful-api.dev/objects -H "Content-Type: application/json" \
     -d '{"name":"test","data":{"hello":"world"}}'
```

## Endpoints

| Endpoint | What happens |
|---|---|
| `GET /weather/{city}` | GET geocoding → GET forecast → one combined response |
| `POST /reports` `{"city": "Delhi", "note": "..."}` | Fetches live weather, then **POSTs** it to restful-api.dev; returns `report_id` |
| `GET /reports/{report_id}` | **GETs** the stored report back from restful-api.dev |
| `GET /health` | Liveness check (used by Docker `HEALTHCHECK`) |

Example `/weather/Delhi` response:

```json
{"city": "Delhi", "country": "India", "lat": 28.65, "lon": 77.23,
 "observed_at": "2026-10-27T18:45", "temperature_c": 27.4, "humidity_pct": 52,
 "wind_kmh": 6.1, "conditions": "Mainly clear"}
```

## Run locally

```bash
pip install -r requirements.txt
python test_app.py            # offline tests, external APIs mocked
uvicorn app:app --reload      # http://localhost:8000/docs
```

## Build the Docker image

```bash
docker build -t api-lab .
docker run -d -p 8000:8000 --name api-lab api-lab
curl localhost:8000/weather/Delhi
```

## Push to Docker Hub and run on EC2

**On your machine** (replace `<dockerhub-user>`):

```bash
docker login
docker build --platform linux/amd64 -t <dockerhub-user>/api-lab:2.0 .   # amd64 matters on M-series Macs
docker push <dockerhub-user>/api-lab:2.0
```

**Launch EC2:** Amazon Linux 2023, t2.micro/t3.micro. Security group inbound: SSH 22 (your IP), Custom TCP **8000** (0.0.0.0/0).

**On EC2:**

```bash
ssh -i key.pem ec2-user@<EC2-PUBLIC-IP>

sudo dnf install -y docker
sudo systemctl enable --now docker
sudo usermod -aG docker ec2-user && newgrp docker

docker pull <dockerhub-user>/api-lab:2.0
docker run -d -p 8000:8000 --restart unless-stopped --name api-lab <dockerhub-user>/api-lab:2.0
docker ps
```

(Ubuntu AMI: `sudo apt update && sudo apt install -y docker.io`, user `ubuntu`.)

**No registry option:** `docker save api-lab | gzip | ssh -i key.pem ec2-user@<EC2-PUBLIC-IP> 'gunzip | docker load'`

## Final — Demonstrate the integration

Open `http://<EC2-PUBLIC-IP>:8000/docs`, or:

```bash
H=http://<EC2-PUBLIC-IP>:8000
curl $H/health
curl $H/weather/Delhi                                     # 2 chained GETs, parsed
curl $H/weather/Mumbai
curl -X POST $H/reports -H "Content-Type: application/json" \
     -d '{"city":"Gurugram","note":"EC2 demo"}'            # POST → 201, copy report_id
curl $H/reports/<report_id>                               # GET it back

# error handling
curl -i $H/weather/zzzzqq                                 # 404 city not found
curl -i -X POST $H/reports -H "Content-Type: application/json" -d '{"city":"x"}'   # 422
docker run -d -p 8001:8000 -e WEATHER_URL=http://10.255.255.1 -e UPSTREAM_TIMEOUT=2 \
       <dockerhub-user>/api-lab:2.0
curl -i localhost:8001/weather/Delhi                      # on EC2: 504 timeout
```

Screenshots to capture: `docker push`, `docker ps` on EC2, `/docs` via public IP, `/weather/Delhi`, the POST response with `report_id`, the GET of that report, and the 404 / 422 / 504 responses.
# Industrial_Training
