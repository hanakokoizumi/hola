import React, { useEffect, useState } from "react";
import { CheckCircle2, Cloud, ExternalLink, LogOut, Network, Server, ShieldCheck } from "lucide-react";
import { Field, StatusPill, Toggle } from "../components/controls.jsx";
import { translateStatusMessage } from "./status.jsx";

export function SettingsView({
  config,
  t,
  patch,
  tab,
  setTab,
  busy,
  startCloudflareLogin,
  logoutCloudflare,
  createCloudflareTunnel,
  cloudflareLoginStatus,
  cloudflareLoginRequested,
  cloudflareLoginCompleteSignal,
}) {
  const tabs = [
    ["cloudflare", Cloud, t.cloudflare],
    ["adguard", ShieldCheck, t.adguard],
    ["caddy", Server, t.caddy],
  ];
  return (
    <section className="settings-layout">
      <div className="settings-nav">
        <h2>{t.settings}</h2>
        {tabs.map(([id, Icon, label]) => (
          <button key={id} className={tab === id ? "active" : ""} onClick={() => setTab(id)}>
            <Icon size={16} />
            {label}
          </button>
        ))}
      </div>
      <div className="settings-panel">
        <div className="settings-title">
          <div>
            <h2>{tabs.find(([id]) => id === tab)?.[2]}</h2>
            <p>{tab === "cloudflare" ? t.cloudflareCommandHint : t.settingsHint}</p>
          </div>
          <Network size={22} />
        </div>
        {tab === "cloudflare" && (
          <Cloudflare
            config={config}
            t={t}
            patch={patch}
            busy={busy}
            startCloudflareLogin={startCloudflareLogin}
            logoutCloudflare={logoutCloudflare}
            createCloudflareTunnel={createCloudflareTunnel}
            cloudflareLoginStatus={cloudflareLoginStatus}
            cloudflareLoginRequested={cloudflareLoginRequested}
            cloudflareLoginCompleteSignal={cloudflareLoginCompleteSignal}
          />
        )}
        {tab === "adguard" && <AdGuard config={config} t={t} patch={patch} />}
        {tab === "caddy" && <Caddy config={config} t={t} patch={patch} />}
      </div>
    </section>
  );
}

function SettingRow({ title, detail, children }) {
  return (
    <div className="setting-row">
      <div>
        <strong>{title}</strong>
        {detail && <span>{detail}</span>}
      </div>
      <div className="setting-control">{children}</div>
    </div>
  );
}

