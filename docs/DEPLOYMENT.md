# AG Punjab AI Pension Portal: Production Deployment Guide

| | |
|---|---|
| **System** | AG Punjab AI Pension Portal + GP Fund module |
| **Document owner** | TMC: Ahmed Raza |
| **Version** | 1.1 (5 Oct 2026): code fixes F1–F10 done, `deploy/` files added |
| **Covers** | (A) LAN deployment inside the AG office and (B) public / internet deployment |

This guide covers what the system is made of, what you need before deploying, and the
steps for each kind of deployment, from an empty server to go-live. Part 3 applies to both
deployment types. Part 4 is LAN only, and Part 5 adds what a public deployment needs.

---

## Contents

1. [What is being deployed](#1-what-is-being-deployed)
2. [What we need](#2-what-we-need)
3. [Common steps (LAN and public)](#3-common-steps-lan-and-public)
4. [Option A: LAN deployment](#4-option-a--lan-deployment)
5. [Option B: Public deployment](#5-option-b--public-deployment)
6. [Data migration: trial to production](#6-data-migration--trial-to-production)
7. [Backups and restore](#7-backups-and-restore)
8. [Verification and go-live checklist](#8-verification-and-go-live-checklist)
9. [Day-to-day operations](#9-day-to-day-operations)
10. [Known pitfalls](#10-known-pitfalls)
11. [Appendix: reference configuration](#11-appendix--reference-configuration)

---

## 1. What is being deployed

### 1.1 Components

| # | Component | What it does | Runs as | Port | Exposed to users? |
|---|---|---|---|---|---|
| 1 | **Portal server** (`api.portal_server`) | Serves the built web UI (`portals/dist`) and forwards `/api/*` to the API and `/gpf/*` to GP Fund | Python | 5184 | **Yes, through nginx only** |
| 2 | **Pension API** (`api.server`) | Case system, logins, rules engine, AI pipeline orchestration, SQLite DB | Python / FastAPI / uvicorn | 8110 | No |
| 3 | **GP Fund backend** (`GP/backend`) | GP Fund pre-audit module (second product) | Python / FastAPI | 8201 | No |
| 4 | **Vision model** Qwen3-VL-30B-A3B-FP8 | Classifies pages and extracts fields | vLLM | 8011 | No |
| 5 | **OCR model** PaddleOCR-VL 1.6 | Reads scanned text | vLLM | 8012 | No |
| 6 | **Embedding model** Qwen3-Embedding-4B | Rules/RAG search | vLLM | 8093 | No |
| 7 | **Reranker** Qwen3-Reranker-4B | Rules/RAG ranking | vLLM (Spark-1 today) | 8094 | No |
| 8 | **Database** | PostgreSQL 16 (`PENSION_DATABASE_URL`), schema migrations `api/migrations/0001…0011` (+ `postgres/` overrides); SQLite file only where there is no PostgreSQL | postgres | 5432 (loopback) | No |
| 9 | **Case files** | Uploaded scans + per-run outputs (`artifacts/run-*`, `artifacts/cases`) | files | — | No |

### 1.2 How the parts connect

```
   Users (AG office / 86 departments)
                │  HTTPS 443
                ▼
        ┌───────────────┐
        │     nginx     │  TLS, rate limits, upload size, security headers
        └───────┬───────┘
                │ http 127.0.0.1:5184
                ▼
        ┌───────────────┐   /api/*   ┌──────────────┐
        │ Portal server │ ─────────▶ │ Pension API  │──▶ PostgreSQL, case files
        │   (5184)      │            │   (8110)     │
        └───────┬───────┘            └──────┬───────┘
                │ /gpf/*                    │ AI pipeline
                ▼                           ▼
        ┌───────────────┐        ┌──────────────────────────────┐
        │  GP Fund API  │───────▶│ vLLM models 8011/8012/8093/  │
        │   (8201)      │        │ 8094 (GPU box, private only) │
        └───────────────┘        └──────────────────────────────┘
```

**Rule:** the only thing users ever reach is nginx on port 443. Ports 5184, 8110 and 8201,
and the model ports, stay closed to everyone else.

### 1.3 How it runs today (trial), and why that isn't production

| Today (trial) | Production |
|---|---|
| Started by `./run.sh` with `nohup`; dies on reboot | systemd services, auto-restart, start on boot |
| Runs out of `~/Desktop/pension`, mixed with test PDFs, backups, logs | Clean release folder `/opt/pension`, data in `/var/lib/pension` |
| Every password is `1234` | Unique password per user, changed at first login |
| Plain HTTP on high ports | HTTPS on 443 behind nginx |
| No version control | Git repository, tagged releases, rollback |
| Manual DB copies | Nightly automated off-box backups |
| Model addresses hard-coded to `192.168.1.1` | Configurable per environment (see §3.1) |

---

## 2. What we need

### 2.1 Approvals and decisions (before any technical work)

| # | Item | From whom | Why |
|---|---|---|---|
| D1 | **Hosting approval**: where pension data may live (AG office server room, PITB / government data centre, or the TMC GPU box) | AG Punjab IT / PITB | The system holds CNICs, pay records, family details and signatures. Government data hosting rules apply. |
| D2 | **Access model**: LAN only, LAN + VPN for departments, or public internet | AG Punjab | Decides between Option A and Option B |
| D3 | **Domain name**, e.g. `pension.agpunjab.gov.pk` (public) or `pension.agpunjab.local` (LAN) | AG IT / PITB / NTC | Needed for HTTPS |
| D4 | **TLS certificate**: internal CA (LAN) or public certificate (Let's Encrypt or government CA) | AG IT | HTTPS |
| D5 | **Data decision**: start with an empty DB, or carry over trial cases | AG Punjab | §6 |
| D6 | **User list**: real names, roles (AG desks, DDOs per department, admin) | AG Punjab | Replaces the shared `1234` trial accounts |
| D7 | **Backup destination**: second server / NAS / government backup | AG IT | §7 |
| D8 | **Named operator(s)** who run the server after handover | AG IT + TMC | §9 |

### 2.2 Hardware

| Role | Minimum | What we run today | Notes |
|---|---|---|---|
| **GPU / model server** | NVIDIA GPU with ≥ 96 GB memory (unified or VRAM), 16+ cores, 128 GB RAM | NVIDIA GB10 (DGX Spark class), 121 GB unified memory, 20 cores | Vision (~0.35 of memory) + OCR + embedding must fit together. Do **not** co-host other large models (an OOM freeze happened on 15 Jul 2026). |
| **Second GPU box** (optional) | as above | Spark-1, 192.168.101.10 (reranker) | Can be folded into the main box if memory allows |
| **App server** | 8 cores, 16 GB RAM, 1 TB SSD | Same GPU box today | Can be the GPU box (simplest) or a separate VM that calls the GPU box over the LAN |
| **Storage** | 1 TB+ for case files, growing | `artifacts/` is ~6.2 GB on the trial data | Plan ~50–100 MB per case (scans + page images) |
| **Backup storage** | 2× the data size | — | Separate machine |
| **UPS** | Enough for a clean shutdown | — | A power cut during a write can damage SQLite |

### 2.3 Software

| Item | Version used | Notes |
|---|---|---|
| OS | Ubuntu 24.04 LTS | |
| Python | 3.12 | |
| Python packages (API) | fastapi 0.136, uvicorn 0.51, Pillow 12.3, PyJWT, aiohttp, sse-starlette, python-multipart | Put them in a dedicated venv (`/opt/pension/venv`), **not** the shared `vllm_env` |
| Python packages (GP) | `GP/backend/requirements.txt` | Same or separate venv |
| vLLM + CUDA | as in `/home/tmc/vllm_env` | Models only |
| Model weights | `qwen3-vl-30b-a3b-fp8`, `paddleocr-vl-1.6`, `qwen3-embedding-4b`, `qwen3-reranker-4b` | Today on the `/models` NFS mount. Production should keep a **local copy** on the GPU box. |
| poppler-utils | `pdftoppm`, `pdfinfo` | PDF → page images |
| LibreOffice (headless) | | Converts Word/other uploads to PDF |
| Node.js | 24.x | **Build machine only**, to build `portals/dist`. Not needed on the server. |
| nginx | distro package | Reverse proxy + TLS |
| git | | Release control |
| PostgreSQL 16 | server + client (`postgresql-16`, `postgresql-client-16`), or the `postgres:16` container (`deploy/docker-compose.postgres.yml`) | The database; `pg_dump` for backups |
| sqlite3 CLI | | Only to read an old trial file for `python3 -m api.db import-sqlite` |

### 2.4 Network

| Item | LAN | Public |
|---|---|---|
| Static internal IP for the server | Required | Required |
| Internal DNS record | Required | Optional |
| Public static IP or government hosting | — | Required |
| Firewall rules | 443 from office subnets | 443 from internet; everything else closed |
| VPN server (WireGuard / IPsec) | Optional (for departments) | Recommended for admin access |
| Outbound internet from server | Not needed (models run offline) | Only for certificate renewal and OS updates |

### 2.5 People

| Role | Responsibility |
|---|---|
| TMC developer | Code fixes (§3.0), release build, first install, handover |
| AG IT / system admin | Server, network, firewall, DNS, certificate, backups, user accounts |
| AG business owner | Approvals D1–D8, user list, acceptance sign-off |
| Desk users (pilot group) | Acceptance testing with real cases |

---

## 3. Common steps (LAN and public)

### 3.0 Code changes required before production: done (5 Oct 2026)

All nine are in the code, each covered by `tests/test_production_hardening.py`, and checked
over real HTTP on a release unpacked and run in production mode. They take effect when the
deployment sets **`PENSION_ENV=production`** (`api/settings.py`). Without it the trial on this
box behaves as before, so preparing the deployment does not disturb the pilot.

| # | Change | What was done |
|---|---|---|
| F1 | **Per-user passwords, changed at first sign-in** | New column `must_change_password` (migration 0009). In production, every password the seed or the administrator sets must be replaced at first sign-in. Until it is, the account can only read who it is and change its password; everything else returns 403. The portal shows a "Choose your own password" screen. Password rule: 10+ characters in production (8 in the trial); refuses common passwords (`1234`, `password`, `Pension2026!`…) and anything containing the username. `PENSION_SEED_PASSWORD` is ignored and `set-all-passwords` is refused in production. At production start-up, every account still on `1234` / its username is flagged automatically. |
| F2 | **Desk taken from the login** | On the older `/api/*` routes the desk must be one the signed-in **account** holds (`api/desks.py` `ACCOUNT_DESKS`: Pension Wing → Auditor/Determining/DAG; admin → System/Reference admin; DDO → submitter). The officer recorded is the account's name, never one typed into the request. Note: those routes were already admin-only for changes and read-only for the AG reviewer, so a DDO could never act there; the gap was the admin claiming any desk and any name. |
| F3 | **No API description pages** | `/docs`, `/redoc`, `/openapi.json` are off in production, for the pension API and GP Fund. nginx blocks them as well. |
| F4 | **Model addresses from settings** | `PENSION_VISION_URL`, `PENSION_OCR_URL`, `PENSION_EMBED_URL`, `PENSION_RERANK_URL`; defaults unchanged. |
| F5 | **Login protection** | Kept: 5 failures per username + address → 60 s lock. Added: 30 failures from one address across all usernames → 15 min lock (stops one password being tried on all 88 accounts). Fixed: the portal server believed `X-Forwarded-For` from anyone, so a caller could give itself a fresh address to escape the lock. It now believes it only from `PENSION_TRUSTED_PROXIES` (default `127.0.0.1`, the local nginx). |
| F6 | **Audit log** | Every sign-in (`LOGIN`), refused sign-in (`LOGIN_FAILED` / `LOGIN_LOCKED`, with the name typed and the address) and every change on the older routes (`V1_DECISION`, `V1_RECOMPUTE`, `V1_RULE_CONFIRM`…) is written to the append-only `audit_log`. Case actions and user administration were already logged. |
| F7 | **Trial artefacts out** | In production `/start.html` (the open password sheet), `/__portals` and the admin credentials route return 404. New `python3 -m api.db forget-credentials` deletes the sheet once passwords are handed out; production start-up warns while it exists. `deploy/build-release.sh` packs a fixed list of folders and **refuses** to build if a PDF, database, credentials file, `.zip`/`.rar` or dump is in it. |
| F8 | **Upload checks** | Already present: content-signature check, 256 MB per file, 512 MB per upload, 40 files, zip-bomb and zip-slip protection. Added: RIFF accepted only as WEBP (not WAV/AVI), `BM` only as `.bmp`, `.txt/.csv` must actually be text, PDFs over `PENSION_MAX_PAGES` (500) refused. |
| F9 | **Listen addresses** | `PENSION_PORTAL_BIND` (production default `127.0.0.1`) and `GPF_BIND` for GP Fund. The API was already loopback-only. |
| F10 | **GP Fund pass-through** (found while doing F2) | `/gpf/*` on the portal passed requests to GP Fund **with no sign-in at all**: anyone who could reach :5184 could read and change GP Fund cases and scans. The AG's GP Fund case screen shows the module's own page in a frame through `/gpf/`, so it can't simply be switched off (that blanked the screen for an hour on 5 Oct). Now every `/gpf/` request needs a GP-Fund-only sign-in cookie that the portal sets for AG and administrator accounts. It lasts 2 hours, is sent only to `/gpf`, can't be read by page scripts or sent by other sites, and opens no other route; the API confirms each one. `PENSION_GPF_PROXY=open` drops the check for a closed demo, and is ignored in production. GP Fund itself listens on 127.0.0.1:8201 by default (`GPF_BIND`). **The officer is the login's:** the portal server tells GP Fund which officer is signed in (`X-GPF-Officer`, a browser's copy is dropped), and every GP Fund action is recorded under it, whatever the page sends (AG reviewer → `ao`, admin → `dag`). The officer picker is locked. The "Open in the module" link is removed, because GP Fund's full page shows every case and its own intake outside the portal. Live in the trial since 5 Oct 2026. |

### 3.1 Prepare the release (on the build machine)

1. **Put the project under git** (it isn't today):
   ```bash
   cd ~/Desktop/pension
   git init
   # .gitignore: artifacts/, **/node_modules/, **/__pycache__/, *.pdf, *.rar, *.zip,
   #             *.sql, portals/dist*, GP/backend/data/, GP/logs/
   git add . && git commit -m "Baseline before production"
   ```
2. **Build the release** with the script, which runs every test suite (pension, GP engine,
   GP backend), builds the portal, packs a fixed list of folders and refuses trial files:
   ```bash
   deploy/build-release.sh 1.0.0          # -> dist-release/pension-1.0.0.tgz + .sha256
   ```
   What goes in: `api/ rules/ pipeline/ extraction/ rag/ config/ portals/dist/ GP/backend/{gpf,web}`,
   `deploy/` (env template, systemd units, nginx config), `docs/DEPLOYMENT.md`, pinned
   `requirements.txt`, and the rules search index `artifacts/rag/index.json`. About 3.4 MB.
3. Tag it in git: `git tag v1.0.0`.

### 3.2 Prepare the server

```bash
# OS packages
sudo apt update && sudo apt install -y python3.12-venv poppler-utils libreoffice-core \
     libreoffice-writer nginx postgresql-16 postgresql-client-16 git ufw
# The database and its owner (PostgreSQL listens on 127.0.0.1 only by default; keep it so)
sudo -u postgres psql -c "CREATE ROLE pension LOGIN PASSWORD '<long random password>'" \
                      -c "CREATE DATABASE pension OWNER pension ENCODING 'UTF8'" 

# Service account; the app never runs as a personal user
sudo useradd --system --home /opt/pension --shell /usr/sbin/nologin pension

# Folders
sudo mkdir -p /opt/pension /var/lib/pension/{artifacts,gpf} /var/log/pension /etc/pension
sudo chown -R pension:pension /var/lib/pension /var/log/pension
sudo chmod 750 /var/lib/pension /etc/pension
```

| Path | Contents | Owner |
|---|---|---|
| `/opt/pension/releases/v1.0.0/` | Unpacked release (read-only) | root |
| `/opt/pension/current` → `releases/v1.0.0` | Symlink; switching it = upgrade/rollback | root |
| `/opt/pension/venv/` | Python virtualenv | root |
| `/var/lib/pension/artifacts/` | DB, case files, run outputs, `.jwt_secret` | pension |
| `/var/lib/pension/gpf/` | GP Fund data | pension |
| `/etc/pension/pension.env` | Secrets and settings (mode 640) | root:pension |
| `/var/log/pension/` | Logs | pension |

### 3.3 Install the application

```bash
sudo tar xzf pension-v1.0.0.tgz -C /opt/pension/releases/
sudo ln -sfn /opt/pension/releases/pension-1.0.0 /opt/pension/current
sudo python3 -m venv /opt/pension/venv
sudo /opt/pension/venv/bin/pip install -r /opt/pension/current/requirements.txt
```

The code keeps its data under `<code>/artifacts`. Move the release's copy (the rules search
index) to the data folder the first time, then point the release at it:
```bash
sudo rsync -a /opt/pension/current/artifacts/ /var/lib/pension/artifacts/   # first install only
sudo chown -R pension:pension /var/lib/pension
sudo rm -rf /opt/pension/current/artifacts
sudo ln -sfn /var/lib/pension/artifacts /opt/pension/current/artifacts
```
Set `PENSION_DATABASE_URL` to the database created in §3.2 (`postgresql://pension:<password>@127.0.0.1:5432/pension`).
`PENSION_DB` only matters when the URL is unset: then the API runs on a SQLite file, which production should not.

### 3.4 Configure: `/etc/pension/pension.env`

Start from `deploy/pension.env.example`, which has every value below. The important ones:

| Variable | Production value | Notes |
|---|---|---|
| `PENSION_ENV` | `production` | **The switch** for F1–F10 (§3.0) |
| `PENSION_API_BIND` | `127.0.0.1` | API never listens on the network |
| `PENSION_DATABASE_URL` | `postgresql://pension:<password>@127.0.0.1:5432/pension` | **The database** (9 Oct 2026). The venv needs `psycopg[binary]` (`deploy/requirements.txt`) |
| `PENSION_DB` | unset | SQLite fallback, used only when the URL is unset |
| `PENSION_JWT_SECRET` | 64+ random characters (`openssl rand -base64 48`) | If you change it, everyone has to sign in again |
| `PENSION_SEED_PASSWORD` | **unset** | Seed accounts must not get a shared password (F1) |
| `PENSION_CORS_ORIGINS` | `https://pension.agpunjab.local` (or the public domain) | Exact origin only |
| `PENSION_PUBLIC_HOST` | the domain name | Used in links the system generates |
| `PENSION_PORTAL_DIST` | `/opt/pension/current/portals/dist` | |
| `PENSION_API_URL` | `http://127.0.0.1:8110` | |
| `PENSION_GPF_URL` | `http://127.0.0.1:8201` | |
| `PENSION_PORTAL_BIND` | `127.0.0.1` | Default in production; nginx is the only way in (F9) |
| `PENSION_TRUSTED_PROXIES` | `127.0.0.1` | Whose `X-Forwarded-For` is believed: the nginx (F5) |
| `PENSION_GPF_PROXY` | unset | `/gpf/` requires the signed-in frame cookie (F10); never `open` |
| `PENSION_VISION_URL` / `_OCR_URL` / `_EMBED_URL` / `_RERANK_URL` | model server addresses | F4 |
| `PENSION_MAX_PAGES` | `500` | Pages one uploaded PDF may have (F8) |
| `PENSION_DEPARTMENT_PORTS` | unset / `0` | One portal with logins (per-department ports stay off) |
| `PENSION_TRUST_PORT_HEADER` | **unset** | Test-only switch; ignored in production anyway |
| `PENSION_API_DOCS` | **unset** | `1` would bring `/docs` back |
| `PENSION_IMPORT_LEGACY` | unset | One-time import only |
| `GPF_DB` | the same URL as `PENSION_DATABASE_URL` | Shared database (migration 0005) |
| `GPF_DATA_DIR` | `/var/lib/pension/gpf` | |
| `GPF_VLLM_URL(S)` | model server address | |

```bash
sudo chown root:pension /etc/pension/pension.env && sudo chmod 640 /etc/pension/pension.env
```

### 3.5 Model server

On the GPU box (the same machine or a separate one):

1. **Copy the weights locally** (e.g. `/srv/models/…`), so the services don't depend on the NFS
   mount from `spark-46ef`. Check them against the fingerprints in `infra/models/`.
2. **The model key** (audit 6 Oct 2026, item 7). Create `/etc/pension/models.env` from
   `deploy/models.env.example` (`VLLM_API_KEY=` 48+ random characters, `root:tmc`, mode 640) and
   put the **same value** in `/etc/pension/pension.env` as `PENSION_MODEL_API_KEY`. The vision,
   OCR and embedding servers bind **127.0.0.1** and refuse any `/v1` request without the key; the
   launchers refuse to start without one. `run.sh` and `GP/backend/run.sh` read it from
   `models.env` themselves.
3. Install the units from the release's `infra/` (`vllm-qwen3-vl.service`, `paddleocr-vl.service`,
   `qwen3-embedding.service`) into `/etc/systemd/system/`. They run the launchers and the warm-up
   from `/opt/pension/current/infra/`, never from a developer's folder. If the weights move off
   `/models`, edit `MODEL_PATH` and the `ExecStartPre` waits.
4. **Startup order matters** (see §10): vision → OCR → embedding → reranker, each waiting for the
   previous `/health`. The units already carry `ExecStartPre`/`ExecStartPost` waits. Keep them.
5. **Keep the vision warm-up** (`warmup-vision.sh` as `ExecStartPost`). Without it, the first
   extraction after a restart returns empty amounts.
6. Do not enable `qwen3guard.service`. Nothing calls it, and it takes GPU memory the pipeline needs.
7. Firewall: with the models on the app server nothing outside needs the model ports; if they
   run on a separate GPU box, set `HOST` to its LAN address and allow only the app server's IP.

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now vllm-qwen3-vl paddleocr-vl qwen3-embedding qwen3-reranker
curl -s http://127.0.0.1:8011/health && curl -s http://127.0.0.1:8012/health \
  && curl -s http://127.0.0.1:8093/health && echo models OK
```

### 3.6 Application services (systemd)

Install the three units from `deploy/systemd/` (`pension-api`, `pension-portal`, `pension-gpf`), then:

```bash
sudo cp /opt/pension/current/deploy/systemd/pension-*.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now pension-api pension-gpf pension-portal
systemctl status pension-api pension-gpf pension-portal --no-pager
curl -s http://127.0.0.1:8110/api/health
curl -s http://127.0.0.1:8201/api/health        # check "mode": "vllm", not stub
curl -s -o /dev/null -w '%{http_code}\n' http://127.0.0.1:5184/      # 200
```

The API applies the migrations in `api/migrations/` on startup (0009 is the latest at v1.0.0).
On first start it seeds the 88 accounts with generated passwords and writes them once to
`/var/lib/pension/artifacts/credentials/credentials.csv` (readable by the service account only).

### 3.7 Create real user accounts

1. Read the admin's generated password from `credentials.csv` on the server
   (`sudo -u pension cat /var/lib/pension/artifacts/credentials/credentials.csv`). Sign in; the
   portal makes you choose your own password before anything else.
2. Create each user from the agreed list (D6): AG desks, DDO per department, admin.
3. Give each user their one-time password through a separate channel (not the same email as the
   link). The portal makes them choose their own at first sign-in (F1).
4. Disable every seeded account that isn't on the list.
5. Once every password is handed out: `sudo -u pension /opt/pension/venv/bin/python3 -m api.db
   forget-credentials` (run from `/opt/pension/current`, with the env file loaded).

### 3.8 nginx (both options)

Use `deploy/nginx/pension.conf` (site) and `deploy/nginx/pension-proxy.conf` (copy to
`/etc/nginx/snippets/`). Common points:
- `client_max_body_size 520m;` (the API's own limits are 256 MB a file, 512 MB an upload)
- `proxy_read_timeout 600s;` and `proxy_buffering off` for the live progress stream (SSE)
- Security headers: HSTS, `X-Content-Type-Options`, `X-Frame-Options`, `Referrer-Policy`
- Block `/docs`, `/redoc`, `/openapi.json`, `/__portals` and `/start.html` at nginx as a second safety layer. Do **not** block `/gpf/`: the AG's GP Fund screen needs it, and the portal checks the sign-in there.

---

## 4. Option A: LAN deployment

**Who uses it:** AG office staff on the office network. Departments either come to the
office network or connect over a VPN (§4.4).

### 4.1 Extra requirements

- Static IP on the office LAN, e.g. `10.x.x.x`
- Internal DNS record: `pension.agpunjab.local → <server IP>`
- Certificate from the AG internal CA, or a self-made CA whose root is installed on office PCs
  (group policy). Avoid "click through the warning" self-signed setups, because they train users
  to ignore real warnings.

### 4.2 Steps

| Step | Action | Done by |
|---|---|---|
| A1 | Approvals D1, D2 (LAN), D3, D4, D6, D7 | AG |
| A2 | Code fixes F1–F10: **done 5 Oct 2026** (§3.0); set `PENSION_ENV=production` | TMC |
| A3 | Build and test the release (§3.1) | TMC |
| A4 | Prepare the server (§3.2) and install (§3.3) | TMC + AG IT |
| A5 | Configure `pension.env` (§3.4) | TMC |
| A6 | Model services up and warm (§3.5) | TMC |
| A7 | App services up (§3.6) | TMC |
| A8 | nginx + internal certificate (§3.8, §11.1) | AG IT |
| A9 | Firewall (§4.3) | AG IT |
| A10 | Internal DNS record | AG IT |
| A11 | Data migration decision applied (§6) | TMC |
| A12 | Real user accounts (§3.7) | AG admin |
| A13 | Backups scheduled and one restore tested (§7) | AG IT |
| A14 | Verification checklist (§8) | TMC + AG |
| A15 | Pilot with one section and a few departments for 1–2 weeks | AG |
| A16 | Go-live sign-off | AG |

### 4.3 Firewall (LAN)

```bash
sudo ufw default deny incoming
sudo ufw default allow outgoing
sudo ufw allow from <office-subnet>/24 to any port 443 proto tcp
sudo ufw allow from <admin-subnet>/24 to any port 22 proto tcp
# Model server only (if separate): allow 8011,8012,8093,8094 from the app server IP only
sudo ufw enable
```

### 4.4 Departments over a VPN (recommended for the 86 departments)

This lets departments in other offices use the LAN deployment without making it public.

- **WireGuard** server on the AG edge (or the server itself). Each department PC/user gets its
  own key, and keys are revoked when staff change.
- The VPN gives access to **port 443 on the portal only**, nothing else on the AG network.
- Share the DNS name over the VPN (or a hosts entry), so the URL stays the same everywhere.
- Keep a register of VPN keys mapped to department and person.

---

## 5. Option B: Public deployment

**Who uses it:** anyone with a login, from any network. Do all of Option A, plus everything
below. **Do not start Option B until D1 hosting approval is in writing.** (Code fixes F1–F10 are done, §3.0.)

### 5.1 Where to host

| Choice | Pros | Cons |
|---|---|---|
| **PITB / government data centre** (recommended) | Meets government data policy, managed firewall/DDoS, `.gov.pk` domain | Lead time; GPU availability must be confirmed |
| **AG office server + public static IP** | Data stays in the AG building | AG must run the firewall, patching and monitoring; link speed |
| **Split**: web front in the data centre, GPU box stays in the office over a site-to-site VPN | No public exposure of the GPU box | More moving parts |
| ~~Tunnel services (e.g. Cloudflare Tunnel)~~ | Quick | Pension data passes through a foreign third party. Avoid unless explicitly approved. |

### 5.2 Extra requirements

- Public domain (`pension.agpunjab.gov.pk`) and DNS A record → public IP
- Public TLS certificate (Let's Encrypt with auto-renewal, or a government CA)
- DDoS / WAF protection if the host offers it
- A security review / penetration test before go-live (PITB normally requires one)
- An incident contact and a plan for what happens if data leaks

### 5.3 Steps (in addition to A1–A16)

| Step | Action | Done by |
|---|---|---|
| B1 | Written hosting approval (D1) and access approval (D2 = public) | AG / PITB |
| B2 | **All code fixes F1–F10**: done 5 Oct 2026 (§3.0); penetration test still to confirm them | TMC |
| B3 | Server at the chosen host; only port 443 (and 80 for redirect / certificate renewal) open | Host / AG IT |
| B4 | GPU/model server **not** on a public IP. Reach it over a private network or VPN only. | AG IT |
| B5 | Public DNS + public certificate with auto-renewal (`certbot --nginx`) | AG IT |
| B6 | nginx hardened (§5.4) | TMC + AG IT |
| B7 | SSH: keys only, no passwords, no root login, from the VPN / admin IPs only | AG IT |
| B8 | fail2ban on SSH and on portal login failures | AG IT |
| B9 | Automatic security updates (`unattended-upgrades`) | AG IT |
| B10 | Monitoring + alerting (§9.3) | AG IT |
| B11 | Penetration test, then fix the findings and re-test | PITB / third party |
| B12 | Staged rollout: AG office → 5 departments → all 86 | AG |

### 5.4 Extra nginx hardening (public)

```nginx
# Login: 5 attempts per minute per IP
limit_req_zone $binary_remote_addr zone=login:10m rate=5r/m;
# General API: 20 req/s per IP
limit_req_zone $binary_remote_addr zone=api:10m rate=20r/s;

location = /api/v2/auth/login { limit_req zone=login burst=5 nodelay; proxy_pass http://pension_portal; }
location /api/ { limit_req zone=api burst=40; proxy_pass http://pension_portal; }

# Never expose these publicly
location ~ ^/(docs|redoc|openapi\.json|__portals|start\.html) { return 404; }

server_tokens off;
add_header Content-Security-Policy "default-src 'self'; img-src 'self' data: blob:; style-src 'self' 'unsafe-inline'; font-src 'self' data:" always;
```
(`/api/v2/auth/login` is the login route in `api/v2.py`.)

### 5.5 Data protection (public)

- HTTPS only; HTTP redirects to HTTPS; HSTS on
- Disk encryption on the data volume (LUKS), or the host's encrypted storage
- Encrypted backups (§7)
- Logins expire after 12 hours (current `TOKEN_TTL`). Consider shorter idle timeouts for AG desks.
- Departments see only their own cases (already the design); verify it in the pen test
- Departments see no AI output (already the design); verify it in the pen test

---

## 6. Data migration: trial to production

**Option 1: Fresh start (recommended).** Production begins with an empty database. The API
creates the schema and departments on first start. Trial cases stay on the trial box for
reference and training.

**Option 2: Carry over selected cases.**
1. Stop the trial API (check that no run is active first; see §10).
2. Make a consistent copy: `pg_dump -Fc "$PENSION_DATABASE_URL" > /tmp/portal-export.dump` (trial box on
   PostgreSQL), or `sqlite3 artifacts/portal.sqlite3 ".backup /tmp/portal-export.sqlite3"` for a trial that
   was still on the file.
3. Copy the matching `artifacts/run-*` and `artifacts/cases/*` folders.
4. On production: `pg_restore -d "$PENSION_DATABASE_URL" --no-owner /tmp/portal-export.dump` into the empty
   database -- or, from a SQLite file, `python3 -m api.db import-sqlite /tmp/portal-export.sqlite3`
   (migrates first, copies every table in foreign-key order, refuses a non-empty target without `--replace`);
   files into `/var/lib/pension/artifacts/`, `chown -R pension:pension`.
5. Start the API (migrations apply), then run `python3 -m api.check_inventory`. Every view must
   agree.
6. **Remove all trial user accounts** and reset any account that is kept.
7. Delete test/fake cases (e.g. PC-2026-000030..32 trial cases) unless the AG wants them kept.

---

## 7. Backups and restore

### 7.1 What to back up

| Item | Path | How often |
|---|---|---|
| Database | PostgreSQL `pension` (`pg_dump -Fc`) | Nightly + before every upgrade |
| Case files / run outputs | `/var/lib/pension/artifacts/` (rest) | Nightly (incremental) |
| GP Fund data | `/var/lib/pension/gpf/` | Nightly |
| Config + secrets | `/etc/pension/`, `/etc/nginx/sites-available/pension`, systemd units | On change |
| JWT secret | `PENSION_JWT_SECRET` in `/etc/pension/pension.env` (production refuses to start without one of 32+ characters) | On change |

### 7.2 Nightly backup script (sketch)

```bash
#!/usr/bin/env bash
# /usr/local/bin/pension-backup  (cron: 30 2 * * *)
set -euo pipefail
STAMP=$(date +%F)
DEST=/var/backups/pension/$STAMP
mkdir -p "$DEST"
# A consistent snapshot of the database, whatever is being written meanwhile
set -a; . /etc/pension/pension.env; set +a
pg_dump -Fc "$PENSION_DATABASE_URL" > "$DEST/portal.dump"
pg_restore --list "$DEST/portal.dump" >/dev/null          # the archive reads back
rsync -a --exclude 'portal.sqlite3*' /var/lib/pension/ "$DEST/files/"
tar czf - -C /etc pension | gpg --encrypt -r backup@agpunjab > "$DEST/etc.tgz.gpg"
# Off-box copy
rsync -a --delete "$DEST" backup-host:/backups/pension/
# Keep 30 daily locally
find /var/backups/pension -maxdepth 1 -type d -mtime +30 -exec rm -rf {} +
```

Retention: 30 daily, 12 monthly, plus whatever the AG records policy requires.

### 7.3 Restore (test this once before go-live, then every quarter)

```bash
sudo systemctl stop pension-portal pension-gpf pension-api
set -a; . /etc/pension/pension.env; set +a
pg_restore -d "$PENSION_DATABASE_URL" --clean --if-exists --no-owner /var/backups/pension/<date>/portal.dump
sudo rsync -a /var/backups/pension/<date>/files/ /var/lib/pension/
sudo systemctl start pension-api pension-gpf pension-portal
python3 -m api.check_inventory
```

---

## 8. Verification and go-live checklist

### 8.1 Technical

- [ ] All tests pass on the release (`tests/`, GP backend, GP engine)
- [ ] `systemctl status` shows all services active; they come back after `sudo reboot`
- [ ] `/api/health` OK; GP Fund health shows `mode: vllm` (not stub)
- [ ] All model `/health` endpoints OK; first extraction after a restart returns real amounts (warm-up worked)
- [ ] `python3 -m api.check_inventory` reports no differences
- [ ] HTTPS works with no browser warning; HTTP redirects to HTTPS
- [ ] `pip install PyJWT==2.15.0` into the services' venv (the pin in `requirements.txt`; done on the trial box 6 Oct 2026, verified 7 Oct), then restart `pension-api`, `pension-portal` and `pension-gpf`
- [ ] Model units run with `--host 127.0.0.1` and `VLLM_API_KEY` set (`infra/*.service` from the release, §3.5); `ss -ltnp` shows 8011, 8012, 8093 on `127.0.0.1` only. Until then `lock-model-ports.sh` (installed at `/usr/local/sbin`, `pension-model-ports.service`) is the stop-gap
- [ ] Ports 5184, 8110, 8201, 8011, 8012, 8093, 8094 are **not** reachable from a user PC (`nmap` from outside)
- [ ] `/docs`, `/openapi.json`, `/__portals`, `start.html` return 404 from outside
- [ ] No account uses `1234`; trial accounts removed; `credentials.csv` not on the server
- [ ] Backup ran; restore tested on a scratch machine
- [ ] Upload of a 100 MB scan bundle works; live progress (SSE) updates in the browser

### 8.2 Functional (with real users)

- [ ] AG desk, DDO and admin can each sign in, and each sees only what their role allows
- [ ] A DDO sees only their own department's cases and **no AI output**
- [ ] One self-pension case end to end: DDO files → AG Verify → auto-return or approve
- [ ] One family-pension case end to end
- [ ] One GP Fund case end to end (`#/gpf`)
- [ ] Missing-document auto-return works; flags show for AG
- [ ] Declared case type mismatch is flagged
- [ ] Pension section filters/sidebar match the AG's sections

### 8.3 Sign-off

| | Name | Date | Signature |
|---|---|---|---|
| AG business owner | | | |
| AG IT | | | |
| TMC | | | |

---

## 9. Day-to-day operations

### 9.1 Upgrades (new release)

1. Build and test the new release (§3.1) and tag it (`v1.1.0`).
2. Announce a short maintenance window. **Check that no AI run is in progress** first.
3. Back up the DB (`pension-backup`).
4. Unpack to `/opt/pension/releases/pension-1.1.0`, install requirements, re-create the
   `artifacts` symlink.
5. `sudo ln -sfn /opt/pension/releases/pension-1.1.0 /opt/pension/current`
6. `sudo systemctl restart pension-api pension-gpf pension-portal`
7. Check health + one case. **Rollback:** point the symlink back to the previous release,
   restore the pre-upgrade DB if a migration ran, and restart.

### 9.2 Logs

```bash
journalctl -u pension-api -f
journalctl -u pension-portal -u pension-gpf --since today
journalctl -u vllm-qwen3-vl --since "1 hour ago"
```
Rotate with journald limits (`SystemMaxUse=2G`) or logrotate for `/var/log/pension`.

### 9.3 Monitoring and alerts

Check every 1–5 minutes and alert the operator (email/SMS/WhatsApp) when something fails:
- `https://<domain>/api/health` returns 200
- Model health endpoints 8011 / 8012 / 8093 / 8094
- Disk space on `/var/lib/pension` (alert at 80%)
- GPU memory / free system memory (alert when free memory < 10 GB)
- Certificate expiry (alert 21 days before)
- Last backup age (alert if > 26 h)

Tools: Uptime Kuma (simple, self-hosted), or Prometheus + Grafana + node_exporter if the AG
already runs them.

### 9.4 Routine tasks

| When | Task |
|---|---|
| Daily | Check alerts; check the backup succeeded |
| Weekly | Review failed logins / locked accounts; check disk growth |
| Monthly | OS security updates (non-automatic ones) in a maintenance window; review user list (leavers) |
| Quarterly | Restore test; certificate and VPN key review |
| On staff change | Disable the account and VPN key the same day |

---

## 10. Known pitfalls

These come from running the trial. Each one has already caused a problem.

| Problem | What happens | Prevention |
|---|---|---|
| **Model boot race** | After a reboot, OCR and embedding fail (negative KV cache) because all models grab memory at once | Start models **one at a time**, each waiting for the previous `/health` (systemd `After=` + `ExecStartPre` waits) |
| **GP Fund in stub mode** | If GP Fund starts before the models are up, it falls back to stub mode and reads nothing | Order `pension-gpf` after the model units; check health shows `mode: vllm`; restart GP Fund if not |
| **Cold vision model** | First extraction after a restart returns all amounts empty | Keep `warmup-vision.sh` as `ExecStartPost` |
| **Restarting mid-run** | Restarting the API kills an AI run in progress; the officer's case is left half-done | Before any restart, check for active runs (health `runs` counts all runs, not active ones; check the run list) |
| **Process manager kills jobs under memory pressure** | Long jobs started from a shell die when memory runs low | Run everything under systemd, never from a terminal session |
| **Co-hosting other GPU models** | Unified memory OOM froze the box on 15 Jul 2026 | Model server runs this system's models only; `qwen3guard` stays disabled |
| **Copying database files** | Copying PostgreSQL's data directory (or, before 9 Oct 2026, a live SQLite file) while it is written gives a corrupt backup | Always `pg_dump` (§7.2) |
| **Weights on NFS** | Model services fail at boot if the NFS mount from `spark-46ef` isn't ready | Local copy of weights on the GPU box |
| **Hard-coded model IPs** | Moving the GPU box breaks reading silently | Fix F4 before moving any machine |
| **Other projects on the same box** | `pkill`-style commands have taken down a colleague's service (:5173, :8100, :8200) | On a dedicated production server this goes away; until then, only stop services by systemd unit name |

---

## 11. Appendix: reference configuration

### 11.1 Files in `deploy/`

The reference configuration lives in the repository, so it is versioned with the code and goes
into every release. This guide no longer copies it, so the two cannot drift apart.

| File | Goes to | What it is |
|---|---|---|
| `deploy/build-release.sh` | (build machine) | Tests, portal build, fixed-list packing, trial-file refusal |
| `deploy/requirements.txt` | `/opt/pension/current/requirements.txt` | Pinned runtime packages |
| `deploy/pension.env.example` | `/etc/pension/pension.env` | Every setting, production values, `CHANGE_ME` where a value must be supplied |
| `deploy/systemd/pension-api.service` | `/etc/systemd/system/` | Pension API on 127.0.0.1:8110 |
| `deploy/systemd/pension-gpf.service` | `/etc/systemd/system/` | GP Fund on 127.0.0.1:8201, ordered after the vision model |
| `deploy/systemd/pension-portal.service` | `/etc/systemd/system/` | Portal server on 127.0.0.1:5184 |
| `deploy/nginx/pension.conf` | `/etc/nginx/sites-available/pension` | TLS, rate limits, blocked paths |
| `deploy/nginx/pension-proxy.conf` | `/etc/nginx/snippets/` | Proxy headers, SSE, timeouts |

### 11.4 Quick reference: ports

| Port | Service | Listens on | Who may connect |
|---|---|---|---|
| 443 | nginx (HTTPS) | all | Users (LAN / VPN / internet) |
| 80 | nginx (redirect) | all | Users (redirect only), certbot |
| 22 | SSH | all | Admin IPs / VPN only |
| 5184 | Portal server | 127.0.0.1 | nginx |
| 8110 | Pension API | 127.0.0.1 | Portal server |
| 8201 | GP Fund | 127.0.0.1 | Portal server, API |
| 8011 | Vision model | GPU box | App server only |
| 8012 | OCR model | GPU box | App server only |
| 8093 | Embedding | GPU box | App server only |
| 8094 | Reranker | GPU box | App server only |

### 11.5 One-page summary

**LAN:** approvals → `deploy/build-release.sh` (fixes F1–F10 done) → server + venv → env file →
models (in order, warmed) → systemd services → nginx + internal certificate → firewall (443 from
office only) → DNS → real accounts → backups + restore test → checklist → pilot → sign-off.
Departments join over a **VPN**.

**Public:** everything in LAN, **plus** written hosting approval → government
or approved hosting → GPU box kept private → public DNS + certificate → hardened nginx (rate
limits, blocked endpoints, CSP) → SSH keys only + fail2ban → auto security updates → monitoring
→ **penetration test** → staged rollout.
claude --resume 2be051e8-ab19-4ca4-8921-c4f1ca72d781