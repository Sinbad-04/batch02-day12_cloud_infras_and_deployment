# Solution — Day 12 Code Lab: Deploy Your AI Agent to Production

> AICB-P1 · VinUniversity 2026
> Học viên: Giap
> Đáp án codelab Part 1 → Part 5 (+ Final Project & Bonus CI/CD)

---

## Part 1: Localhost vs Production

### Exercise 1.1 — Phát hiện anti-patterns (`01-localhost-vs-production/develop/app.py`)

Tìm được **7 vấn đề** trong file basic:

| # | Anti-pattern | Dòng | Hậu quả |
|---|--------------|------|---------|
| 1 | API key + DATABASE_URL **hardcode** trong code | 17–18 | Push lên GitHub là lộ secret ngay; không rotate được |
| 2 | **Không có config management** — `DEBUG`, `MAX_TOKENS` cứng trong code | 21–22 | Muốn đổi giữa dev/prod phải sửa code & build lại |
| 3 | Dùng `print()` thay vì logging | 33, 38 | Không có level, không structured, khó parse trong log aggregator |
| 4 | **Log ra secret** (`print(... OPENAI_API_KEY)`) | 34 | Secret rò rỉ vào log files |
| 5 | **Không có health check** endpoint | 42 | Platform không biết khi nào container chết để restart |
| 6 | **Port cố định**, không đọc từ `PORT` env | 45, 52 | Railway/Render inject `PORT` động → app không nhận traffic |
| 7 | `host="localhost"` + `reload=True` trong "production" | 51, 53 | `localhost` không nhận kết nối ngoài container; `reload` tốn RAM, không an toàn |

### Exercise 1.2 — Chạy basic version

```bash
cd 01-localhost-vs-production/develop
pip install -r requirements.txt
python app.py
curl -X POST "http://localhost:8000/ask?question=hello"
# → {"answer": "...mock response..."}
```

**Quan sát:** Nó *chạy* được nhưng không production-ready: secret nằm trong source, không có `/health`, bind `localhost`, không đọc `PORT`. Hễ đưa lên cloud là fail.

### Exercise 1.3 — So sánh basic vs advanced

| Feature | Basic (`develop`) | Advanced (`production`) | Tại sao quan trọng |
|---------|-------------------|--------------------------|--------------------|
| **Config** | Hardcode trong code | `config.py` đọc từ env vars (12-Factor) | Secret tách khỏi code; đổi môi trường không cần build lại; fail-fast nếu thiếu config bắt buộc (`validate()` raise nếu thiếu `AGENT_API_KEY` ở production) |
| **Health check** | ❌ Không có | ✅ `/health` (liveness) + `/ready` (readiness) + `/metrics` | Platform tự restart container chết; load balancer chỉ route traffic khi `/ready` = 200 |
| **Logging** | `print()` raw, log cả secret | JSON structured (`logging.basicConfig` format JSON), không log secret | Parse được bởi Datadog/Loki/CloudWatch; truy vết theo `event`, `client_ip`, `question_length` mà không lộ nội dung nhạy cảm |
| **Shutdown** | Đột ngột (Ctrl-C) | Graceful: `lifespan` + handler `SIGTERM` (dòng 177–186) | Hoàn thành request đang xử lý trước khi tắt → không mất dữ liệu / không trả lỗi 502 cho user khi deploy/scale |
| **Network bind** | `host="localhost"` | `host="0.0.0.0"` từ `settings.host` | `0.0.0.0` mới nhận được kết nối từ ngoài container |
| **Port** | Cứng `8000` | `settings.port` từ env `PORT` | Railway/Render/Cloud Run inject `PORT` động |
| **CORS** | ❌ Không có | ✅ `CORSMiddleware` với `allowed_origins` cấu hình được | Kiểm soát domain nào được gọi API |

