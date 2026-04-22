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

Container runs as non-root (UID 10001). The mounted `./data` and
`./config/config.yaml` must be writable by that UID; `chown -R 10001:10001`
if you hit permission errors on the rewritten `secure_1psidts` field.

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

Streaming (default: JSON array, matches Google v1beta):

```bash
curl -N -X POST \
  "http://localhost:8080/v1beta/models/gemini-3-pro:streamGenerateContent" \
  -H "x-goog-api-key: sk-replace-me" \
  -H "Content-Type: application/json" \
  -d '{"contents":[{"parts":[{"text":"Say hi in haiku"}]}]}'
```

Streaming with Server-Sent Events (add `?alt=sse`):

```bash
curl -N -X POST \
  "http://localhost:8080/v1beta/models/gemini-3-pro:streamGenerateContent?alt=sse" \
  -H "x-goog-api-key: sk-replace-me" \
  -H "Content-Type: application/json" \
  -d '{"contents":[{"parts":[{"text":"Say hi"}]}]}'
```

Liveness / readiness:

- `GET /healthz` — process is up.
- `GET /readyz` — `GeminiClient` is running, watcher task alive, and the
  `__Secure-1PSIDTS` cookie has been refreshed within `2 × refresh_interval`.

## Breaking changes (since initial server commit)

- **`api_keys: []` no longer disables auth.** An empty list is treated as
  misconfiguration and every request is rejected with 401. To run without
  authentication on a private network set `server.auth_disabled: true`
  explicitly in `config.yaml`; startup logs a CRITICAL warning so the state
  is visible.
- **`streamGenerateContent` default content type changed** from
  `text/event-stream` to `application/json` (JSON array, matching Google's
  v1beta default). Pass `?alt=sse` to keep the old SSE framing.
- **OpenAPI/Swagger routes disabled.** `/docs`, `/redoc`, and
  `/openapi.json` all return 404; re-enable at your own risk by running
  behind an authenticated proxy.
- **Container runs as non-root** (UID 10001). `chown` mounted volumes to
  match.

## What it does with cookies

- Reads the initial `secure_1psid` / `secure_1psidts` from `config.yaml`.
- The underlying library rotates `__Secure-1PSIDTS` every
  `gemini.refresh_interval` seconds (default 600).
- A supervised watcher task polls the live cookie jar; when it changes, the
  new value is written back to `config.yaml` atomically
  (randomly-named temp file → `os.replace`, with both an `asyncio.Lock` and
  a cross-process `fcntl.flock` for safety).
- Result: restarting the container never loses the latest cookie — it simply
  reads the most recent value from `config.yaml` on startup.

The library also persists cookies into `/data/cookies/.cached_cookies_*.json`,
which is the second persistence layer (kept on the mounted `./data` volume).

## What is and isn't implemented

Implemented:

- `POST /v1beta/models/{model}:generateContent`
- `POST /v1beta/models/{model}:streamGenerateContent` (JSON array, or SSE via `?alt=sse`)
- `GET /healthz`, `GET /readyz`
- Auth via `x-goog-api-key` header, `?key=` query, or `Authorization: Bearer <key>`
- Text + inline image input (`parts[].inline_data`), text + generated image
  output returned as base64 inline data
- `usageMetadata` populated when the upstream library reports token counts

Silently ignored (kept for request-shape compatibility):

- `generationConfig`, `safetySettings`, `tools`, `toolConfig`
- `fileData` (only `inlineData` is supported; `fileData` parts are logged and dropped)

Intentionally out of scope (YAGNI for now):

- `countTokens`
- `GET /v1beta/models`
- Multi-account pooling, rate limiting, Prometheus metrics
- Server-side `ChatSession` caching — every request is stateless; the client
  must send the full `contents` history

## Configuration

See [`config.example.yaml`](../config.example.yaml). The program rewrites
`gemini.secure_1psidts` in place; comments are preserved via `ruamel.yaml`
round-trip but formatting in unusual cases may shift slightly — keep a backup
if you customize heavily.

## Security posture

- **Fail-closed auth.** Empty `api_keys` + `auth_disabled=false` → all 401.
- **Fixed error messages for upstream failures** (502/504). `str(exc)` is
  never returned to the client; upstream exceptions may contain session
  cookie values.
- **Stream errors don't leak.** A failing `streamGenerateContent` emits a
  generic error chunk; the upstream exception is logged server-side only.
- **Base64 inline_data capped** at 27M chars (≈20 MB binary) to guard
  against memory exhaustion.
- **Model path validated** against a regex allowlist before being passed to
  the upstream client.
- **Non-root container, no Swagger, no Redoc, no OpenAPI in production.**

## Limitations

- Single Gemini account per process.
- Single Uvicorn worker (the underlying library holds an async lock; more
  workers would also race on the config file).
- `model` in the URL is validated against a regex then passed straight to
  the library resolver; valid names are whatever the account exposes, see
  [`src/gemini_webapi/constants.py`](../src/gemini_webapi/constants.py) for
  the built-in enum plus dynamically discovered models.
- POSIX only (uses `fcntl.flock`).
