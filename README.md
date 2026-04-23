<p align="center">
    <img src="https://raw.githubusercontent.com/HanaokaYuzu/Gemini-API/master/assets/banner.png" width="55%" alt="Gemini Banner" align="center">
</p>
<p align="center">
    <a href="https://github.com/elity/Gemini-API/pkgs/container/gemini-api">
        <img src="https://ghcr-badge.egpl.dev/elity/gemini-api/latest_tag?label=ghcr.io%2Felity%2Fgemini-api" alt="GHCR image"></a>
    <a href="https://github.com/elity/Gemini-API/actions/workflows/docker-publish.yml">
        <img src="https://github.com/elity/Gemini-API/actions/workflows/docker-publish.yml/badge.svg" alt="Docker Publish"></a>
    <a href="https://github.com/HanaokaYuzu/Gemini-API/blob/master/LICENSE">
        <img src="https://img.shields.io/github/license/HanaokaYuzu/Gemini-API" alt="License"></a>
    <a href="https://pypi.org/project/gemini-webapi">
        <img src="https://img.shields.io/pypi/v/gemini-webapi?label=gemini-webapi%20(upstream)" alt="PyPI"></a>
</p>

# <img src="https://raw.githubusercontent.com/HanaokaYuzu/Gemini-API/master/assets/logo.svg" width="35px" alt="Gemini Icon" /> Gemini-API Gateway