### Checkpoint 1 ✅
- **Hardcode secret nguy hiểm** vì: commit là vĩnh viễn trong git history (kể cả sau khi xóa), lộ với bất kỳ ai có quyền đọc repo, không rotate được mà không sửa code.
- **Environment variables**: tách config khỏi code, mỗi môi trường (dev/staging/prod) chỉ khác về env, cùng một artifact (image) chạy mọi nơi.
- **Health check**: cho phép orchestrator phân biệt "process còn sống" (liveness) với "sẵn sàng nhận traffic" (readiness — đã connect xong DB/Redis).
- **Graceful shutdown**: nhận `SIGTERM` → ngừng nhận request mới → chờ request đang chạy xong → đóng connection → exit.

---

## Part 2: Docker Containerization

### Exercise 2.1 — Dockerfile cơ bản (`02-docker/develop/Dockerfile`)

1. **Base image:** `python:3.11` — bản full (~1 GB), kèm toàn bộ build tools.
2. **Working directory:** `/app` (`WORKDIR /app`).
3. **Tại sao COPY requirements.txt trước:** tận dụng **Docker layer cache**. Layer `pip install` chỉ rebuild khi `requirements.txt` đổi. Nếu copy cả source trước, mỗi lần sửa code đều phải cài lại toàn bộ dependencies → build chậm.
4. **CMD vs ENTRYPOINT:**
   - `CMD` = lệnh mặc định, **dễ bị override** khi `docker run image <lệnh khác>`.
   - `ENTRYPOINT` = lệnh **cố định**, các tham số `docker run` được *append* vào nó.
   - Pattern phổ biến: `ENTRYPOINT ["python"]` + `CMD ["app.py"]` → chạy `python app.py` mặc định, nhưng `docker run img other.py` thành `python other.py`.

### Exercise 2.2 — Build & run

```bash
# Từ project root
docker build -f 02-docker/develop/Dockerfile -t my-agent:develop .
docker run -p 8000:8000 my-agent:develop
docker images my-agent:develop
```

**Quan sát image size:** base `python:3.11` → image ≈ **1.0–1.1 GB**. To vì chứa cả compiler, headers, công cụ build không cần lúc runtime.

### Exercise 2.3 — Multi-stage build (`02-docker/production/Dockerfile`)

- **Stage 1 (`builder`):** dùng `python:3.11-slim`, cài `gcc`, `libpq-dev`, rồi `pip install --user` dependencies vào `/root/.local`. Stage này chứa build tools — **không deploy**.
- **Stage 2 (`runtime`):** lại từ `python:3.11-slim` sạch, chỉ `COPY --from=builder /root/.local ...` (copy đúng packages đã build) + source code. Không có gcc, không có header.
- **Tại sao image nhỏ hơn:** image cuối chỉ giữ những gì cần để **chạy**, bỏ hết những gì chỉ cần để **build**. Từ ~1 GB xuống **~150–250 MB**.
- **Điểm cộng security:** tạo non-root user (`appuser`), `USER appuser`, thêm `HEALTHCHECK`, chạy `uvicorn ... --workers 2`.

```bash
docker build -f 02-docker/production/Dockerfile -t my-agent:advanced .
docker images | grep my-agent   # so sánh: advanced nhỏ hơn develop ~4-6x
```

### Exercise 2.4 — Docker Compose stack (`02-docker/production/docker-compose.yml`)

**Architecture diagram:**

```
            Client (port 80/443)
                  │
            ┌─────▼─────┐
            │   nginx   │  reverse proxy + LB + rate limit + security headers
            └─────┬─────┘
                  │  (network: internal)
            ┌─────▼─────┐
            │   agent   │  FastAPI (target: runtime), healthcheck /health
            └──┬─────┬──┘
               │     │
       ┌───────▼─┐ ┌─▼────────┐
       │  redis  │ │  qdrant  │   cache/rate-limit + vector DB (RAG)
       │ (volume)│ │ (volume) │
       └─────────┘ └──────────┘
```

