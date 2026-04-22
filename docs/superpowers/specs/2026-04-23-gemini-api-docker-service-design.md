# Gemini-API Docker 化 + Gemini 官方 API 兼容层

## Context

`HanaokaYuzu/Gemini-API` 是一个通过 `__Secure-1PSID` / `__Secure-1PSIDTS` cookie 逆向 Gemini 网页版的异步 Python 客户端库。用户希望在不改动库内核的前提下，围绕该库构建一个长期运行、可放到 Docker 中对外提供 HTTP 服务的**网关**，其对外协议与 Google 官方 `generativelanguage.googleapis.com` 的 `:generateContent` / `:streamGenerateContent` 保持严格兼容，使得原本面向官方 API 的客户端代码（示例：`curl … /v1beta/models/gemini-3.1-flash-image-preview:generateContent`）无需改动即可切换到自托管端点。

关键约束：
- 库自带 `__Secure-1PSIDTS` 每 10 分钟自动刷新机制（`client.py:319-355` + `utils/rotate_1psidts.py`），容器长期运行期间必须将刷新后的新 cookie 持久化到宿主机挂载卷，**确保容器重启后不需要人工重新导出**。
- 配置入口统一为**单一 YAML 文件**（宿主机 → 容器挂载），程序拥有写权限并在刷新 1PSIDTS 时原地更新该文件。
- 仅做**单账号**、**单进程单 GeminiClient**、**无状态拼接 contents** 的最小可用版本，遵循 YAGNI。

目标产物：
- `server/` Python 包：FastAPI 应用（路由、鉴权、schema、converter、服务单例、配置仓储）
- `docker/Dockerfile` + `docker/docker-compose.yml`
- `config.example.yaml`
- 与 `server/` 对应的单元测试

不在本期范围：多账号池、`countTokens`、`GET /v1beta/models`、多轮 ChatSession 缓存、Prometheus 指标、速率限制。

---

## 架构总览

```
client ──HTTP──▶ FastAPI (uvicorn, 1 worker)
                   │
                   ├─ auth middleware (x-goog-api-key / ?key= 校验)
                   ├─ POST /v1beta/models/{model}:generateContent
                   ├─ POST /v1beta/models/{model}:streamGenerateContent (SSE)
                   ├─ GET  /healthz   (端口存活)
                   ├─ GET  /readyz    (底层 client 可用 & 最近一次刷新成功)
                   │
                   └─ GeminiService (全局单例)
                        │
                        ├─ gemini_webapi.GeminiClient (async, 内置自动刷新任务)
                        │     └─ 刷新成功 → 写 $GEMINI_COOKIE_PATH/.cached_cookies_*.json
                        │
                        ├─ CookieWatcher (后台 task, 监听 mtime)
                        │     └─ 变化 → ConfigStore.update_psidts(new)
                        │
                        └─ ConfigStore (单文件 YAML, asyncio.Lock + fcntl.flock + os.replace)
```

设计原则：
- **SRP**：`ConfigStore` 唯一持有对 `config.yaml` 的写权；`GeminiService` 唯一持有 `GeminiClient`；`converters` 纯函数；`auth` 纯依赖项。
- **KISS**：无数据库、无 Redis、无会话缓存；刷新同步走"监听 cookie 缓存文件 mtime"，避免 monkey-patch 上游库。
- **DIP**：路由层只依赖 `GeminiService` 的两个抽象方法 `generate()` / `generate_stream()`，便于后续替换（例如未来切换为官方 API）。

---

## 目录结构

