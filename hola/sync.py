from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Awaitable, Callable

from .clients import (
    AdGuardClient,
    CaddyClient,
    check_cloudflared_connection,
    delete_cloudflare_tunnel_dns,
    restart_container,
    route_cloudflared_dns,
    write_cloudflared_runtime,
)
from .config_store import ConfigStore
from .models import HolaConfig, ProxyRule, SyncStatus, TargetState, TargetStatus, utc_now


@dataclass
class SyncManager:
    store: ConfigStore
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)

    async def reconcile(self) -> SyncStatus:
        async with self.lock:
            config = self.store.read(decrypt=True)

            await self._sync_cloudflare(config)
            await self._sync_caddy(config)
            await self._sync_adguard(config)

            # Re-read the config from disk before writing so we never clobber
            # user edits that landed while the sync was in flight.  Only the
            # status fields and tunnel metadata created during sync are carried
            # over from the in-memory snapshot.
            fresh = self.store.read(decrypt=True)
            fresh.status = config.status
            fresh.cloudflare.tunnel_name = config.cloudflare.tunnel_name
            fresh.cloudflare.tunnel_id = config.cloudflare.tunnel_id
            fresh.cloudflare.credentials_file = config.cloudflare.credentials_file

            self._set_overall_status(fresh)
            self.store.write(fresh)
            return fresh.status

    async def remove_proxy(self, proxy: ProxyRule) -> SyncStatus:
        async with self.lock:
            config = self.store.read(decrypt=True)
            await self._cleanup_removed_proxy(config, proxy)
            cleanup_cloudflare = config.status.cloudflare if config.status.cloudflare.state == TargetState.error else None
            cleanup_adguard = config.status.adguard if config.status.adguard.state == TargetState.error else None
            await self._sync_cloudflare(config)
            await self._sync_caddy(config)
            await self._sync_adguard(config)
            if cleanup_cloudflare:
                config.status.cloudflare = cleanup_cloudflare
            if cleanup_adguard:
                config.status.adguard = cleanup_adguard
            fresh = self.store.read(decrypt=True)
            fresh.status = config.status
            self._set_overall_status(fresh)
            self.store.write(fresh)
            return fresh.status

    def _set_overall_status(self, config: HolaConfig) -> None:
        states = [
            config.status.cloudflare.state,
            config.status.caddy.state,
            config.status.adguard.state,
        ]
        if TargetState.error in states:
            config.status.overall = TargetStatus(state=TargetState.error, message="One or more targets failed")
        elif TargetState.warning in states:
            config.status.overall = TargetStatus(state=TargetState.warning, message="Synced with warnings")
        else:
            config.status.overall = TargetStatus(state=TargetState.ok, message="All targets are in sync")

    async def _run_target(
        self,
        config: HolaConfig,
        attr: str,
        label: str,
        task: Callable[[], Awaitable[str]],
    ) -> None:
        try:
            previous_updated_at = getattr(config.status, attr).updated_at
            message = await task()
            current = getattr(config.status, attr)
            if not message and current.updated_at != previous_updated_at and current.state != TargetState.ok:
                return
            setattr(config.status, attr, TargetStatus(state=TargetState.ok, message=message, updated_at=utc_now()))
        except Exception as exc:  # noqa: BLE001
            setattr(config.status, attr, TargetStatus(state=TargetState.error, message=f"{label}: {exc}", updated_at=utc_now()))

    def _set_target(self, config: HolaConfig, attr: str, state: TargetState, message: str) -> None:
        setattr(config.status, attr, TargetStatus(state=state, message=message, updated_at=utc_now()))

    def _publish_target(self, config: HolaConfig, attr: str, state: TargetState, message: str) -> None:
        self._set_target(config, attr, state, message)
        fresh = self.store.read(decrypt=True)
        fresh.status = config.status
        self.store.write(fresh, backup=False)

    async def _sync_cloudflare(self, config: HolaConfig) -> None:
        async def task() -> str:
            cf = config.cloudflare
            if not cf.enabled:
                self._set_target(config, "cloudflare", TargetState.warning, "Cloudflare sync disabled")
                return ""
            if not cf.tunnel_id or not cf.credentials_file:
                self._set_target(config, "cloudflare", TargetState.warning, "Cloudflare Tunnel not created")
                return ""
            enabled_hostnames = [proxy.hostname for proxy in config.proxies if proxy.enabled]
            routed = 0
            self._publish_target(config, "cloudflare", TargetState.syncing, "Setting Cloudflare Tunnel DNS routes")
            for hostname in enabled_hostnames:
                await route_cloudflared_dns(cf.tunnel_id, hostname)
                routed += 1
            self._publish_target(config, "cloudflare", TargetState.syncing, "Writing Cloudflare Tunnel ingress to Caddy")
            write_cloudflared_runtime(cf.tunnel_id, cf.credentials_file, cf.proxy_enabled, cf.proxy_url, enabled_hostnames)
            self._publish_target(config, "cloudflare", TargetState.syncing, "Starting Cloudflare Tunnel")
            await restart_container("cloudflare")
            self._publish_target(config, "cloudflare", TargetState.syncing, "Waiting for Cloudflare Tunnel to become active")
            await asyncio.sleep(3)
            state, message = await check_cloudflared_connection()
            if state == "error":
                raise RuntimeError(message)
            if state == "warning":
                self._set_target(config, "cloudflare", TargetState.warning, message)
                return ""
            return f"{message}; DNS routes synced for {routed} hostname(s)"

        if config.cloudflare.enabled and config.cloudflare.tunnel_id and config.cloudflare.credentials_file:
            await self._run_target(config, "cloudflare", "Cloudflare sync failed", task)
        else:
            await task()

    async def _cleanup_removed_proxy(self, config: HolaConfig, proxy: ProxyRule) -> None:
        await self._cleanup_removed_cloudflare_dns(config, proxy)
        await self._cleanup_removed_adguard_rewrite(config, proxy)

    async def _cleanup_removed_cloudflare_dns(self, config: HolaConfig, proxy: ProxyRule) -> None:
        cf = config.cloudflare
        if not cf.enabled or not cf.tunnel_id:
            return
        try:
            self._publish_target(config, "cloudflare", TargetState.syncing, "Deleting removed Cloudflare DNS route")
            deleted = await delete_cloudflare_tunnel_dns(cf.zone_id, cf.api_token, cf.tunnel_id, proxy.hostname)
            self._set_target(config, "cloudflare", TargetState.syncing, f"Deleted {deleted} Cloudflare DNS record(s)")
        except Exception as exc:  # noqa: BLE001
            self._set_target(config, "cloudflare", TargetState.error, f"Cloudflare DNS cleanup failed: {exc}")

    async def _cleanup_removed_adguard_rewrite(self, config: HolaConfig, proxy: ProxyRule) -> None:
        adguard = config.adguard
        if not adguard.enabled or not adguard.url or not adguard.username or not adguard.password or not config.caddy.local_ip:
            return
        try:
            self._publish_target(config, "adguard", TargetState.syncing, "Deleting removed AdGuard Home DNS rewrite")
            client = AdGuardClient(adguard.url, adguard.username, adguard.password)
            await client.delete_rewrite(proxy.hostname, config.caddy.local_ip)
        except Exception as exc:  # noqa: BLE001
            self._set_target(config, "adguard", TargetState.error, f"AdGuard cleanup failed: {exc}")

    async def _sync_caddy(self, config: HolaConfig) -> None:
        async def task() -> str:
            if not config.caddy.admin_url:
                self._set_target(config, "caddy", TargetState.warning, "Caddy Admin API URL missing")
                return ""
            self._publish_target(config, "caddy", TargetState.syncing, "Loading Caddy reverse proxy configuration")
            await CaddyClient(config.caddy.admin_url).load_config(config)
            if config.caddy.http01_enabled and config.proxies:
                self._publish_target(config, "caddy", TargetState.syncing, "Waiting for SSL certificates")
            return "Caddy reverse proxy config loaded"

        if config.caddy.admin_url:
            await self._run_target(config, "caddy", "Caddy sync failed", task)
        else:
            await task()

    async def _sync_adguard(self, config: HolaConfig) -> None:
        async def task() -> str:
            adguard = config.adguard
            if not adguard.enabled:
                self._set_target(config, "adguard", TargetState.warning, "AdGuard Home sync disabled")
                return ""
            if not adguard.url or not adguard.username or not adguard.password:
                self._set_target(config, "adguard", TargetState.warning, "AdGuard Home configuration incomplete")
                return ""
            if config.proxies and not config.caddy.local_ip:
                self._set_target(config, "adguard", TargetState.warning, "Caddy local LAN IP missing")
                return ""
            client = AdGuardClient(adguard.url, adguard.username, adguard.password)
            self._publish_target(config, "adguard", TargetState.syncing, "Checking AdGuard Home authentication")
            await client.check_auth()
            count = 0
            for proxy in config.proxies:
                answer = config.caddy.local_ip
                self._publish_target(config, "adguard", TargetState.syncing, "Syncing AdGuard Home DNS rewrites")
                if proxy.enabled:
                    await client.set_rewrite(proxy.hostname, answer)
                    count += 1
                else:
                    await client.delete_rewrite(proxy.hostname, answer)
            return f"AdGuard Home rewrites synced for {count} proxy rule(s)"

        if config.adguard.enabled and config.adguard.url and config.adguard.username and config.adguard.password:
            await self._run_target(config, "adguard", "AdGuard sync failed", task)
        else:
            await task()