- **Services start:** `nginx`, `agent`, `redis`, `qdrant`.
- **Communicate thế nào:** tất cả ở chung network `internal` (bridge), gọi nhau bằng **service name** làm DNS hostname: agent → `redis://redis:6379`, `http://qdrant:6333`; nginx → `agent:8000`. Chỉ `nginx` expose ra ngoài (80/443); agent **không** expose port trực tiếp → mọi traffic đi qua nginx.
- `depends_on ... condition: service_healthy` → agent chỉ start sau khi redis & qdrant healthy.
- Secret để trong `.env.local` (gitignore), không hardcode trong compose.

### Checkpoint 2 ✅
- Cấu trúc Dockerfile: `FROM` → `WORKDIR` → `COPY deps` → `RUN install` → `COPY code` → `CMD`.
- Multi-stage: tách build-time khỏi run-time → image nhỏ, sạch, an toàn.
- Compose orchestration: nhiều service, network nội bộ, service discovery bằng tên, healthcheck + dependency ordering.
- Debug container: `docker logs <id>`, `docker exec -it <id> /bin/sh`, `docker compose ps`.

---

## Part 3: Cloud Deployment

### Exercise 3.1 — Railway (`03-cloud-deployment/railway/`)

```bash
npm i -g @railway/cli
railway login
railway init
railway variables set PORT=8000 AGENT_API_KEY=my-secret-key
railway up
railway domain        # lấy public URL
```

Test:
```bash
curl https://<your-app>.up.railway.app/health
curl -X POST https://<your-app>.up.railway.app/ask \
  -H "Content-Type: application/json" -d '{"question":"hello"}'
```

`railway.toml`: builder `NIXPACKS`, `startCommand = uvicorn app:app --host 0.0.0.0 --port $PORT`, `healthcheckPath=/health`, restart `ON_FAILURE` (max 3).

### Exercise 3.2 — Render (`03-cloud-deployment/render/render.yaml`)

**So sánh `render.yaml` vs `railway.toml`:**

| Tiêu chí | `railway.toml` | `render.yaml` |
|----------|----------------|----------------|
| Định dạng | TOML | YAML (Blueprint spec) |
| Phạm vi | Chỉ 1 service | **Multi-service** (web `ai-agent` + `redis` add-on) trong cùng file |
| Build | `NIXPACKS` auto-detect | `buildCommand: pip install -r requirements.txt` |
| Start | `startCommand` | `startCommand` (giống nhau) |
| Health check | `healthcheckPath` | `healthCheckPath` |
| Secret | Set qua CLI/Dashboard | `sync: false` (nhập tay) hoặc `generateValue: true` (Render tự sinh `AGENT_API_KEY`) |
| Auto deploy | Mặc định khi push | `autoDeploy: true` tường minh |
| Region | Mặc định | Chỉ định được (`singapore`) |

→ `render.yaml` thiên về **Infrastructure-as-Code đầy đủ** (khai báo cả Redis + region + cách sinh secret), `railway.toml` gọn nhẹ hơn cho 1 service.

### Exercise 3.3 — GCP Cloud Run (`production-cloud-run/`)

**`cloudbuild.yaml` — CI/CD pipeline 4 step** (chạy khi push `main`):
1. `test` — `pip install` + `pytest tests/`.
2. `build` — `docker build` 2 tag (`$COMMIT_SHA` + `latest`), `--cache-from latest` để cache layer. `waitFor: [test]`.
3. `push` — đẩy image lên Container Registry. `waitFor: [build]`.
4. `deploy` — `gcloud run deploy` region `asia-southeast1`, `--allow-unauthenticated`, `--min-instances=1` (tránh cold start), `--max-instances=10`, secret từ **Secret Manager** (`--set-secrets`). `waitFor: [push]`.

