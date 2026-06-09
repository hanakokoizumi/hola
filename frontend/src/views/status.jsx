import React from "react";
import { StatusPill } from "../components/controls.jsx";

export function Status({ config, t }) {
  const items = [
    [t.overall, config.status?.overall],
    [t.cloudflare, config.status?.cloudflare],
    [t.caddy, config.status?.caddy],
    [t.adguard, config.status?.adguard],
  ];
  return (
    <section className="stack">
      {items.map(([name, status]) => (
        <article className="status-line" key={name}>
          <div>
            <strong>{name}</strong>
            <span>{translateStatusMessage(status?.message, t)}</span>
          </div>
          <StatusPill status={status} t={t} />
        </article>
      ))}
    </section>
  );
}

export function translateStatusMessage(message, t) {
  if (!message) return t.noStatus;
  if (message === "Cloudflare sync disabled") return t.cloudflareDisabled;
  if (message === "Cloudflare configuration incomplete") return t.cloudflareIncomplete;
  if (message === "Cloudflare Tunnel not created") return t.cloudflareIncomplete;
  if (message === "Setting Cloudflare Tunnel DNS routes") return t.cloudflareSettingDns;
  if (message === "Writing Cloudflare Tunnel ingress to Caddy") return t.cloudflareWritingIngress;
  if (message === "Starting Cloudflare Tunnel") return t.cloudflareStartingTunnel;
  if (message === "Waiting for Cloudflare Tunnel to become active") return t.cloudflareWaitingTunnel;
  if (message === "Deleting removed Cloudflare DNS route") return t.cloudflareDeletingDns;
  if (message.startsWith("Deleted ") && message.includes(" Cloudflare DNS record")) return t.cloudflareDeletedDns;
  if (message.startsWith("Cloudflare DNS cleanup failed:")) return `${t.cloudflareDnsCleanupFailed} ${message.replace("Cloudflare DNS cleanup failed:", "").trim()}`;
  if (message === "Caddy reverse proxy config loaded") return t.caddyLoaded;
  if (message === "Caddy sync disabled") return t.caddyDisabled;
  if (message === "Caddy Admin API URL missing") return t.caddyDisabled;
  if (message === "Caddy local LAN IP missing") return t.caddyLocalIpMissingDetail;
  if (message === "Loading Caddy reverse proxy configuration") return t.caddyLoading;
  if (message === "Waiting for SSL certificates") return t.caddyWaitingSsl;
  if (message === "AdGuard Home sync disabled") return t.adguardDisabled;
  if (message === "AdGuard Home configuration incomplete") return t.adguardIncomplete;
  if (message === "Checking AdGuard Home authentication") return t.adguardCheckingAuth;
  if (message === "Syncing AdGuard Home DNS rewrites") return t.adguardSyncingRewrites;
  if (message === "Deleting removed AdGuard Home DNS rewrite") return t.adguardDeletingRewrite;
  if (message.startsWith("AdGuard cleanup failed:")) return `${t.adguardCleanupFailed} ${message.replace("AdGuard cleanup failed:", "").trim()}`;
  if (message.includes("AdGuard Home authentication failed")) return t.adguardAuthFailed;
  if (message === "All targets are in sync") return t.allSynced;
  if (message === "Synced with warnings") return t.syncedWarnings;
  if (message === "One or more targets failed") return t.syncFailed;
  return message;
}