```
Gemini-API/
├── src/gemini_webapi/                      # 原库，不改
├── server/
│   ├── __init__.py
│   ├── main.py                             # FastAPI app + lifespan
│   ├── settings.py                         # Pydantic Settings, 读取 CONFIG_PATH 环境变量
│   ├── config_store.py                     # YAML round-trip 读 / 原子写
│   ├── gemini_service.py                   # 全局 GeminiClient + CookieWatcher
│   ├── auth.py                             # Depends: x-goog-api-key 校验
│   ├── logging_setup.py                    # loguru JSON sink
│   ├── converters.py                       # request↔prompt+files, ModelOutput↔response
│   ├── schemas/
│   │   ├── __init__.py
│   │   ├── request.py                      # GenerateContentRequest/Content/Part/Blob
│   │   └── response.py                     # GenerateContentResponse/Candidate/FinishReason
│   ├── routes/
│   │   ├── __init__.py
│   │   ├── generate.py
│   │   └── health.py
│   └── errors.py                           # 统一异常 → Google 风格错误响应
├── docker/
│   ├── Dockerfile
│   └── docker-compose.yml
├── config.example.yaml
├── tests/server/                           # 新增
│   ├── test_converters.py
│   ├── test_config_store.py
│   ├── test_auth.py
│   └── test_routes.py
├── docs/superpowers/specs/
│   └── 2026-04-23-gemini-api-docker-service-design.md   # 待 plan 结束后写入仓库
└── pyproject.toml                          # 追加 [project.optional-dependencies] server
```

`pyproject.toml` 新增 extras（不污染主依赖）：
```toml
[project.optional-dependencies]
server = [
  "fastapi>=0.115",
  "uvicorn[standard]>=0.30",
  "pydantic>=2.12",
  "pydantic-settings>=2.5",
  "ruamel.yaml>=0.18",
]
```

---

## 配置文件（`config.yaml`）

```yaml
server:
  host: 0.0.0.0
  port: 8080
  log_level: INFO
api_keys:                     # 空数组 = 不鉴权（仅本地/内网场景）
  - sk-your-gateway-key
gemini:
  secure_1psid: "xxx"
  secure_1psidts: "yyy"       # 程序会原地更新
  proxy: null
  refresh_interval: 600
  timeout: 450
```

- 唯一的事实来源。
- 容器内读 `CONFIG_PATH` 环境变量（默认 `/config/config.yaml`）。
- 写回时 `ruamel.yaml` round-trip 保留注释与顺序；写入策略：`tmp` 同目录写 → `fsync` → `os.replace` → 进程内 `asyncio.Lock` + 跨进程 `fcntl.flock(LOCK_EX)`。

---

## 关键组件

### 1. `config_store.py`
- `load() -> Config`：Pydantic `Config` 模型（api_keys/server/gemini 三段）
- `async update_psidts(new_value: str) -> None`：
  1. `async with self._lock:` 进程内互斥
  2. 打开 `config.yaml.lock`，`fcntl.flock(LOCK_EX)` 跨进程互斥（多 worker 场景的保险）
  3. ruamel.yaml round-trip 读 → 改 `gemini.secure_1psidts` → 写入同目录临时文件 → `fsync` → `os.replace(tmp, config.yaml)`
  4. 写失败仅记 error，不抛出到请求路径

### 2. `gemini_service.py`
- `lifespan` 中启动：
  1. `ConfigStore.load()` 拿到 `Config`
  2. 设定 `os.environ["GEMINI_COOKIE_PATH"] = "/data/cookies"`（Dockerfile 已预设，代码兜底）
  3. `client = GeminiClient(cfg.gemini.secure_1psid, cfg.gemini.secure_1psidts, proxy=cfg.gemini.proxy)`
  4. `await client.init(auto_refresh=True, refresh_interval=cfg.gemini.refresh_interval, timeout=cfg.gemini.timeout)`
  5. 启动 `CookieWatcher` 后台 task
- `CookieWatcher`：
  - 每 30s 轮询 `/data/cookies/.cached_cookies_{PSID_tail}.json` 的 mtime
  - mtime 变化 → 读文件 → 提取 `__Secure-1PSIDTS` → 与内存中上次值对比 → 变化则调 `ConfigStore.update_psidts(new)` 并更新 `last_refresh_ok_at`
  - 失败记 warn，不中断
- `async generate(prompt, files, model)` → `ModelOutput`
- `async generate_stream(prompt, files, model)` → `AsyncIterator[ModelOutput]`
- 暴露只读属性：`is_running`、`last_refresh_ok_at`（供 `readyz` 判断）

### 3. `converters.py`

**请求 → prompt+files**：
```
for content in req.contents:
    role = content.role or "user"
    for part in content.parts:
        if part.text:
            text_chunks.append(f"{role}: {part.text}")
        elif part.inline_data:
            files.append(base64.b64decode(part.inline_data.data))
prompt = "\n\n".join(text_chunks)
```
- `generationConfig` / `safetySettings` / `systemInstruction`：记 debug 日志，不支持则忽略（YAGNI）。
  - 例外：`systemInstruction.parts[].text` 作为最前缀拼进 prompt（廉价且高价值）。