**`service.yaml`** — Cloud Run Service (Knative): `minScale=1`, `maxScale=10`, `containerConcurrency=80`, `livenessProbe → /health`, `startupProbe → /ready`, env secret qua `secretKeyRef`. Đây là cách khai báo IaC để `gcloud run services replace`.

### Checkpoint 3 ✅
- Deploy 1 platform → có public URL.
- Set env vars: Railway `railway variables set`, Render Dashboard/`render.yaml`, Cloud Run `--set-env-vars` / Secret Manager.
- Xem logs: `railway logs`, Render Dashboard → Logs, `gcloud run services logs read`.

---

## Part 4: API Security

### Exercise 4.1 — API Key authentication (`04-api-gateway/develop/app.py`)

- **Key được check ở đâu:** dependency `verify_api_key()` (dòng 39) đọc header `X-API-Key` qua `APIKeyHeader`, inject vào `/ask` bằng `Depends(verify_api_key)`.
- **Sai/thiếu key:**
  - Thiếu key → **401** `Missing API key`.
  - Sai key → **403** `Invalid API key`.
- **Rotate key:** key đọc từ env `AGENT_API_KEY` → đổi giá trị env + restart, không sửa code. (Tốt hơn nữa: hỗ trợ danh sách nhiều key để rotate không downtime.)

```bash
# Thiếu key → 401
curl -X POST http://localhost:8000/ask -H "Content-Type: application/json" -d '{"question":"Hi"}'
# Có key → 200
curl -X POST http://localhost:8000/ask -H "X-API-Key: demo-key-change-in-production" \
  -H "Content-Type: application/json" -d '{"question":"Hi"}'
```

### Exercise 4.2 — JWT authentication (`04-api-gateway/production/auth.py`)

**JWT flow:**
1. `POST /token` với username/password → `authenticate_user()` kiểm tra `DEMO_USERS`.
2. `create_token()` sinh JWT ký bằng `SECRET_KEY` (HS256), payload `{sub, role, iat, exp}`, hết hạn sau 60 phút.
3. Client gửi `Authorization: Bearer <token>` → `verify_token()` decode + verify signature → trả `{username, role}` **không cần query DB** (stateless).
4. Lỗi: hết hạn → 401 `Token expired`; sai chữ ký → 403 `Invalid token`; không có token → 401.

```bash
TOKEN=$(curl -s -X POST http://localhost:8000/token -H "Content-Type: application/json" \
  -d '{"username":"student","password":"demo123"}' | jq -r .access_token)
curl -X POST http://localhost:8000/ask -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" -d '{"question":"Explain JWT"}'
```

**API key vs JWT:** API key = bí mật tĩnh, đơn giản, hợp B2B/internal nhưng khó phân quyền & hết hạn. JWT = stateless, mang `role`/`exp`, tự hết hạn, phân quyền theo claim — hợp app nhiều user.

### Exercise 4.3 — Rate limiting (`04-api-gateway/production/rate_limiter.py`)

- **Algorithm:** **Sliding Window Counter** — mỗi user một `deque` timestamp; loại các timestamp ngoài window 60s; đếm số còn lại.
- **Limit:** user **10 req/60s**, admin **100 req/60s** (hai instance singleton `rate_limiter_user`, `rate_limiter_admin`).
- **Vượt limit:** raise **429** kèm header `X-RateLimit-Limit/Remaining/Reset` và `Retry-After`.
- **Bypass cho admin:** route theo `role` từ JWT → dùng `rate_limiter_admin` (limit cao hơn).
- **Lưu ý production:** in-memory deque **không scale** qua nhiều instance → cần Redis (`INCR` + `EXPIRE`, hoặc sorted-set sliding window).

### Exercise 4.4 — Cost guard (`04-api-gateway/production/cost_guard.py`)

