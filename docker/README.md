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
  "http://localhost:8080/v1beta/models/gemini-3-flash:generateContent" \
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
  "http://localhost:8080/v1beta/models/gemini-3-flash:streamGenerateContent" \
  -H "x-goog-api-key: sk-replace-me" \
  -H "Content-Type: application/json" \
  -d '{"contents":[{"parts":[{"text":"Say hi in haiku"}]}]}'
```

Streaming with Server-Sent Events (add `?alt=sse`):

```bash
curl -N -X POST \
  "http://localhost:8080/v1beta/models/gemini-3-flash:streamGenerateContent?alt=sse" \
  -H "x-goog-api-key: sk-replace-me" \
  -H "Content-Type: application/json" \
  -d '{"contents":[{"parts":[{"text":"Say hi"}]}]}'
```

Liveness / readiness:

- `GET /healthz` — process is up.
- `GET /readyz` — `GeminiClient` is running, watcher task alive, and the
  `__Secure-1PSIDTS` cookie has been refreshed within `2 × refresh_interval`.

## Supported models

The `{model}` path segment must match a model name available to your Gemini
account. The authoritative list is enumerated in
[`src/gemini_webapi/constants.py`](../src/gemini_webapi/constants.py) (`class Model`)
and is also dynamically reported by the upstream `/400` error body when you
guess wrong:

| Model name                        | Family              | Notes                                      |
|-----------------------------------|---------------------|--------------------------------------------|
| `unspecified`                     | default             | Let the account pick its own default.      |
| `gemini-3-pro`                    | Pro                 | Strongest reasoning.                       |
| `gemini-3-flash`                  | Flash               | Fast & cheap. Good default for smoke tests.|
| `gemini-3-flash-thinking`         | Flash (CoT)         | Chain-of-thought exposed in output.        |
| `gemini-3-pro-plus`               | Pro Plus            | Larger context. Requires Gemini Advanced.  |
| `gemini-3-flash-plus`             | Flash Plus          | Larger context. Requires Gemini Advanced.  |
| `gemini-3-flash-thinking-plus`    | Flash Thinking Plus | Plus + CoT. Requires Gemini Advanced.      |
| `gemini-3-pro-advanced`           | Pro Advanced        | Top tier. Requires Gemini Advanced.        |
| `gemini-3-flash-advanced`         | Flash Advanced      | Requires Gemini Advanced.                  |
| `gemini-3-flash-thinking-advanced`| Flash Thinking Adv. | Requires Gemini Advanced.                  |

The list depends on what your Google account has access to. If you request
a model you are not entitled to (or a name the upstream library does not
recognise), the gateway returns `400 Bad Request` with the exact set of
available names in the error message.

## Request recipes (curl)

All examples assume the gateway is at `http://localhost:8080` and the API
key is `sk-replace-me`. Swap in your host/key. Each recipe is a one-liner
you can copy-paste.

### Plain text → text (non-streaming)

```bash
curl -s -X POST \
  "http://localhost:8080/v1beta/models/gemini-3-flash:generateContent" \
  -H "x-goog-api-key: sk-replace-me" \
  -H "Content-Type: application/json" \
  -d '{"contents":[{"parts":[{"text":"Write a haiku about self-hosting."}]}]}'
```

### Streaming — JSON array (Google v1beta default)

```bash
curl -N -X POST \
  "http://localhost:8080/v1beta/models/gemini-3-flash:streamGenerateContent" \
  -H "x-goog-api-key: sk-replace-me" \
  -H "Content-Type: application/json" \
  -d '{"contents":[{"parts":[{"text":"Count slowly from 1 to 5."}]}]}'
```

### Streaming — Server-Sent Events (`?alt=sse`)

```bash
curl -N -X POST \
  "http://localhost:8080/v1beta/models/gemini-3-flash:streamGenerateContent?alt=sse" \
  -H "x-goog-api-key: sk-replace-me" \
  -H "Content-Type: application/json" \
  -d '{"contents":[{"parts":[{"text":"Count slowly from 1 to 5."}]}]}'
```

### Image input (base64-encoded `inline_data`)

```bash
IMG_B64=$(base64 -i /path/to/photo.jpg | tr -d '\n')
curl -s -X POST \
  "http://localhost:8080/v1beta/models/gemini-3-pro:generateContent" \
  -H "x-goog-api-key: sk-replace-me" \
  -H "Content-Type: application/json" \
  -d "$(jq -n --arg b64 \"$IMG_B64\" '{
    contents: [{
      parts: [
        { text: \"Describe this image in one sentence.\" },
        { inline_data: { mime_type: \"image/jpeg\", data: $b64 } }
      ]
    }]
  }')"
```

The base64 payload is capped at `server.max_inline_data_b64_chars` characters
(default 27 000 000 ≈ 20 MB of binary). Use `image/png`, `image/webp`, etc.
for other formats.

### Image generation (text → generated image)

```bash
curl -s -X POST \
  "http://localhost:8080/v1beta/models/gemini-3-pro:generateContent" \
  -H "x-goog-api-key: sk-replace-me" \
  -H "Content-Type: application/json" \
  -d '{
    "contents": [{
      "parts": [{
        "text": "Generate a picture of a nano banana plated at a fine-dining restaurant, Gemini-themed."
      }]
    }]
  }' | jq '.candidates[0].content.parts[] | select(.inline_data) | .inline_data.mime_type'
```

Generated images come back as `inline_data` parts (base64). Pipe through
`jq` + `base64 -d` to save:

```bash
# … same request as above, then:
| jq -r '.candidates[0].content.parts[] | select(.inline_data) | .inline_data.data' \
| base64 -d > out.png
```

## Google API compatibility reference

The gateway mirrors the public Google Gemini REST contract where possible,
so off-the-shelf clients that target the official endpoint work unchanged.
For the full schema (request / response JSON shape, field semantics, the
parts of `GenerateContentRequest` this gateway silently ignores), consult
Google's docs:

- REST method reference — [`generateContent`](https://ai.google.dev/api/generate-content) / [`streamGenerateContent`](https://ai.google.dev/api/generate-content#method:-models.streamgeneratecontent)
- All Gemini REST endpoints — <https://ai.google.dev/api/rest>
- Official model catalog (upstream Google — names differ from the web-account
  names this gateway accepts, see [Supported models](#supported-models)) — <https://ai.google.dev/gemini-api/docs/models>

Gateway-specific deviations from Google's contract are listed in
[What is and isn't implemented](#what-is-and-isnt-implemented) and
[Breaking changes](#breaking-changes-since-initial-server-commit).

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
