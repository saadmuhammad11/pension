# Go-live runbook — AG Punjab pension case system

Release: `fix/high-findings` at the commit named in step 2, tagged `v1.0.0`. This is the ordered,
exact procedure; the background for each step is in `docs/DEPLOYMENT.md` (§ references below).
Steps marked **[sudo]** need root on the machine named. Everything else runs as the deploying user
(build box) or as the `pension` service account (production).

Two machines are named: the **build box** (this trial machine, `~/Desktop/pension`) and the
**production server** (`/opt/pension`, service account `pension`). Where the GPU models run on a
separate box, steps 10 and 15 run there.

**Rule for every restart:** no AI run may be in progress (§10). Check first:

```bash
# on the box whose API is about to stop; 0 = safe
sqlite3 "file:$DB?mode=ro" "SELECT COUNT(*) FROM case_runs WHERE state IN ('queued','running')"
```
(`$DB` is `artifacts/portal.sqlite3` on the trial box, `/var/lib/pension/artifacts/portal.sqlite3`
on production.) `/api/health`'s `runs` field counts every run ever, not active ones.

---

## Part A — on the build box

### 1. Back up the current (trial) database and data, before anything else

```bash
cd ~/Desktop/pension
test "$(sqlite3 'file:artifacts/portal.sqlite3?mode=ro' "SELECT COUNT(*) FROM case_runs WHERE state IN ('queued','running')")" = 0
STAMP=$(date +%F-%H%M)
mkdir -p artifacts/backup-pre-golive-$STAMP && chmod 700 artifacts/backup-pre-golive-$STAMP
sqlite3 artifacts/portal.sqlite3 ".backup 'artifacts/backup-pre-golive-$STAMP/portal.sqlite3'"
sqlite3 artifacts/backup-pre-golive-$STAMP/portal.sqlite3 "PRAGMA integrity_check;"      # must print ok
tar czf artifacts/backup-pre-golive-$STAMP/gpf-data.tgz -C GP/backend data
chmod 600 artifacts/backup-pre-golive-$STAMP/*
```
Never `cp` the live SQLite file (§10). The backup stays inside `artifacts/` (git-ignored, owner-only);
it holds trial claimant data and must not leave the box.

### 2. Push and merge the branch

```bash
git status --short            # must be clean except untracked docs you mean to keep out
git log --oneline -1          # note the commit: this is the release
python3 -I deploy/check-release-pii.py "$(git rev-parse --show-toplevel)"/api   # sanity, exits 0
git push origin fix/high-findings
```
Open the pull request `fix/high-findings` → `main`, have it reviewed, merge it (no squash: the
one-commit-per-item history is the audit trail). Then:
```bash
git checkout main && git pull --ff-only
git tag v1.0.0 && git push origin v1.0.0
```

### 3. Rebuild the portal and build the release tarball

`deploy/build-release.sh` runs all three test suites, type-checks and rebuilds the portal bundle
(`portals/dist`), packs a fixed list of folders, and refuses the tarball if it carries a CNIC or a
trial file (§3.1). It takes about seven minutes.
```bash
git checkout v1.0.0
deploy/build-release.sh 1.0.0            # -> dist-release/pension-1.0.0.tgz and .sha256
tar tzf dist-release/pension-1.0.0.tgz | grep -E 'artifacts/run-|credentials|\.pdf$|portal\.sqlite3' && echo "REFUSE" || echo "tarball clean"
```
If any suite fails, stop: nothing is deployed from a red build.

### 4. Copy the release to the production server

```bash
scp dist-release/pension-1.0.0.tgz dist-release/pension-1.0.0.tgz.sha256 <admin>@<server>:/tmp/
```

---

## Part B — on the production server

### 5. Prepare the server **[sudo]** (first install only; §3.2)

```bash
sudo apt update && sudo apt install -y python3.12-venv poppler-utils libreoffice-core libreoffice-writer nginx sqlite3 git ufw nmap
sudo useradd --system --home /opt/pension --shell /usr/sbin/nologin pension
sudo mkdir -p /opt/pension/releases /var/lib/pension/{artifacts,gpf} /var/log/pension /etc/pension
sudo chown -R pension:pension /var/lib/pension /var/log/pension
sudo chmod 750 /var/lib/pension /etc/pension
```

