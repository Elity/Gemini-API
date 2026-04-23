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

## Quick Start (Docker)

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

Minimal `config.yaml` (see [`docker/README.md`](./docker/README.md) for the full reference):

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

Smoke test against the same shape Google's API accepts:

```bash
curl -s -X POST \
  "http://localhost:8080/v1beta/models/gemini-3-flash:generateContent" \
  -H "x-goog-api-key: sk-replace-me" \
  -H "Content-Type: application/json" \
  -d '{
    "contents": [{
      "parts": [{"text": "Write a haiku about self-hosting."}]
    }]
  }'
```

How to obtain the `__Secure-1PSID` / `__Secure-1PSIDTS` cookies from your browser is documented in detail in the [upstream README — Authentication](https://github.com/HanaokaYuzu/Gemini-API#authentication).

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

What is silently accepted but ignored, and what is intentionally out of scope (e.g. `countTokens`, `generationConfig`, `safetySettings`, multi-account pooling), is documented in [`docker/README.md`](./docker/README.md#what-is-and-isnt-implemented).

---

## Configuration

Full schema, breaking-change notes, and operational details live in [`docker/README.md`](./docker/README.md). The minimum required keys are:

| Key | Purpose |
| --- | --- |
| `gemini.secure_1psid`   | `__Secure-1PSID` cookie from your gemini.google.com session |
| `gemini.secure_1psidts` | `__Secure-1PSIDTS` cookie; the gateway will rotate this in place |
| `api_keys`              | List of accepted client keys; empty = fail closed |

Environment variables consumed by the container:

| Var | Default | Purpose |
| --- | --- | --- |
| `CONFIG_PATH`        | `/config/config.yaml` | Path to the config file (mounted in) |
| `GEMINI_COOKIE_PATH` | `/data/cookies`        | Where the upstream library persists cached cookies |

The gateway rewrites `gemini.secure_1psidts` in `config.yaml` whenever Google rotates the cookie. The write is atomic (temp-file + `os.replace`) and protected by both an `asyncio.Lock` and a cross-process `fcntl.flock`. POSIX only.

---

## CORS

The server ships with an open CORS policy: `Access-Control-Allow-Origin: *`, all methods, all headers, **credentials disabled**. Any browser-based client may call the API, but the browser will not attach cookies — the JS must explicitly set `x-goog-api-key` (or `Authorization`) for each request. This keeps the API usable from local web tools without weakening the auth model.

---

## Releases & Docker Images

Pushing a `vX.Y.Z` git tag triggers `.github/workflows/docker-publish.yml`, which builds and publishes a multi-arch image to GHCR.

- Registry: `ghcr.io/elity/gemini-api`
- Architectures: `linux/amd64`, `linux/arm64`
- Tags published per release:
  - `vX.Y.Z` (e.g. `v1.2.3`)
  - `X.Y.Z`  (e.g. `1.2.3`)
  - `X.Y`    (e.g. `1.2`)
  - `latest`

Pin a specific version in production (`ghcr.io/elity/gemini-api:v1.0.0`); use `:latest` only for evaluation.

---

## Library use (legacy)

The original Python wrapper is unchanged and still importable:

```bash
pip install gemini-webapi
```

```python
from gemini_webapi import GeminiClient

client = GeminiClient(secure_1psid="...", secure_1psidts="...")
await client.init()
response = await client.generate_content("Hello Gemini")
print(response.text)
```

The full library API — image generation, deep research, gems, streaming, CLI — is documented in the upstream repository. To avoid drift, **this README does not duplicate it**:

- Library docs & examples: [HanaokaYuzu/Gemini-API](https://github.com/HanaokaYuzu/Gemini-API)
- PyPI: [`gemini-webapi`](https://pypi.org/project/gemini-webapi)

The `[server]` extra of `pyproject.toml` (`pip install "gemini-webapi[server]"`) installs FastAPI + Uvicorn + the YAML/HTTPX deps used by the gateway, for users who want to run the server outside Docker.

---

## Security notes

- **`api_keys` MUST be set** in `config.yaml`. An empty list is treated as misconfiguration and every request is rejected with 401. The lifespan also logs a startup warning so the failure mode is visible.
- **Do not expose `auth_disabled: true`** to the public internet. The startup banner logs `CRITICAL: SECURITY ...` whenever it is enabled — heed it.
- **Swagger / Redoc / OpenAPI are disabled** (`/docs`, `/redoc`, `/openapi.json` all 404) so unauthenticated scanners don't get a free schema dump.
- **Upstream errors are not echoed** to clients — `str(exc)` may contain session cookies or internal URLs. Errors return generic 502/504 / `stream interrupted` messages; full traces go to the server log.
- **Inline base64 input is capped** at ~20 MB (`max_inline_data_b64_chars`, default 27 000 000) to guard against memory exhaustion.
- **Model path is regex-validated** before being passed to the upstream client, blocking path traversal and injection attempts.
- **Container runs as non-root** (UID 10001).

---

## License & Credits

Released under the same license as upstream — see [`LICENSE`](./LICENSE).

This fork stands entirely on the work of:

- [@HanaokaYuzu](https://github.com/HanaokaYuzu) and the [HanaokaYuzu/Gemini-API](https://github.com/HanaokaYuzu/Gemini-API) contributors — original `gemini-webapi` Python library and reverse-engineering of the Gemini web app.

The HTTP gateway, Docker packaging, GHCR release pipeline, and this documentation are additions on top of that foundation.