- 模型名直接透传给 `client._resolve_model_by_name(path_param)`；失败抛 `ModelNotFoundError` → 404。

**ModelOutput → response**：
```python
{
  "candidates": [{
    "content": {
      "role": "model",
      "parts": [
        {"text": output.text},
        *[
          {"inlineData": {"mimeType": "image/png", "data": base64(await img.save(bytes))}}
          for img in output.images
        ]
      ]
    },
    "finishReason": "STOP",
    "index": 0
  }],
  "usageMetadata": {"promptTokenCount": 0, "candidatesTokenCount": 0, "totalTokenCount": 0},
  "modelVersion": output.model_name or req_model
}
```
- 图片下载用库自带 `Image.save(bytes_mode=True)` 或等价方式；失败的单张图片跳过并记 warn，不中断整个响应。

### 4. `auth.py`
```python
def require_api_key(x_goog_api_key: str | None = Header(None),
                    key: str | None = Query(None)):
    provided = x_goog_api_key or key
    allowed = settings.api_keys
    if not allowed:           # 空列表 = 关闭鉴权
        return
    if not provided or not any(hmac.compare_digest(provided, k) for k in allowed):
        raise HTTPException(401, detail={"error": {"code": 401, "status": "UNAUTHENTICATED", "message": "Invalid API key"}})
```

### 5. `routes/generate.py`
- `POST /v1beta/models/{model}:generateContent` → `require_api_key` → 调 `service.generate` → converter → JSON
- `POST /v1beta/models/{model}:streamGenerateContent` → `StreamingResponse(media_type="text/event-stream")`
  - 每个 `ModelOutput` 序列化为完整 `GenerateContentResponse` JSON（**增量快照语义**，对齐 Google）
  - 每帧 `data: {json}\n\n`
  - 末帧附 `finishReason=STOP`
  - 中途异常：`yield data: {"error": {...}}\n\n` 后关闭连接

### 6. `routes/health.py`
- `/healthz`：固定返回 200 `{"status":"ok"}`
- `/readyz`：`service.is_running && (now - last_refresh_ok_at) < 2*refresh_interval` → 200，否则 503

### 7. `errors.py`
自定义异常 → Google 风格：
```json
{"error": {"code": <http>, "status": "<GOOGLE_STATUS>", "message": "..."}}
```
映射表：
| 异常 | HTTP | status |
|---|---|---|
| `HTTPException(401)` | 401 | UNAUTHENTICATED |
| Pydantic ValidationError | 400 | INVALID_ARGUMENT |
| `ModelNotFoundError` | 404 | NOT_FOUND |
| `gemini_webapi.AuthError` | 503 | UNAVAILABLE |
| `gemini_webapi.APIError` / TimeoutError | 502 / 504 | INTERNAL / DEADLINE_EXCEEDED |
| 上传体过大 | 413 | INVALID_ARGUMENT |

---

## Dockerfile 关键点

```dockerfile
FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 \
    GEMINI_COOKIE_PATH=/data/cookies \
    CONFIG_PATH=/config/config.yaml
WORKDIR /app
COPY pyproject.toml README.md ./
COPY src ./src
COPY server ./server
RUN pip install --no-cache-dir ".[server]"
RUN mkdir -p /data/cookies /config
VOLUME ["/data", "/config"]
EXPOSE 8080
HEALTHCHECK --interval=30s --timeout=3s --retries=3 \
  CMD python -c "import urllib.request,sys;sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8080/healthz').status==200 else 1)"
CMD ["uvicorn", "server.main:app", "--host", "0.0.0.0", "--port", "8080", "--workers", "1"]
```

## docker-compose.yml

```yaml
services:
  gemini-api:
    build:
      context: ..
      dockerfile: docker/Dockerfile
    image: gemini-api-gateway:latest
    container_name: gemini-api
    restart: unless-stopped
    ports:
      - "8080:8080"
    volumes:
      - ./config.yaml:/config/config.yaml
      - ./data:/data
    environment:
      - CONFIG_PATH=/config/config.yaml
      - GEMINI_COOKIE_PATH=/data/cookies
```

