import React, { useMemo, useState } from "react";
import { CheckCircle2, ChevronLeft, ChevronRight, Cloud, Globe2, Home, KeyRound, Server, ShieldCheck } from "lucide-react";
import { Field, StatusPill, Toggle } from "../components/controls.jsx";
import { translateStatusMessage } from "./status.jsx";

export function SetupWizard({
  config,
  t,
  busy,
  patch,
  saveConfig,
  runSync,
  startCloudflareLogin,
  createCloudflareTunnel,
  cloudflareLoginStatus,
  draft,
  setDraft,
  createProxy,
}) {
  const steps = useMemo(() => getWizardSteps(config, t, cloudflareLoginStatus), [config, t, cloudflareLoginStatus]);
  const firstIncomplete = steps.findIndex((step) => !step.done);
  const [stepIndex, setStepIndex] = useState(firstIncomplete === -1 ? steps.length - 1 : firstIncomplete);
  const step = steps[Math.min(stepIndex, steps.length - 1)];

  return (
    <section className="wizard-layout">
      <div className="wizard-sidebar">
        <h2>{t.setupWizard}</h2>
        {steps.map(({ id, label, done }, index) => (
          <button key={id} className={index === stepIndex ? "active" : ""} type="button" onClick={() => setStepIndex(index)}>
            <StatusPill status={{ state: done ? "ok" : index === stepIndex ? "syncing" : "unknown" }} label={done ? t.ok : String(index + 1)} t={t} />
            {label}
          </button>
        ))}
      </div>
      <div className="wizard-panel">
        <div className="wizard-title">
          <div>
            <span>{t.setupStep.replace("{current}", stepIndex + 1).replace("{total}", steps.length)}</span>
            <h2>{step.label}</h2>
          </div>
          <step.Icon size={24} />
        </div>
        {step.id === "admin" && <AdminStep t={t} config={config} />}
        {step.id === "cloudflare" && (
          <CloudflareStep
            t={t}
            config={config}
            busy={busy}
            startCloudflareLogin={startCloudflareLogin}
            createCloudflareTunnel={createCloudflareTunnel}
            cloudflareLoginStatus={cloudflareLoginStatus}
          />
        )}
        {step.id === "caddy" && <CaddyStep t={t} config={config} patch={patch} saveConfig={saveConfig} busy={busy} />}
        {step.id === "adguard" && <AdGuardStep t={t} config={config} patch={patch} saveConfig={saveConfig} busy={busy} />}
        {step.id === "proxy" && <ProxyStep t={t} config={config} draft={draft} setDraft={setDraft} createProxy={createProxy} busy={busy} />}
        {step.id === "finish" && <FinishStep t={t} config={config} runSync={runSync} busy={busy} />}
        <div className="wizard-actions">
          <button className="ghost" type="button" onClick={() => setStepIndex(Math.max(0, stepIndex - 1))} disabled={stepIndex === 0}>
            <ChevronLeft size={16} />
            {t.previous}
          </button>
          <button type="button" onClick={() => setStepIndex(Math.min(steps.length - 1, stepIndex + 1))} disabled={stepIndex === steps.length - 1}>
            {t.next}
            <ChevronRight size={16} />
          </button>
        </div>
      </div>
    </section>
  );
}

function AdminStep({ t, config }) {
  return (
    <div className="wizard-content">
      <StatusLine title={t.adminAccount} done={Boolean(config.admin?.password_hash)} t={t} detail={config.admin?.username || "admin"} />
    </div>
  );
}