### 6. Back up the production database (every upgrade; skip on the first install) **[sudo]**

```bash
sudo systemctl is-active pension-api && \
  test "$(sudo -u pension sqlite3 'file:/var/lib/pension/artifacts/portal.sqlite3?mode=ro' "SELECT COUNT(*) FROM case_runs WHERE state IN ('queued','running')")" = 0
sudo mkdir -p /var/backups/pension/pre-v1.0.0
sudo -u pension sqlite3 /var/lib/pension/artifacts/portal.sqlite3 ".backup '/var/backups/pension/pre-v1.0.0/portal.sqlite3'"
sudo sqlite3 /var/backups/pension/pre-v1.0.0/portal.sqlite3 "PRAGMA integrity_check;"
sudo rsync -a /var/lib/pension/gpf/ /var/backups/pension/pre-v1.0.0/gpf/
sudo tar czf /var/backups/pension/pre-v1.0.0/etc-pension.tgz -C /etc pension
```
This is the rollback point for step 22.

### 7. Install the release **[sudo]** (§3.3)

```bash
cd /tmp && sha256sum -c pension-1.0.0.tgz.sha256
sudo tar xzf /tmp/pension-1.0.0.tgz -C /opt/pension/releases/
sudo python3 -m venv /opt/pension/venv                      # first install only
sudo /opt/pension/venv/bin/pip install -r /opt/pension/releases/pension-1.0.0/requirements.txt
sudo /opt/pension/venv/bin/python3 -c 'import jwt; assert jwt.__version__ == "2.15.0", jwt.__version__; print("PyJWT", jwt.__version__)'
```
PyJWT 2.15.0 is pinned in `requirements.txt`; the check above is the §8.1 item. Do **not** switch
the `current` symlink yet (step 14).

First install only — move the shipped data folder to its home and point the release at it:
```bash
sudo rsync -a /opt/pension/releases/pension-1.0.0/artifacts/ /var/lib/pension/artifacts/
sudo chown -R pension:pension /var/lib/pension
```
Every install:
```bash
sudo rm -rf /opt/pension/releases/pension-1.0.0/artifacts
sudo ln -sfn /var/lib/pension/artifacts /opt/pension/releases/pension-1.0.0/artifacts
```

### 8. Configure `/etc/pension/pension.env` **[sudo]** (§3.4)

```bash
sudo cp -n /opt/pension/releases/pension-1.0.0/deploy/pension.env.example /etc/pension/pension.env
sudo chown root:pension /etc/pension/pension.env && sudo chmod 640 /etc/pension/pension.env
sudoedit /etc/pension/pension.env
```
Values that must be right (production refuses to start otherwise, or runs unsafe):