`cost_guard.py` đã implement đầy đủ:
- Tính cost theo token: input `$0.00015/1K`, output `$0.0006/1K` (GPT-4o-mini).
- **Per-user budget** `$1/ngày` → vượt raise **402 Payment Required**; **global budget** `$10/ngày` → vượt raise **503**.
- Cảnh báo (`logger.warning`) khi đạt **80%** budget.
- Reset theo ngày (`day` so với `time.strftime("%Y-%m-%d")`).

Bản Redis (theo gợi ý đề, budget tháng `$10`):
```python
import redis
from datetime import datetime
r = redis.Redis()

def check_budget(user_id: str, estimated_cost: float) -> bool:
    month_key = datetime.now().strftime("%Y-%m")
    key = f"budget:{user_id}:{month_key}"
    current = float(r.get(key) or 0)
    if current + estimated_cost > 10:
        return False
    r.incrbyfloat(key, estimated_cost)
    r.expire(key, 32 * 24 * 3600)   # tự xóa sau ~1 tháng
    return True
```
Dùng Redis vì state phải **share** giữa các instance và **bền** qua restart (in-memory mất khi container restart và mỗi instance đếm riêng).

### Checkpoint 4 ✅
- API key auth qua header + `Depends`.
- JWT: login → token có `exp`/`role` → verify signature stateless.
- Rate limit sliding window (Redis cho production).
- Cost guard với Redis, key theo `user:tháng`, TTL tự reset.

---

## Part 5: Scaling & Reliability

### Exercise 5.1 — Health checks

```python
@app.get("/health")          # Liveness — process còn sống?
def health():
    return {"status": "ok"}

@app.get("/ready")           # Readiness — sẵn sàng nhận traffic?
def ready():
    if USE_REDIS:
        try:
            _redis.ping()    # check dependency thật
        except Exception:
            raise HTTPException(503, "Redis not available")
    return {"ready": True}
```
**Khác biệt:** `/health` chỉ xác nhận process chạy (fail → platform **restart**); `/ready` kiểm tra dependency (Redis/DB) (fail → load balancer **ngừng route** traffic, nhưng không restart). Tách ra để tránh restart vô ích khi chỉ là dependency tạm chậm.

### Exercise 5.2 — Graceful shutdown

```python
import signal, sys

def shutdown_handler(signum, frame):
    logger.info("SIGTERM received — draining...")
    # 1. Set flag is_ready=False → /ready trả 503 → LB ngừng gửi request mới
    # 2. uvicorn ngừng nhận connection mới, chờ in-flight requests xong
    # 3. Đóng Redis/DB connections
    # 4. sys.exit(0)
    sys.exit(0)

signal.signal(signal.SIGTERM, shutdown_handler)
```
Trong lab, bản advanced dùng `lifespan` (`asynccontextmanager`): block sau `yield` chạy lúc shutdown để cleanup; uvicorn chạy với `timeout_graceful_shutdown=30`. Container orchestrator gửi `SIGTERM` rồi chờ (grace period) trước khi `SIGKILL`.

### Exercise 5.3 — Stateless design (`05-scaling-reliability/production/app.py`)

**Anti-pattern:** lưu `conversation_history = {}` trong RAM. Khi scale 3 instance, request user A lần 2 có thể vào instance khác → mất history.

**Đúng (stateless):** mọi state để Redis. Lab dùng `save_session`/`load_session`/`append_to_history` với key `session:{id}` + TTL 3600s. Response trả `served_by: INSTANCE_ID` để chứng minh **bất kỳ instance nào** cũng phục vụ được vì state nằm ở Redis chứ không ở memory. Có fallback in-memory khi không có Redis (kèm cảnh báo "not scalable").

### Exercise 5.4 — Load balancing (`05-scaling-reliability/production/docker-compose.yml` + `nginx.conf`)

```bash
docker compose up --scale agent=3
```
- 3 instance `agent` (compose `replicas: 3`, mỗi instance limit 0.5 CPU / 256M), chung network, **không** expose port.
- `nginx` (port 8080→80) làm load balancer **round-robin** giữa các instance qua `upstream agent_backend`.
- 1 instance chết → healthcheck fail → nginx route sang instance khác → **không downtime**.