function CloudflareStep({ t, config, busy, startCloudflareLogin, createCloudflareTunnel, cloudflareLoginStatus }) {
  const [tunnelName, setTunnelName] = useState(config.cloudflare.tunnel_name || "hola");
  const loginState = cloudflareLoginStatus?.state || "unknown";
  const isLoggedIn = loginState === "ok";
  const hasTunnel = Boolean(config.cloudflare.tunnel_id && config.cloudflare.credentials_file);
  const [loginUrl, setLoginUrl] = useState("");

  const handleLogin = async () => {
    const result = await startCloudflareLogin();
    setLoginUrl(result.login_url || "");
  };

  return (
    <div className="wizard-content">
      <StatusLine title={t.cloudflareLoginStatus} done={isLoggedIn} t={t} detail={formatLoginMessage(cloudflareLoginStatus?.message, t)} />
      <StatusLine title={t.selectedZone} done={Boolean(config.cloudflare.zone_name)} t={t} detail={config.cloudflare.zone_name || t.noZoneSelected} />
      <StatusLine title={t.cloudflareManagedTunnel} done={hasTunnel} t={t} detail={config.cloudflare.tunnel_name || t.notConfigured} />
      <div className="wizard-form-row">
        {!isLoggedIn && <button type="button" onClick={handleLogin} disabled={busy}>{t.getLoginUrl}</button>}
        {loginUrl && (
          <a className="login-link" href={loginUrl} target="_blank" rel="noreferrer">
            {t.openCloudflareLogin}
          </a>
        )}
      </div>
      {isLoggedIn && (
        <div className="wizard-form-row">
          <Field label={t.tunnelName} value={tunnelName} onChange={setTunnelName} placeholder="hola" />
          <button type="button" onClick={() => createCloudflareTunnel(tunnelName)} disabled={busy || !tunnelName.trim()}>
            {hasTunnel ? t.recreateTunnel : t.createTunnel}
          </button>
        </div>
      )}
    </div>
  );
}

function CaddyStep({ t, config, patch, saveConfig, busy }) {
  return (
    <div className="wizard-content">
      <StatusLine title={t.caddy} done={Boolean(config.caddy.admin_url && config.caddy.local_ip)} t={t} detail={translateStatusMessage(config.status?.caddy?.message, t)} />
      <div className="form-grid">
        <Field label={t.caddyAdmin} value={config.caddy.admin_url} onChange={(value) => patch("caddy", "admin_url", value)} />
        <Field label={t.localIp} value={config.caddy.local_ip} onChange={(value) => patch("caddy", "local_ip", value)} placeholder="192.168.1.10" />
        <Field label={t.acmeEmail} value={config.caddy.acme_email} onChange={(value) => patch("caddy", "acme_email", value)} />
        <Toggle checked={config.caddy.http01_enabled} onChange={(value) => patch("caddy", "http01_enabled", value)} label={t.http01} />
      </div>
      <button type="button" onClick={() => saveConfig()} disabled={busy}>{t.save}</button>
    </div>
  );
}

function AdGuardStep({ t, config, patch, saveConfig, busy }) {
  return (
    <div className="wizard-content">
      <StatusLine title={t.adguard} done={!config.adguard.enabled || Boolean(config.adguard.url && config.adguard.username && config.adguard.password)} t={t} detail={translateStatusMessage(config.status?.adguard?.message, t)} />
      <div className="form-grid">
        <Toggle checked={config.adguard.enabled} onChange={(value) => patch("adguard", "enabled", value)} label={t.adguardToggle} />
        <Field label={t.adguardUrl} value={config.adguard.url} onChange={(value) => patch("adguard", "url", value)} placeholder="http://192.168.1.2:3000" />
        <Field label={t.username} value={config.adguard.username} onChange={(value) => patch("adguard", "username", value)} />
        <Field label={t.password} value={config.adguard.password} onChange={(value) => patch("adguard", "password", value)} type="password" />
      </div>
      <button type="button" onClick={() => saveConfig()} disabled={busy}>{t.save}</button>
    </div>
  );
}

