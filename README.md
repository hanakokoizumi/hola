<p align="center">
  <a href="README.zh-CN.md">简体中文</a>
</p>

<p align="center">
  <img src="https://img.shields.io/badge/python-3.12%2B-blue?logo=python&logoColor=white" alt="Python">
  <img src="https://img.shields.io/badge/fastapi-0.115%2B-009688?logo=fastapi&logoColor=white" alt="FastAPI">
  <img src="https://img.shields.io/badge/react-19-61DAFB?logo=react&logoColor=white" alt="React">
  <img src="https://img.shields.io/badge/vite-7-646CFF?logo=vite&logoColor=white" alt="Vite">
  <img src="https://img.shields.io/badge/typescript-5.8-3178C6?logo=typescript&logoColor=white" alt="TypeScript">
  <img src="https://img.shields.io/badge/Docker-✓-2496ED?logo=docker&logoColor=white" alt="Docker">
  <img src="https://img.shields.io/badge/caddy-2.8-22B638?logo=caddy&logoColor=white" alt="Caddy">
  <img src="https://img.shields.io/badge/Cloudflare-Tunnel-F38020?logo=cloudflare&logoColor=white" alt="Cloudflare Tunnel">
  <img src="https://img.shields.io/badge/license-MIT-green" alt="License">
</p>

<h1 align="center">Hola 🏠</h1>

<p align="center"><strong>HomeLab split‑access proxy manager</strong></p>

<p align="center">
  One domain. Two paths — <em>local</em> when youʼre home, <em>remote</em> when youʼre away.
</p>

---

## What does it do?

Run services on the same domain — say `grafana.example.com` — and have them accessible **locally** via your LAN, and **remotely** via Cloudflare Tunnel. Hola wires together the pieces so you donʼt have to:

| Layer | Inside your network | Outside your network |
|---|---|---|
| **Access** | AdGuard Home DNS → LAN IP | Cloudflare Tunnel → public internet |
| **TLS** | Caddy + Letʼs Encrypt | Cloudflare edge certificate |
| **Reverse proxy** | Caddy (managed by Hola) | Cloudflare Tunnel → Caddy |

All configuration lives in one YAML file, editable from the web panel. No SSH, no editing configs by hand.

```
 Browser ──┐
           ├── home ──► adguard DNS rewrite ──► caddy ──► your app
           │
           └── away ──► Cloudflare Tunnel ──► caddy ──► your app
```

## Quick start

```bash
cp .env.example .env
docker compose up --build
```

Open **http://localhost:9333** — the web panel is ready.

> All runtime settings are editable in the UI. Environment variables in `.env` only supply first‑run defaults.

## How it works

### 1. Add a service

Give it a name, subdomain, and upstream port in the web panel.

### 2. Local access (AdGuard Home)

Hola pushes a **DNS rewrite** rule to your AdGuard Home instance so `subdomain.example.com` resolves to your serverʼs LAN IP. Requests go:

```
browser → subdomain.example.com → LAN IP → Caddy → your app
```

### 3. Remote access (Cloudflare Tunnel)

Hola registers the same subdomain with `cloudflared`. When youʼre outside your network, requests go:

```
browser → Cloudflare edge → Tunnel → Caddy → your app
```

No port forwarding. No dynamic DNS. No split‑brained bookmarks.

## Data layout

Everything lives under `./data/` — plain directories, no Docker volumes:

```text
data/
├── app/
│   ├── hola.yaml          # service definitions (editable in UI)
│   ├── secret.key          # encryption key
│   └── backups/            # automatic YAML snapshots
├── caddy/
│   ├── data/               # Let's Encrypt certs & OCSP
│   └── config/             # caddy.json (managed by Hola)
└── cloudflared/
    ├── cert.pem
    ├── credentials-*.json
    ├── runtime.env
    └── tunnel-id
```

## Requirements

- **Docker** and **Docker Compose** v2
- An **AdGuard Home** instance already running on your network (Hola uses its API to push DNS rewrites)
- A **Cloudflare** account with a domain on Cloudflare nameservers (for Tunnel)
- A domain you own (e.g. `example.com`)

## First‑run setup

1. Copy `.env.example` → `.env`, adjust if needed.
2. `docker compose up --build`
3. Open the web panel at `http://localhost:9333`.
4. Configure your **AdGuard Home** URL + credentials under Settings.
5. Under Cloudflare, click **Login** — Hola will give you a URL. Open it in a browser, authorize, paste the token back.
6. Create a tunnel, add your services, done.

---

<p align="center">
  <a href="https://github.com/hanakokoizumi/hola">GitHub</a> ·
  MIT License
</p>
