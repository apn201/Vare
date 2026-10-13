# Deploying Väre on an Apache server, from GitHub

The hackathon rules only ask for "a link to a functional demo application", reachable free of charge until judging ends. Any public HTTPS URL works.

Väre is one Python process (FastAPI/uvicorn) on `127.0.0.1:8765`, with Apache proxying to it. The frontend uses relative URLs, so it works at a sub-path (`/vare/`) or on its own subdomain.

Source: `https://github.com/apn201/Vare` (branch `main`). While the repo is private, git needs a GitHub personal access token with read access to it, in the environment as `GITHUB_PAT`. The token is passed per command as an HTTP header, so it is never written into `/opt/vare/.git/config` or the shell history. Once the repo is public, drop the `-c http...extraheader` part.

## Steps

1. Python 3.11+ and git on the server.
2. Clone to `/opt/vare`:
   ```bash
   AUTH=$(printf 'x-access-token:%s' "$GITHUB_PAT" | base64 -w0)
   git -c "http.https://github.com/.extraheader=AUTHORIZATION: basic $AUTH" \
       clone --branch main https://github.com/apn201/Vare.git /opt/vare
   ```
3. `python3 -m venv /opt/vare/.venv && /opt/vare/.venv/bin/pip install -r /opt/vare/requirements.txt`
4. `/opt/vare/.env`, readable only by the service user (`chmod 600`). It is gitignored, so `git pull` never touches it:
   ```
   QLOO_API_KEY=...
   QLOO_BASE_URL=https://hackathon.api.qloo.com
   LLM_API_KEY=sk-or-...
   LLM_MODEL=deepseek/deepseek-v4.1-flash
   QLOO_CACHE_PATH=var/qloo_cache.db
   ```
   `/opt/vare/var/` must exist and be writable by the service user (Qloo response cache).
   Optional limits (defaults in `.env.example`): `VARE_RUNS_PER_10MIN`, `VARE_RUNS_PER_DAY`, `VARE_LOOKUPS_PER_10MIN`, `VARE_RUNS_PER_DAY_TOTAL`, `QLOO_MONTH_RESERVE`. Limits are per client IP, read from `X-Forwarded-For` (uvicorn `--proxy-headers`, trusting Apache on 127.0.0.1), and kept in memory, which is why the service runs one worker.
5. `deploy/vare.service` -> `/etc/systemd/system/vare.service` (adjust `User=` if not `www-data`), then `systemctl daemon-reload && systemctl enable --now vare`.
6. `deploy/apache-vare.conf`: option A (sub-path) or B (subdomain). `a2enmod proxy proxy_http headers && apachectl configtest && systemctl reload apache2`.
7. Check: `curl -s https://helppox.com/vare/api/health` returns `{"status":"ok","qloo_key_set":true,"llm_key_set":true,...}`.
8. Check the MCP endpoint (what agents connect to): `/opt/vare/.venv/bin/python /opt/vare/scripts/mcp_smoke.py https://helppox.com/vare/mcp` lists four tools and calls them.
   - Sub-path setup (option A) keeps the Host header as `127.0.0.1:8765`, which the MCP endpoint accepts.
   - Subdomain setup (option B, `ProxyPreserveHost On`): add `MCP_ALLOWED_HOSTS=vare.helppox.com` to `.env`, or the endpoint answers 421 (DNS-rebinding protection).

## Updating

```bash
cd /opt/vare
AUTH=$(printf 'x-access-token:%s' "$GITHUB_PAT" | base64 -w0)
git -c "http.https://github.com/.extraheader=AUTHORIZATION: basic $AUTH" pull --ff-only origin main
/opt/vare/.venv/bin/pip install -r requirements.txt
systemctl restart vare
curl -s https://helppox.com/vare/api/health
```

## Prompt for an agent doing the deploy

> Deploy Väre from GitHub to this server at https://helppox.com/vare/. Repository: https://github.com/apn201/Vare, branch main; use your GitHub PAT as GITHUB_PAT and pass it only as an HTTP extraheader as shown in deploy/DEPLOY.md, never in the remote URL, a file, or output. Follow deploy/DEPLOY.md in the repo exactly: clone to /opt/vare, Python venv in /opt/vare/.venv, systemd unit from deploy/vare.service on 127.0.0.1:8765, Apache proxy from deploy/apache-vare.conf (option A). Create /opt/vare/.env with mode 600 from the values I give you separately; never print them, never commit them. Make /opt/vare/var writable by the service user. Run `apachectl configtest` before reloading Apache, and do not change any other vhost. Finish by showing the output of `curl -s https://helppox.com/vare/api/health`, `systemctl status vare --no-pager`, and `/opt/vare/.venv/bin/python /opt/vare/scripts/mcp_smoke.py https://helppox.com/vare/mcp`.
>
> For later updates: follow the "Updating" section of deploy/DEPLOY.md.
