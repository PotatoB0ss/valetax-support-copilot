# Deployment (single VPS, Ubuntu 24.04)

Live demo: **https://145-63-128-218.sslip.io** (password-protected; ask the author for access).

```
internet ─▶ Caddy :443 (Let's Encrypt via sslip.io hostname, HSTS, auto-renew) ─▶ 127.0.0.1:8000 python -m copilot serve
            Caddy :80  ─▶ 301 to HTTPS                                             (systemd, user `copilot`, sandboxed)
```

| File | Installed to |
|---|---|
| `copilot.service` | `/etc/systemd/system/copilot.service`: runs as unprivileged `copilot`, `ProtectSystem=strict`, restarts on failure |
| `Caddyfile` | `/etc/caddy/Caddyfile`: TLS, security headers, reverse proxy, IP → hostname redirect |

Steps (as root):

```bash
apt install caddy                                   # from the official Caddy apt repo
useradd --system --create-home --home-dir /opt/copilot --shell /usr/sbin/nologin copilot
sudo -u copilot -H sh -c 'curl -LsSf https://astral.sh/uv/install.sh | sh'
git clone https://github.com/PotatoB0ss/valetax-support-copilot /opt/copilot/app
install -m 600 -o copilot -g copilot .env /opt/copilot/app/.env   # see .env.example: key, password, daily caps
cd /opt/copilot/app && sudo -u copilot -H /opt/copilot/.local/bin/uv sync --frozen --no-dev
cp deploy/copilot.service /etc/systemd/system/ && systemctl enable --now copilot
cp deploy/Caddyfile /etc/caddy/Caddyfile && systemctl reload caddy
ufw allow 80/tcp && ufw allow 443/tcp
```

`sslip.io` maps `145-63-128-218.sslip.io` to the server IP, so a real certificate can be issued without
buying a domain. For production, put a company domain in the Caddyfile. Abuse controls (rate limits, daily
budget, size caps) are described in [../SECURITY.md](../SECURITY.md).
