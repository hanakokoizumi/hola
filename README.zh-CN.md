<p align="center">
  <a href="README.md">English</a>
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

<p align="center"><strong>HomeLab 内外网分流代理管理器</strong></p>

<p align="center">
  一个域名，两条路径 —— <em>在家</em>走内网，<em>出门</em>走隧道。
</p>

---

## 这是什么？

让你的服务使用同一个域名（如 `grafana.example.com`），**在家时**通过局域网直连，**出门时**通过 Cloudflare Tunnel 远程访问。Hola 帮你把各组件串联起来，无需手动配置：

| 层级 | 内网访问 | 外网访问 |
|---|---|---|
| **入口** | AdGuard Home DNS → 局域网 IP | Cloudflare Tunnel → 公网 |
| **TLS** | Caddy + Letʼs Encrypt | Cloudflare 边缘证书 |
| **反向代理** | Caddy（由 Hola 管理） | Cloudflare Tunnel → Caddy |

所有配置集中在一个 YAML 文件中，通过 Web 面板即可编辑。无需 SSH，无需手改配置文件。

```
 浏览器 ──┐
          ├── 在家 ──► AdGuard DNS 重写 ──► Caddy ──► 你的服务
          │
          └── 出门 ──► Cloudflare Tunnel ──► Caddy ──► 你的服务
```

## 快速开始

```bash
cp .env.example .env
docker compose up --build
```

打开 **http://localhost:9333** 即可进入 Web 管理面板。

> 所有运行时配置均可在界面中修改。`.env` 中的环境变量仅提供首次运行的默认值。

## 工作原理

### 1. 添加服务

在 Web 面板中填写服务名称、子域名和上游端口。

### 2. 内网访问（AdGuard Home）

Hola 会向你的 AdGuard Home 推送 **DNS 重写规则**，使 `subdomain.example.com` 解析到你服务器的局域网 IP。请求路径：

```
浏览器 → subdomain.example.com → 局域网 IP → Caddy → 你的服务
```

### 3. 外网访问（Cloudflare Tunnel）

Hola 同时将同一子域名注册到 `cloudflared`。当你离开家时，请求路径：

```
浏览器 → Cloudflare 边缘节点 → Tunnel → Caddy → 你的服务
```

无需端口转发，无需动态 DNS，无需记住两套地址。

## 数据目录结构

所有数据存放在 `./data/` 下，纯目录，无 Docker volume：

```text
data/
├── app/
│   ├── hola.yaml          # 服务定义（可在界面中编辑）
│   ├── secret.key          # 加密密钥
│   └── backups/            # YAML 自动备份快照
├── caddy/
│   ├── data/               # Let's Encrypt 证书与 OCSP
│   └── config/             # caddy.json（由 Hola 管理）
└── cloudflared/
    ├── cert.pem
    ├── credentials-*.json
    ├── runtime.env
    └── tunnel-id
```

## 前置条件

- **Docker** 和 **Docker Compose** v2
- 已在局域网中运行一个 **AdGuard Home** 实例（Hola 通过其 API 推送 DNS 重写规则）
- 一个 **Cloudflare** 账号，且域名已托管在 Cloudflare 的 NS 服务器上（用于 Tunnel）
- 一个属于你自己的域名

## 首次配置流程

1. 复制 `.env.example` → `.env`，按需调整。
2. `docker compose up --build`
3. 打开 Web 面板 `http://localhost:9333`。
4. 在「设置」中填写你的 **AdGuard Home** 地址和账号密码。
5. 在 Cloudflare 设置中点击「登录」——Hola 会生成一个授权 URL，在浏览器中打开并授权，将令牌粘贴回来。
6. 创建隧道，添加你的服务，大功告成。

---

<p align="center">
  <a href="https://github.com/hanakokoizumi/hola">GitHub</a> ·
  MIT 许可证
</p>