> **Acknowledgement.** This project is a fork of [HanaokaYuzu/Gemini-API](https://github.com/HanaokaYuzu/Gemini-API) — an elegant async Python wrapper around Google Gemini. Huge thanks to [@HanaokaYuzu](https://github.com/HanaokaYuzu) and contributors for the foundational reverse-engineering work that made this gateway possible. The original Python library is preserved under `gemini-webapi` and still installable via PyPI; this fork adds an HTTP server layer that mirrors Google's official `v1beta` API contract so existing Gemini SDKs / clients can point at a self-hosted instance.

A self-hostable HTTP gateway that exposes your personal Google Gemini web account through the official Google `v1beta` REST contract.

---

## Why

Google's official Gemini API requires a paid GCP project and an API key billed per token. If you already have a Gemini web account (free or Advanced), this gateway lets you reuse that session over a stable, drop-in REST surface:

- **Drop-in compatible** — identical URL shape (`/v1beta/models/{model}:generateContent`), identical request/response JSON, identical auth header (`x-goog-api-key`). Point any existing Gemini SDK or client at `http://your-host:8080` and it Just Works.
- **No paid API key needed** — authenticates to Google with your web cookies (`__Secure-1PSID` / `__Secure-1PSIDTS`); the cookie is auto-refreshed and persisted across restarts.
- **Self-host friendly** — single multi-arch Docker image, fail-closed auth, non-root container, healthchecks built-in.

This is **not** an officially supported Google product. Use at your own risk and within Google's Terms of Service.

---

## Quick start

Pull the prebuilt multi-arch image from GHCR (`linux/amd64` + `linux/arm64`):

```yaml
# docker-compose.yml
services:
  gemini-api:
    image: ghcr.io/elity/gemini-api:latest
    container_name: gemini-api
    restart: unless-stopped
    ports:
      - "8080:8080"
    volumes:
      - ./config:/config
      - ./data:/data
    environment:
      - CONFIG_PATH=/config/config.yaml
      - GEMINI_COOKIE_PATH=/data/cookies
```

Minimal `config.yaml`:

```yaml
server:
  host: 0.0.0.0
  port: 8080
  auth_disabled: false        # MUST stay false on untrusted networks

api_keys:                     # at least one non-empty key is REQUIRED
  - sk-replace-me

gemini:
  secure_1psid: "REPLACE_WITH_YOUR_SECURE_1PSID"
  secure_1psidts: "REPLACE_WITH_YOUR_SECURE_1PSIDTS"
  refresh_interval: 600
  timeout: 450
```

The container runs as UID 10001. Make sure the mounted `./data` and `./config.yaml` are writable by that UID:

```bash
mkdir -p ./config ./data
cp /path/to/config.example.yaml ./config/config.yaml   # edit after copy
sudo chown -R 10001:10001 ./config ./data
docker compose up -d
```

Test with the recipes in [Request recipes](#request-recipes-curl).

For obtaining the `__Secure-1PSID` / `__Secure-1PSIDTS` cookies and the full config reference, see [Configuration](#configuration).

---

## Supported models

The `{model}` path segment must match a model name available to your Gemini
account. The authoritative list is enumerated in
[`src/gemini_webapi/constants.py`](./src/gemini_webapi/constants.py) (`class Model`)
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

---

## Request recipes (curl)

All examples assume the gateway is at `http://localhost:8080` and the API
key is `sk-replace-me`. Swap in your own host/key. Each recipe is a one-liner
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

---

## Endpoints

| Method | Path | Notes |
| --- | --- | --- |
| `POST` | `/v1beta/models/{model}:generateContent` | Standard one-shot generation. JSON in, JSON out. |
| `POST` | `/v1beta/models/{model}:streamGenerateContent` | Default response is a JSON array (matches Google's v1beta default). Pass `?alt=sse` for `text/event-stream`. |
| `GET`  | `/healthz` | Liveness — returns 200 as long as the process is up. |
| `GET`  | `/readyz`  | Readiness — 200 only if `GeminiClient` is running and the `__Secure-1PSIDTS` cookie was refreshed within `2 × refresh_interval`. |

Authentication accepts any of:

- `x-goog-api-key: <key>` header (Google's official spec — preferred)
- `Authorization: Bearer <key>` header
- `?key=<key>` query parameter

API keys are compared with `hmac.compare_digest`. Empty `api_keys` list **fails closed** — every request returns 401 unless `server.auth_disabled: true` is set explicitly.

What is silently accepted but ignored, and what is intentionally out of scope (e.g. `countTokens`, `generationConfig`, `safetySettings`, multi-account pooling), is documented in [What is and isn't implemented](#what-is-and-isnt-implemented).

---

## Configuration

### Required keys

| Key | Purpose |
| --- | --- |
| `gemini.secure_1psid`   | `__Secure-1PSID` cookie from your gemini.google.com session |
| `gemini.secure_1psidts` | `__Secure-1PSIDTS` cookie; the gateway will rotate this in place |
| `api_keys`              | List of accepted client keys; empty = fail closed |

### Environment variables

| Var | Default | Purpose |
| --- | --- | --- |
| `CONFIG_PATH`        | `/config/config.yaml` | Path to the config file (mounted in) |
| `GEMINI_COOKIE_PATH` | `/data/cookies`        | Where the upstream library persists cached cookies |

See [`config.example.yaml`](./config.example.yaml) for the full schema. The
program rewrites `gemini.secure_1psidts` in place; comments are preserved via
`ruamel.yaml` round-trip but formatting in unusual cases may shift slightly —
keep a backup if you customize heavily.

### Cookie handling

- Reads the initial `secure_1psid` / `secure_1psidts` from `config.yaml`.
- The underlying library rotates `__Secure-1PSIDTS` every
  `gemini.refresh_interval` seconds (default 600).
- A supervised watcher task polls the live cookie jar; when it changes, the
  new value is written back to `config.yaml` atomically
  (randomly-named temp file → `os.replace`, with both an `asyncio.Lock` and
  a cross-process `fcntl.flock` for safety). POSIX only.
- Result: restarting the container never loses the latest cookie — it simply
  reads the most recent value from `config.yaml` on startup.

The library also persists cookies into `/data/cookies/.cached_cookies_*.json`,
which is the second persistence layer (kept on the mounted `./data` volume).

Because the gateway atomically rewrites `config/config.yaml` whenever Google
rotates `__Secure-1PSIDTS`, the *parent directory* must be mounted (not the
single file). Mounting only the file causes `os.replace` to fail with
`EBUSY`.

### Obtaining the cookies

How to obtain the `__Secure-1PSID` / `__Secure-1PSIDTS` cookies from your
browser is documented in detail in the
[upstream README — Authentication](https://github.com/HanaokaYuzu/Gemini-API#authentication).

---

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

---

## Breaking changes

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

---

## Security notes

- **Fail-closed auth.** `api_keys` MUST be set in `config.yaml`. An empty list is treated as misconfiguration and every request is rejected with 401 (unless `server.auth_disabled: true` is set explicitly). The lifespan logs a startup warning so the failure mode is visible.
- **Do not expose `auth_disabled: true`** to the public internet. The startup banner logs `CRITICAL: SECURITY ...` whenever it is enabled — heed it.
- **Swagger / Redoc / OpenAPI are disabled** (`/docs`, `/redoc`, `/openapi.json` all 404) so unauthenticated scanners don't get a free schema dump.
- **Upstream errors are not echoed** to clients — `str(exc)` may contain session cookies or internal URLs. Errors return generic 502/504 messages; full traces go to the server log.
- **Stream errors don't leak.** A failing `streamGenerateContent` emits a generic error chunk; the upstream exception is logged server-side only.
- **Inline base64 input is capped** at ~20 MB (`max_inline_data_b64_chars`, default 27 000 000) to guard against memory exhaustion.
- **Model path is regex-validated** against an allowlist before being passed to the upstream client, blocking path traversal and injection attempts.
- **Container runs as non-root** (UID 10001).

---

## Limitations

- Single Gemini account per process.
- Single Uvicorn worker (the underlying library holds an async lock; more
  workers would also race on the config file).
- `model` in the URL is validated against a regex then passed straight to
  the library resolver; valid names are whatever the account exposes, see
  [`src/gemini_webapi/constants.py`](./src/gemini_webapi/constants.py) for
  the built-in enum plus dynamically discovered models.
- POSIX only (uses `fcntl.flock`).

---

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
[Breaking changes](#breaking-changes).

---

## License & Credits

Released under the same license as upstream — see [`LICENSE`](./LICENSE).

This fork stands entirely on the work of:

- [@HanaokaYuzu](https://github.com/HanaokaYuzu) and the [HanaokaYuzu/Gemini-API](https://github.com/HanaokaYuzu/Gemini-API) contributors — original `gemini-webapi` Python library and reverse-engineering of the Gemini web app.

The HTTP gateway, Docker packaging, GHCR release pipeline, and this documentation are additions on top of that foundation.