```bash
for i in {1..10}; do
  curl -s -X POST http://localhost:8080/chat -H "Content-Type: application/json" \
    -d '{"question":"Request '$i'"}' | jq .served_by
done   # → thấy served_by xoay vòng giữa các instance
```

### Exercise 5.5 — Test stateless (`test_stateless.py`)

Script gửi 5 request cùng `session_id` tới `http://localhost:8080`:
1. Tạo session, gửi liên tiếp 5 câu hỏi.
2. In `served_by` mỗi request → có thể là instance khác nhau.
3. Cuối cùng `GET /chat/{session_id}/history` → **đủ cả 10 message** (5 user + 5 assistant) dù được phục vụ bởi nhiều instance → chứng minh state nằm ở Redis, không mất khi đổi instance.

### Checkpoint 5 ✅
- `/health` (liveness) + `/ready` (readiness check Redis).
- Graceful shutdown qua `lifespan` + `SIGTERM` + grace period.
- Stateless: session/history trong Redis, không trong RAM.
- Load balancing nginx round-robin, tự bỏ instance unhealthy.
- `test_stateless.py` xác nhận history liên tục khi scale.

---

## Part 6: Final Project (`06-lab-complete/`)

Project `06-lab-complete` đã hội đủ checklist production:

| Yêu cầu | Hiện thực trong repo |
|---------|----------------------|
| Config từ env (12-Factor) | `app/config.py` (dataclass + `os.getenv`, `validate()` fail-fast ở production) |
| API key auth | `verify_api_key()` header `X-API-Key` → 401 nếu sai |
| Rate limiting | `check_rate_limit()` sliding window, `RATE_LIMIT_PER_MINUTE` |
| Cost guard | `check_and_record_cost()`, `DAILY_BUDGET_USD`, vượt → 503 |
| Health / Readiness | `GET /health`, `GET /ready` (`_is_ready`) |
| Graceful shutdown | `lifespan` + `SIGTERM` handler + `timeout_graceful_shutdown=30` |
| JSON logging | `logging.basicConfig` format JSON + middleware log mỗi request |
| Input validation | Pydantic `AskRequest` (`min_length=1, max_length=2000`) |
| Security headers / CORS | middleware set `X-Content-Type-Options`, `X-Frame-Options`; `CORSMiddleware` |
| Docker multi-stage, non-root | `Dockerfile` (builder + runtime, user `agent`, `HEALTHCHECK`) |
| Deploy config | `railway.toml`, `render.yaml`, `docker-compose.yml` (agent + redis) |
| Validation script | `check_production_ready.py` |

Chạy & validate cục bộ:
```bash
cd 06-lab-complete
docker compose up --build
curl http://localhost:8000/health
curl -X POST http://localhost:8000/ask -H "X-API-Key: dev-key-change-me" \
  -H "Content-Type: application/json" -d '{"question":"Hello"}'
python check_production_ready.py
```

> **Lab Assignment (deliverable #2):** thư mục `06-lab-complete` cần được thay bằng dự án Agent cá nhân/nhóm từ các buổi trước, áp dụng đúng các bước productionization ở trên, deploy lên Railway/Render và ghi lại Public URL:
>
> - **Public API URL:** `__________________________` *(điền sau khi deploy)*
> - **Platform:** Railway / Render *(chọn)*
> - **Health check:** `<url>/health` → 200

---

## Bonus — CI/CD bằng GitHub Actions

File workflow đã tạo tại `.github/workflows/deploy.yml`:
- **CI:** lint (`ruff`) + test có coverage (`pytest --cov`).
- **CD:** build và deploy tự động lên Railway/Render khi push `main`.

Chi tiết & yêu cầu secret xem ngay trong file workflow.
