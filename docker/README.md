# Gemini-API Gateway (Docker)

Self-hosted HTTP service that wraps [`gemini_webapi`](../src/gemini_webapi) and
exposes a subset of the Google Gemini REST API (`:generateContent` and
`:streamGenerateContent`), so any client built against the official endpoint
can point at your own container instead.

## Quick start

```bash
cd docker
cp ../config.example.yaml config.yaml            # then fill in real PSID/PSIDTS/api_keys
mkdir -p data
docker compose up -d --build
```

Test it with the same shape of request the official API accepts:

```bash
curl -s -X POST \
  "http://localhost:8080/v1beta/models/gemini-3-pro:generateContent" \
  -H "x-goog-api-key: sk-replace-me" \
  -H "Content-Type: application/json" \
  -d '{
    "contents": [{
      "parts": [
        {"text": "Create a picture of a nano banana dish in a fancy restaurant with a Gemini theme"}
      ]
    }]
  }'
```

Streaming:

```bash
curl -N -X POST \
  "http://localhost:8080/v1beta/models/gemini-3-pro:streamGenerateContent" \
  -H "x-goog-api-key: sk-replace-me" \
  -H "Content-Type: application/json" \
  -d '{"contents":[{"parts":[{"text":"Say hi in haiku"}]}]}'
```

Liveness / readiness:

- `GET /healthz` — process is up.
- `GET /readyz` — `GeminiClient` is running and the `__Secure-1PSIDTS`
  cookie has been refreshed within `2 × refresh_interval`.

## What it does with cookies

- Reads the initial `secure_1psid` / `secure_1psidts` from `config.yaml`.
- The underlying library rotates `__Secure-1PSIDTS` every
  `gemini.refresh_interval` seconds (default 600).
- A small watcher task polls the live cookie jar; when it changes, the new
  value is written back to `config.yaml` atomically (`tmp` file → `os.replace`,
  with both an `asyncio.Lock` and a cross-process `fcntl.flock` for safety).
- Result: restarting the container never loses the latest cookie — it simply
  reads the most recent value from `config.yaml` on startup.

The library also persists cookies into `/data/cookies/.cached_cookies_*.json`,
which is the second persistence layer (kept on the mounted `./data` volume).

## What is and isn't implemented

Implemented:

- `POST /v1beta/models/{model}:generateContent`
- `POST /v1beta/models/{model}:streamGenerateContent` (SSE)
- `GET /healthz`, `GET /readyz`
- Auth via `x-goog-api-key` header, `?key=` query, or `Authorization: Bearer <key>`
- Text + inline image input (`parts[].inline_data`), text + generated image
  output returned as base64 inline data

Intentionally out of scope (YAGNI for now):

- `countTokens`
- `GET /v1beta/models`
- `generationConfig` / `safetySettings` (ignored, not translated)
- Multi-account pooling, rate limiting, Prometheus metrics
- Server-side `ChatSession` caching — every request is stateless; the client
  must send the full `contents` history

## Configuration

See [`config.example.yaml`](../config.example.yaml). The program rewrites
`gemini.secure_1psidts` in place; comments are preserved via `ruamel.yaml`
round-trip but formatting in unusual cases may shift slightly — keep a backup
if you customize heavily.

## Limitations

- Single Gemini account per process.
- Single Uvicorn worker (the underlying library holds an async lock; more
  workers would also race on the config file).
- `model` in the URL is passed straight to the library resolver; valid names
  are whatever the account exposes, see
  [`src/gemini_webapi/constants.py`](../src/gemini_webapi/constants.py) for the
  built-in enum plus dynamically discovered models.