| Variable | Value |
|---|---|
| `PENSION_ENV` | `production` |
| `PENSION_JWT_SECRET` | `openssl rand -base64 48` (64+ characters; never `CHANGE_ME`) |
| `PENSION_SEED_PASSWORD` | **unset** (seeded accounts get generated passwords) |
| `PENSION_DB` | `/var/lib/pension/artifacts/portal.sqlite3` |
| `PENSION_API_BIND`, `PENSION_PORTAL_BIND` | `127.0.0.1` |
| `PENSION_TRUSTED_PROXIES` | `127.0.0.1` |
| `PENSION_CORS_ORIGINS`, `PENSION_PUBLIC_HOST` | the portal's exact origin / host name |
| `PENSION_PORTAL_DIST` | `/opt/pension/current/portals/dist` |
| `PENSION_MODEL_API_KEY` | the same value as `VLLM_API_KEY` in step 10 |
| `PENSION_VISION_URL` etc. | `http://127.0.0.1:8011`, `:8012`, `:8093` (the reranker's LAN address if remote) |
| `GPF_DB` | `/var/lib/pension/artifacts/portal.sqlite3` |
| `GPF_DATA_DIR` | `/var/lib/pension/gpf` |
| `PENSION_GPF_PROXY`, `PENSION_API_DOCS`, `PENSION_TRUST_PORT_HEADER`, `PENSION_DEPARTMENT_PORTS` | **unset** |

### 9. Model key **[sudo]** (§3.5 item 2)

```bash
sudo cp -n /opt/pension/releases/pension-1.0.0/deploy/models.env.example /etc/pension/models.env
sudo chown root:pension /etc/pension/models.env && sudo chmod 640 /etc/pension/models.env
sudoedit /etc/pension/models.env        # VLLM_API_KEY=<openssl rand -base64 48>; same value in pension.env
```
Both launchers and the model units refuse to start with the key missing, short or `CHANGE_ME`.

### 10. Keyed model units on 127.0.0.1 **[sudo]** (§3.5) — on the GPU box

Stop any model server still running from a developer's folder (on the trial box they run from
`~/Desktop/Pension-AG/infra` and `~/vllm_env`): `ps -o pid,cmd -C vllm`, then stop them by their
unit or `kill <pid>` of the `vllm serve` processes, **one box only, nothing else's**.
```bash
sudo cp /opt/pension/releases/pension-1.0.0/infra/{vllm-qwen3-vl,paddleocr-vl,qwen3-embedding,qwen3-reranker}.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now vllm-qwen3-vl          # wait for /health before the next (boot race, §10)
curl -sf http://127.0.0.1:8011/health && sudo systemctl enable --now paddleocr-vl
curl -sf http://127.0.0.1:8012/health && sudo systemctl enable --now qwen3-embedding
curl -sf http://127.0.0.1:8093/health && sudo systemctl enable --now qwen3-reranker
ss -ltnp | grep -E ':(8011|8012|8093) '              # every line must show 127.0.0.1
curl -s -o /dev/null -w '%{http_code}\n' http://127.0.0.1:8011/v1/models            # 401: the key is enforced
curl -s -o /dev/null -w '%{http_code}\n' -H "Authorization: Bearer $(sudo sed -n 's/^VLLM_API_KEY=//p' /etc/pension/models.env)" http://127.0.0.1:8011/v1/models   # 200
```
Do not enable `qwen3guard.service`. If the stop-gap `pension-model-ports.service` (nftables) is
installed on this box, leave it: it is harmless with the units on loopback.

### 11. Application units and nginx **[sudo]** (§3.6, §3.8) — install, do not start yet

```bash
sudo cp /opt/pension/releases/pension-1.0.0/deploy/systemd/pension-{api,portal,gpf}.service /etc/systemd/system/
sudo cp /opt/pension/releases/pension-1.0.0/deploy/nginx/pension-proxy.conf /etc/nginx/snippets/
sudo cp /opt/pension/releases/pension-1.0.0/deploy/nginx/pension.conf /etc/nginx/sites-available/pension
sudo ln -sfn /etc/nginx/sites-available/pension /etc/nginx/sites-enabled/pension
sudo nginx -t
sudo systemctl daemon-reload
```
Edit the server name and the certificate paths in the site file; the TLS certificate is AG IT's
(§11.1). Firewall (§4.3): `sudo ufw default deny incoming; sudo ufw allow from <office-subnet> to any port 443 proto tcp; sudo ufw allow from <admin-subnet> to any port 22 proto tcp; sudo ufw enable`.

### 12. Stop the old services, if an earlier release is running **[sudo]**

Only after the active-run check at the top of this document returned 0:
```bash
sudo systemctl stop pension-portal pension-gpf pension-api
```

### 13. Database: fresh start, or carry trial cases over (§6)

**Fresh start (recommended):** nothing to do; the API creates the schema on first start.

**Carry-over:** restore the trial backup from step 1 into `/var/lib/pension/artifacts/portal.sqlite3`
(plus the matching `artifacts/run-*` and `artifacts/cases/*` folders), `sudo chown -R pension:pension /var/lib/pension`,
and remove `-wal`/`-shm` files. Trial accounts are dealt with in step 16 either way.

### 14. Switch the release and start the API **[sudo]**

```bash
sudo ln -sfn /opt/pension/releases/pension-1.0.0 /opt/pension/current
sudo systemctl enable --now pension-api
sudo journalctl -u pension-api -n 40 --no-pager
```
On start the API applies migrations 0001–0010 (0010 adds the Deputy AG role) and seeds: the
departments' DDO accounts, the named reviewer `syed.haider` and `admin`, each with a **generated**
password, written once to `/var/lib/pension/artifacts/credentials/credentials.csv` (service account
only). On a carried-over database the shared `ag.reviewer` login is renamed in place to `syed.haider`
(same password; its sessions end).