function ProxyStep({ t, config, draft, setDraft, createProxy, busy }) {
  const zoneName = config.cloudflare?.zone_name || "";
  const placeholder = zoneName ? `notes.${zoneName}` : "notes.example.com";
  return (
    <div className="wizard-content">
      <StatusLine title={t.addProxy} done={(config.proxies || []).length > 0} t={t} detail={zoneName ? t.proxyWizardZone.replace("{zone}", zoneName) : t.noZoneSelected} />
      <div className="form-grid">
        <Field label={t.hostname} value={draft.hostname} onChange={(value) => setDraft({ ...draft, hostname: value })} placeholder={placeholder} />
        <Field label={t.upstream} value={draft.upstream_url} onChange={(value) => setDraft({ ...draft, upstream_url: value })} placeholder="http://192.168.1.20:5000" />
        <Field label={t.note} value={draft.note} onChange={(value) => setDraft({ ...draft, note: value })} placeholder="Notes" />
        <Toggle checked={draft.enabled} onChange={(value) => setDraft({ ...draft, enabled: value })} label={t.enabled} />
      </div>
      <button type="button" onClick={createProxy} disabled={busy || !draft.hostname.trim() || !draft.upstream_url.trim()}>{t.addProxy}</button>
    </div>
  );
}

function FinishStep({ t, config, runSync, busy }) {
  return (
    <div className="wizard-content">
      <StatusLine title={t.overall} done={config.status?.overall?.state === "ok"} t={t} detail={translateStatusMessage(config.status?.overall?.message, t)} />
      <StatusLine title={t.cloudflare} done={config.status?.cloudflare?.state === "ok"} t={t} detail={translateStatusMessage(config.status?.cloudflare?.message, t)} />
      <StatusLine title={t.caddy} done={config.status?.caddy?.state === "ok"} t={t} detail={translateStatusMessage(config.status?.caddy?.message, t)} />
      <StatusLine title={t.adguard} done={config.status?.adguard?.state === "ok" || config.status?.adguard?.state === "warning"} t={t} detail={translateStatusMessage(config.status?.adguard?.message, t)} />
      <button type="button" onClick={runSync} disabled={busy}>{t.sync}</button>
    </div>
  );
}

function StatusLine({ title, done, detail, t }) {
  return (
    <div className="wizard-status-line">
      <div>
        <strong>{title}</strong>
        {detail && <span>{detail}</span>}
      </div>
      <StatusPill status={{ state: done ? "ok" : "warning" }} label={done ? t.configured : t.notConfigured} t={t} />
    </div>
  );
}

function getWizardSteps(config, t, cloudflareLoginStatus) {
  const isLoggedIn = cloudflareLoginStatus?.state === "ok";
  const hasTunnel = Boolean(config.cloudflare?.tunnel_id && config.cloudflare?.credentials_file);
  const caddyReady = Boolean(config.caddy?.admin_url && config.caddy?.local_ip);
  const adguardReady = !config.adguard?.enabled || Boolean(config.adguard?.url && config.adguard?.username && config.adguard?.password);
  return [
    { id: "admin", label: t.adminAccount, Icon: KeyRound, done: Boolean(config.admin?.password_hash) },
    { id: "cloudflare", label: t.cloudflare, Icon: Cloud, done: isLoggedIn && hasTunnel },
    { id: "caddy", label: t.caddy, Icon: Server, done: caddyReady },
    { id: "adguard", label: t.adguard, Icon: ShieldCheck, done: adguardReady },
    { id: "proxy", label: t.proxies, Icon: Globe2, done: (config.proxies || []).length > 0 },
    { id: "finish", label: t.finishSetup, Icon: Home, done: config.status?.overall?.state === "ok" },
  ];
}

function formatLoginMessage(message, t) {
  if (!message) return t.noStatus;
  if (message === "Cloudflare login certificate is available.") return t.cloudflareLoginComplete;
  if (message === "Cloudflare login certificate is already available.") return t.cloudflareLoginComplete;
  if (message === "Waiting for Cloudflare browser authorization.") return t.cloudflareLoginWaiting;
  if (message === "Cloudflare login has not completed.") return t.cloudflareLoginMissing;
  return message;
}