---

## 测试策略

- `test_converters.py`：构造 `ModelOutput`、`GenerateContentRequest` 固定数据，纯函数断言；包括 systemInstruction 拼接、inline_data 解码、多图输出。
- `test_config_store.py`：`tmp_path` 写示例 yaml → 并发 10 个 `asyncio.gather` 调 `update_psidts` → 断言最终文件可被 YAML 再次解析、`secure_1psidts` 值合法、注释保留。
- `test_auth.py`：`FastAPI TestClient`，分别测空 allowlist、缺 header、错 key、正确 key、query `?key=`。
- `test_routes.py`：monkey-patch `GeminiService`（用真实 `ModelOutput` 对象），断言路由返回结构、流式分帧、错误映射。
- **smoke（手动）**：`docker compose up -d`，用用户示例 curl 打两个路径，用一张真实图片 base64 进行 inline_data 输入测试。

---

## 关键文件索引（修改/新增）

| 类型 | 路径 | 说明 |
|---|---|---|
| 新增 | `server/**/*.py` | 整个服务层 |
| 新增 | `docker/Dockerfile` | 单阶段镜像 |
| 新增 | `docker/docker-compose.yml` | 开发/生产编排 |
| 新增 | `config.example.yaml` | 用户复制为 `config.yaml` |
| 新增 | `tests/server/*` | 单元 + 路由测试 |
| 修改 | `pyproject.toml` | `[project.optional-dependencies].server` |
| 修改 | `.gitignore` | 忽略 `config.yaml`、`data/` |
| 修改 | `README.md` | 追加 "Run as a Docker service" 小节（简短指引） |

复用上游（**不改动**）：
- `src/gemini_webapi/client.py:71` `GeminiClient` 类
- `src/gemini_webapi/client.py:319-355` 自动刷新任务
- `src/gemini_webapi/utils/rotate_1psidts.py:109-144` `save_cookies` 持久化
- `src/gemini_webapi/constants.py:95-142` `Model` 枚举（透传模型名）
- `src/gemini_webapi/types/image.py` `Image.save` 下载

---

## 已知风险 / 取舍

1. **库刷新静默失败**：`start_auto_refresh` 错误只记 warn；通过监听 cookie 缓存 mtime 变化判断成功，失败会让 `readyz` 变红但不阻塞请求。
2. **config.yaml 被重写的格式扰动**：`ruamel.yaml` round-trip 能保留大多数注释/空行，但极端格式可能轻微变动；README 提示用户保留备份。
3. **`generationConfig` 被忽略**：本期不做翻译，避免语义错位。
4. **图片下载拖慢 TTFB**：接受；流式路径先吐文字，末帧带图。
5. **跨进程并发写**：本期单 worker 不会触发，但预留 `fcntl.flock` 以防未来变更。

---

## 验证方法（End-to-End）

1. `cp config.example.yaml config.yaml` 并填入有效 PSID/PSIDTS/api_key
2. `docker compose -f docker/docker-compose.yml up -d --build`
3. `curl http://localhost:8080/healthz` → 200
4. `curl http://localhost:8080/readyz` → 待初始化完成后 200
5. 用用户提供的示例 curl（把 host 换成 `localhost:8080`，模型可用 `gemini-3-pro`）跑通文本请求
6. 构造带 `inline_data` 的请求上传一张图 + 文字提示，断言响应中有文字+图片 base64
7. 访问 `:streamGenerateContent`，`curl -N` 观察多帧 SSE
8. 删除宿主机 `data/cookies/*.json`，观察容器内刷新仍能维持（初始值取自 config.yaml）
9. 停止并重启容器，`config.yaml` 中的 `secure_1psidts` 应已被更新为最新值
10. 运行 `pytest tests/server/` 全部通过

---

## 后续（本次不做）

- 多账号轮询
- OpenAPI schema 暴露给官方 Gemini SDK 验证
- `countTokens` / `GET /v1beta/models`
- Prometheus `/metrics`
- 容器化镜像瘦身（multi-stage build + `pip install --no-deps` 精简）
- IP 白名单、QPS 限流