Production refuses to start, with the reason in the journal, if: the JWT secret is missing, short
or the placeholder; a shared login (`ag.reviewer`, `dag`, `ao`, `reviewer`, `officer` ...) is
still **active**; a migration failed. Fix the cause and start again — do not work around it.

### 15. Start GP Fund and the portal **[sudo]**

```bash
curl -sf http://127.0.0.1:8093/health >/dev/null        # models up first, or GP Fund falls into stub mode (§10)
sudo systemctl enable --now pension-gpf pension-portal
curl -s http://127.0.0.1:8110/api/health                 # "ok": true; models and GP Fund not "degraded"
curl -s http://127.0.0.1:8201/api/health | grep -o '"mode": *"[a-z]*"'    # must be "vllm"
curl -s -o /dev/null -w '%{http_code}\n' http://127.0.0.1:5184/           # 200
sudo systemctl reload nginx
```
If GP Fund shows `stub`, restart `pension-gpf` once the three model health checks pass.

### 16. Accounts: no `1234`, no shared logins, the Deputy AG created

Run as the service account from the release folder with the environment loaded:
```bash
cd /opt/pension/current
alias pdb='sudo -u pension env $(sudo grep -v "^#" /etc/pension/pension.env | xargs) /opt/pension/venv/bin/python3 -m api.db'
```
1. **Carried-over database only:** every trial account is on `1234`. Do not use `set-all-passwords`
   (one shared password for everyone). Disable what is not on the agreed list, and reset the rest one by
   one with their own password: `pdb reset-password <username> "$(openssl rand -base64 12)"` (the command
   prompts if no password is given; a reset account must change it at first sign-in). Disable leftover test
   accounts (`audit.tmp1`, `audit.tmp2`, `sectest.audit`, `legacy.import`, `ahmed`) and any department
   account not on the list from the admin's Users screen (Disable, with a reason).
2. **Named reviewers:** `pdb add-reviewer <username> "<Officer's name, designation>"` for each Auditor /
   Determining Officer of the Pension Wing. The username must be a person's (`ag.reviewer`, `dag`, `ao`
   are refused).
3. **Deputy AG:** `pdb add-reviewer <username> "<Name>, Deputy Accountant General (Pension)" --dag`
   (role `AG_DAG`: the override, writes on the old register, the DAG band in GP Fund).
4. Hand each password out through a separate channel; every officer chooses their own at first
   sign-in (`must_change_password`). The administrator's own password comes from `credentials.csv`.
5. Verify, then destroy the sheet:
   ```bash
   sudo -u pension sqlite3 'file:/var/lib/pension/artifacts/portal.sqlite3?mode=ro' \
     "SELECT username, role FROM users WHERE active = 1 AND username IN ('ag.reviewer','dag','ao','reviewer','officer','auditor','ag.upload')"   # must be empty
   sudo -u pension /opt/pension/venv/bin/python3 - <<'EOF'
   import sqlite3, sys; sys.path.insert(0, "/opt/pension/current")
   from api.auth import verify_password
   con = sqlite3.connect("file:/var/lib/pension/artifacts/portal.sqlite3?mode=ro", uri=True)
   bad = [u for u, h in con.execute("SELECT username, password_hash FROM users WHERE active = 1") if verify_password("1234", h)]
   print("accounts on 1234:", bad or "none")
   EOF
   pdb forget-credentials        # removes credentials.csv and .html
   ```
6. From the browser: sign in as `admin`, Users: confirm every active account is a named person;
   the admin screen offers no case actions (G6).

### 17. §8.1 technical checklist (all must pass before any user is told)