function Cloudflare({
  config,
  t,
  patch,
  busy,
  startCloudflareLogin,
  logoutCloudflare,
  createCloudflareTunnel,
  cloudflareLoginStatus,
  cloudflareLoginRequested,
  cloudflareLoginCompleteSignal,
}) {
  const [loginUrl, setLoginUrl] = useState("");
  const [tunnelName, setTunnelName] = useState(config.cloudflare.tunnel_name || "hola");
  const [showNextStep, setShowNextStep] = useState(false);
  const loginState = cloudflareLoginStatus?.state || "unknown";
  const isLoggedIn = loginState === "ok";
  const hasTunnel = Boolean(config.cloudflare.tunnel_id && config.cloudflare.credentials_file);

  useEffect(() => {
    if (!cloudflareLoginRequested || !isLoggedIn || hasTunnel) return;
    setShowNextStep(true);
  }, [cloudflareLoginRequested, hasTunnel, isLoggedIn]);

  useEffect(() => {
    if (!cloudflareLoginCompleteSignal || !isLoggedIn || hasTunnel) return;
    setShowNextStep(true);
  }, [cloudflareLoginCompleteSignal, hasTunnel, isLoggedIn]);

  const handleLogin = async () => {
    const result = await startCloudflareLogin();
    setLoginUrl(result.login_url || "");
    if (result.state === "ok" && !hasTunnel) {
      setShowNextStep(true);
    }
  };

  const handleLogout = async () => {
    await logoutCloudflare();
    setLoginUrl("");
    setShowNextStep(false);
  };

  const handleCreateTunnel = async () => {
    const result = await createCloudflareTunnel(tunnelName);
    const cloudflare = result.cloudflare || {};
    patch("cloudflare", "enabled", true);
    patch("cloudflare", "tunnel_name", cloudflare.tunnel_name || tunnelName);
    patch("cloudflare", "tunnel_id", cloudflare.tunnel_id || "");
    patch("cloudflare", "credentials_file", cloudflare.credentials_file || "");
    setShowNextStep(false);
  };

  return (
    <>
      <div className="setting-list">
        <SettingRow title={t.cloudflareLoginStatus}>
          <div className="status-detail">
            <StatusPill status={{ state: loginState }} label={t[loginState]} t={t} />
            <span>{formatCloudflareLoginMessage(cloudflareLoginStatus?.message, t)}</span>
          </div>
        </SettingRow>
        <SettingRow title={t.cloudflareSetupStatus}>
          <div className="status-detail">
            <StatusPill status={config.status?.cloudflare} t={t} />
            <span>{translateStatusMessage(config.status?.cloudflare?.message, t)}</span>
          </div>
        </SettingRow>
        <SettingRow title={t.cloudflareLogin} detail={isLoggedIn ? t.cloudflareLoggedInHint : t.cloudflareLoginHint}>
          <div className="cloudflare-flow">
            {isLoggedIn ? (
              <button className="danger" type="button" onClick={handleLogout} disabled={busy}>
                <LogOut size={16} />
                {t.cloudflareLogout}
              </button>
            ) : (
              <>
                <button type="button" onClick={handleLogin} disabled={busy}>{t.getLoginUrl}</button>
                {loginUrl && (
                  <a className="login-link" href={loginUrl} target="_blank" rel="noreferrer">
                    <ExternalLink size={16} />
                    {t.openCloudflareLogin}
                  </a>
                )}
              </>
            )}
          </div>
        </SettingRow>
        <SettingRow title={t.enabledCloudflare} detail={t.cloudflareForcedEnabled}>
          <div className="status-detail">
            <StatusPill status={{ state: config.cloudflare.enabled ? "ok" : "warning" }} label={config.cloudflare.enabled ? t.enabled : t.disabled} t={t} />
          </div>
        </SettingRow>
        <SettingRow title={t.selectedZone} detail={t.selectedZoneHint}>
          <div className="status-detail">
            <StatusPill status={{ state: config.cloudflare.zone_name ? "ok" : "warning" }} label={config.cloudflare.zone_name ? t.configured : t.notConfigured} t={t} />
            <span>{config.cloudflare.zone_name || t.noZoneSelected}</span>
          </div>
        </SettingRow>
        {isLoggedIn && (
          <SettingRow title={t.tunnelName} detail={t.tunnelNameHint}>
            <div className="cloudflare-flow">
              <Field value={tunnelName} onChange={setTunnelName} placeholder="hola" />
              <button type="button" onClick={handleCreateTunnel} disabled={busy || !tunnelName.trim()}>{hasTunnel ? t.recreateTunnel : t.createTunnel}</button>
            </div>
          </SettingRow>
        )}
        {hasTunnel && (
          <SettingRow title={t.cloudflareManagedTunnel}>
            <div className="status-detail">
              <StatusPill status={{ state: "ok" }} label={t.configured} t={t} />
              <span>{config.cloudflare.tunnel_name || tunnelName}</span>
            </div>
          </SettingRow>
        )}
        <SettingRow title={t.cloudflareZoneId} detail={t.cloudflareZoneHint}><Field value={config.cloudflare.zone_id} onChange={(value) => patch("cloudflare", "zone_id", value)} /></SettingRow>
        <SettingRow title={t.cloudflareApiToken} detail={t.cloudflareApiTokenHint}><Field value={config.cloudflare.api_token} onChange={(value) => patch("cloudflare", "api_token", value)} type="password" /></SettingRow>
        <SettingRow title={t.proxyToggle} detail={t.proxyHint}><Toggle checked={config.cloudflare.proxy_enabled} onChange={(value) => patch("cloudflare", "proxy_enabled", value)} label="" /></SettingRow>
        <SettingRow title={t.proxyUrl}><Field value={config.cloudflare.proxy_url} onChange={(value) => patch("cloudflare", "proxy_url", value)} placeholder="http://192.168.1.2:7890 or socks5://192.168.1.2:1080" /></SettingRow>
      </div>
      {showNextStep && (
        <div className="modal-backdrop" role="presentation">
          <div className="modal" role="dialog" aria-modal="true" aria-labelledby="cloudflare-next-step-title">
            <CheckCircle2 size={30} />
            <h2 id="cloudflare-next-step-title">{t.cloudflareLoginComplete}</h2>
            <p>{t.cloudflareCreateTunnelPrompt}</p>
            <div className="cloudflare-flow modal-flow">
              <Field value={tunnelName} onChange={setTunnelName} placeholder="hola" />
              <button type="button" onClick={handleCreateTunnel} disabled={busy || !tunnelName.trim()}>{t.createTunnel}</button>
              <button className="ghost" type="button" onClick={() => setShowNextStep(false)} disabled={busy}>{t.later}</button>
            </div>
          </div>
        </div>
      )}
    </>
  );
}

function formatCloudflareLoginMessage(message, t) {
  if (!message) return t.noStatus;
  if (message === "Cloudflare login certificate is available.") return t.cloudflareLoginComplete;
  if (message === "Cloudflare login certificate is already available.") return t.cloudflareLoginComplete;
  if (message === "Waiting for Cloudflare browser authorization.") return t.cloudflareLoginWaiting;
  if (message === "Cloudflare login has not completed.") return t.cloudflareLoginMissing;
  return message;
}

function AdGuard({ config, t, patch }) {
  return (
    <div className="setting-list">
      <SettingRow title={t.adguardToggle}><Toggle checked={config.adguard.enabled} onChange={(value) => patch("adguard", "enabled", value)} label="" /></SettingRow>
      <SettingRow title={t.adguardUrl}><Field value={config.adguard.url} onChange={(value) => patch("adguard", "url", value)} placeholder="http://192.168.1.2:3000" /></SettingRow>
      <SettingRow title={t.username}><Field value={config.adguard.username} onChange={(value) => patch("adguard", "username", value)} /></SettingRow>
      <SettingRow title={t.password}><Field value={config.adguard.password} onChange={(value) => patch("adguard", "password", value)} type="password" /></SettingRow>
    </div>
  );
}

function Caddy({ config, t, patch }) {
  return (
    <div className="setting-list">
      <SettingRow title={t.caddyAdmin}><Field value={config.caddy.admin_url} onChange={(value) => patch("caddy", "admin_url", value)} /></SettingRow>
      <SettingRow title={t.localIp} detail={t.localIpHint}><Field value={config.caddy.local_ip} onChange={(value) => patch("caddy", "local_ip", value)} placeholder="192.168.1.10" /></SettingRow>
      <SettingRow title={t.acmeEmail}><Field value={config.caddy.acme_email} onChange={(value) => patch("caddy", "acme_email", value)} /></SettingRow>
      <SettingRow title={t.http01}><Toggle checked={config.caddy.http01_enabled} onChange={(value) => patch("caddy", "http01_enabled", value)} label="" /></SettingRow>
    </div>
  );
}