- [ ] All tests passed on the release (step 3's build log).
- [ ] `systemctl status pension-api pension-gpf pension-portal vllm-qwen3-vl paddleocr-vl qwen3-embedding qwen3-reranker` all active; `sudo reboot` once and confirm they come back in order **[sudo]**.
- [ ] `/api/health` ok, models and GP Fund not degraded; GP Fund `mode: vllm`.
- [ ] Model `/health` endpoints ok; the first verification after the reboot reads real values (warm-up).
- [ ] Inventory check reports no difference: `PENSION_CHECK_PASSWORD=<a reviewer's and the admin's password> PENSION_CHECK_USERS=<reviewer>:AG_REVIEWER,admin:ADMIN sudo -u pension /opt/pension/venv/bin/python3 -m api.check_inventory` (run from `/opt/pension/current`; the two accounts must be on that one password for the check, so do it right after step 16 with temporary passwords, or create a check-only reviewer and disable it afterwards).
- [ ] HTTPS with no browser warning; `curl -I http://<host>/` redirects to HTTPS.
- [ ] PyJWT 2.15.0 in the venv (step 7).
- [ ] `ss -ltnp` on the server: 8011, 8012, 8093, 8110, 8201, 5184 on `127.0.0.1` only; 443 (and 22) the only listeners on the network address.
- [ ] **Outside port scan**, from a user PC on the office network, not from the server:
  ```bash
  nmap -Pn -p 22,80,443,5184,8011,8012,8093,8094,8100,8110,8200,8201,3306,3307,5672,15672 <server>
  ```
  Only 443 (and 22 from the admin subnet, 80 as a redirect if configured) may be `open`; everything else `filtered` or `closed`.
- [ ] From outside: `https://<host>/docs`, `/openapi.json`, `/__portals`, `/start.html` all 404.
- [ ] No active account verifies against `1234`; no shared login active; `credentials.csv` gone (step 16).
- [ ] Backup job installed (`/usr/local/bin/pension-backup`, §7.2) and **one restore tested on a scratch machine** (§7.3).
- [ ] A 100 MB scan bundle uploads from a department account; live progress (SSE) updates; the case goes to the AG and shows findings and no computed amount.
- [ ] A reviewer approves a case by hand; the administrator cannot (403); the Deputy AG's override works and is in the audit log under her name.

### 18. §8.2 functional checks (with real users) and §8.3 sign-off, then the pilot (A15).

---

## Part C — rollback

Use when a step 14–17 check fails and cannot be fixed in minutes. **[sudo]** throughout.

1. Check no run is active (top of this document), then `sudo systemctl stop pension-portal pension-gpf pension-api`.
2. **Code:** point `current` back at the previous release and restart:
   ```bash
   sudo ln -sfn /opt/pension/releases/<previous> /opt/pension/current
   ```
   First install (no previous release): leave the services stopped and nginx returning 503; the trial
   box is unaffected and still serves its users.
3. **Database:** migrations 0010 (role check rebuild) and any seed rename are not reversible by the
   old code, so restore the pre-upgrade backup from step 6:
   ```bash
   sudo -u pension cp /var/backups/pension/pre-v1.0.0/portal.sqlite3 /var/lib/pension/artifacts/portal.sqlite3
   sudo rm -f /var/lib/pension/artifacts/portal.sqlite3-wal /var/lib/pension/artifacts/portal.sqlite3-shm
   sudo rsync -a /var/backups/pension/pre-v1.0.0/gpf/ /var/lib/pension/gpf/
   ```
   Anything filed between the backup and the rollback is lost; say so to the departments concerned.
4. **Config:** `sudo tar xzf /var/backups/pension/pre-v1.0.0/etc-pension.tgz -C /etc` if `pension.env`
   or `models.env` were changed.
5. **Models:** the keyed units stay; they are independent of the application release. If the old
   application cannot send the key (older than 5 Oct 2026), stop the keyed units and start the previous
   launchers instead, and re-apply `sudo /usr/local/sbin/lock-model-ports.sh` so the ports stay closed
   to the network.
6. `sudo systemctl start pension-api pension-gpf pension-portal`; health checks as in step 15;
   `python3 -m api.check_inventory`.
7. Record what failed in `docs/STATUS.md` before the next attempt.

---

## Quick reference

| Step | Where | sudo | Reversible |
|---|---|---|---|
| 1 backup trial DB | build box | no | n/a |
| 2 push, merge, tag | build box | no | yes (revert) |
| 3 build release | build box | no | n/a |
| 5–11 server prep, install, config, models, units | server / GPU box | **yes** | yes |
| 12 stop old services | server | **yes** | yes |
| 13 database choice | server | yes if carrying over | via step 6 backup |
| 14–15 switch and start | server | **yes** | via Part C |
| 16 accounts | server | yes (as `pension`) | re-run |
| 17 checklist, outside scan | server + a user PC | partly | n/a |
