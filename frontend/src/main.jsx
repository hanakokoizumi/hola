import React, { useEffect, useState } from "react";
import { createRoot } from "react-dom/client";
import { dictionaries, getInitialLanguage } from "./i18n/locales.js";
import { api } from "./lib/api.js";
import { emptyConfig } from "./lib/config.js";
import { Shell } from "./components/layout.jsx";
import { AuthPage } from "./views/auth.jsx";
import { Proxies } from "./views/proxies.jsx";
import { SetupWizard } from "./views/setup-wizard.jsx";
import { SettingsView } from "./views/settings.jsx";
import { Status } from "./views/status.jsx";
import "./styles.css";

function App() {
  const [lang, setLang] = useState(getInitialLanguage());
  const t = dictionaries[lang] || dictionaries.en;
  const [config, setConfig] = useState(emptyConfig);
  const [active, setActive] = useState("proxies");
  const [settingsTab, setSettingsTab] = useState("cloudflare");
  const [busy, setBusy] = useState(false);
  const [toast, setToast] = useState("");
  const [authed, setAuthed] = useState(localStorage.getItem("hola.auth") === "true");
  const [cloudflareLoginRequested, setCloudflareLoginRequested] = useState(false);
  const [cloudflareLoginCompleteSignal, setCloudflareLoginCompleteSignal] = useState(0);
  const [cloudflareLoginStatus, setCloudflareLoginStatus] = useState({
    state: "unknown",
    message: t.noStatus,
    login_running: false,
  });
  const [proxyDraft, setProxyDraft] = useState({ hostname: "", upstream_url: "", enabled: true, note: "" });
  const needsSetup = !config.admin?.password_hash;

  useEffect(() => {
    api("/api/config").then(setConfig).catch((error) => setToast(error.message));
  }, []);

  const refreshStatus = () =>
    api("/api/status")
      .then((status) => setConfig((current) => ({ ...current, status })))
      .catch(() => {});

  useEffect(() => {
    if (!authed || needsSetup) return undefined;
    const timer = window.setInterval(refreshStatus, 1000);
    return () => window.clearInterval(timer);
  }, [authed, needsSetup]);

  const enableCloudflareLocally = () => {
    setConfig((current) => ({
      ...current,
      cloudflare: {
        ...current.cloudflare,
        enabled: true,
      },
    }));
  };

  const refreshCloudflareLoginStatus = async () => {
    const status = await api("/api/cloudflare/login/status");
    setCloudflareLoginStatus(status);
    if (status.cloudflare) {
      setConfig((current) => ({
        ...current,
        cloudflare: {
          ...current.cloudflare,
          ...status.cloudflare,
        },
      }));
    }
    if (status.state === "ok") {
      enableCloudflareLocally();
    }
    return status;
  };

  useEffect(() => {
    if (!authed || needsSetup) return undefined;
    refreshCloudflareLoginStatus().catch(() => {});
    const interval = cloudflareLoginRequested || cloudflareLoginStatus.login_running ? 1000 : 5000;
    const timer = window.setInterval(() => refreshCloudflareLoginStatus().catch(() => {}), interval);
    return () => window.clearInterval(timer);
  }, [authed, needsSetup, cloudflareLoginRequested, cloudflareLoginStatus.login_running]);

  useEffect(() => {
    if (!cloudflareLoginRequested || cloudflareLoginStatus.state !== "ok") return;
    setCloudflareLoginRequested(false);
    setConfig((current) => ({
      ...current,
      cloudflare: {
        ...current.cloudflare,
        enabled: true,
      },
    }));
    setCloudflareLoginCompleteSignal((value) => value + 1);
    setToast(t.cloudflareLoginNextStep);
  }, [cloudflareLoginRequested, cloudflareLoginStatus.state, t.cloudflareLoginNextStep]);

  const switchLang = (value) => {
    localStorage.setItem("hola.lang", value);
    setLang(value);
  };

  const patch = (section, key, value) => {
    setConfig((current) => ({ ...current, [section]: { ...current[section], [key]: value } }));
  };

  const saveConfig = async (nextConfig = config) => {
    setBusy(true);
    try {
      const saved = await api("/api/config", { method: "PUT", body: JSON.stringify(nextConfig) });
      setConfig(saved);
      window.setTimeout(refreshStatus, 500);
      window.setTimeout(refreshStatus, 2000);
      setToast(t.configSaved);
    } catch (error) {
      setToast(error.message);
    } finally {
      setBusy(false);
    }
  };

  const runSync = async () => {
    setBusy(true);
    try {
      const status = await api("/api/sync", { method: "POST" });
      setConfig((current) => ({ ...current, status }));
      setToast(t.syncFinished);
    } catch (error) {
      setToast(error.message);
    } finally {
      setBusy(false);
    }
  };

  const startCloudflareLogin = async () => {
    setBusy(true);
    try {
      const result = await api("/api/cloudflare/login", { method: "POST" });
      setCloudflareLoginStatus(result);
      if (result.cloudflare) {
        setConfig((current) => ({
          ...current,
          cloudflare: {
            ...current.cloudflare,
            ...result.cloudflare,
          },
        }));
      }
      if (result.state === "ok") {
        enableCloudflareLocally();
        setCloudflareLoginCompleteSignal((value) => value + 1);
        setToast(t.cloudflareLoginNextStep);
      } else {
        setCloudflareLoginRequested(true);
        setToast(t.cloudflareLoginStarted);
      }
      return result;
    } catch (error) {
      setToast(error.message);
      throw error;
    } finally {
      setBusy(false);
    }
  };

  const logoutCloudflare = async () => {
    setBusy(true);
    try {
      const result = await api("/api/cloudflare/login", { method: "DELETE" });
      setCloudflareLoginRequested(false);
      setCloudflareLoginStatus(result.login_status);
      setConfig((current) => ({
        ...current,
        cloudflare: result.cloudflare || {
          ...current.cloudflare,
          enabled: false,
          tunnel_id: "",
          credentials_file: "",
        },
      }));
      setToast(t.cloudflareLoggedOut);
      return result;
    } catch (error) {
      setToast(error.message);
      throw error;
    } finally {
      setBusy(false);
    }
  };

  const createCloudflareTunnel = async (name) => {
    setBusy(true);
    try {
      const result = await api("/api/cloudflare/tunnel", {
        method: "POST",
        body: JSON.stringify({ name }),
      });
      setConfig((current) => ({
        ...current,
        cloudflare: result.cloudflare || current.cloudflare,
      }));
      window.setTimeout(refreshStatus, 1000);
      setToast(t.cloudflareTunnelCreated);
      return result;
    } catch (error) {
      setToast(error.message);
      throw error;
    } finally {
      setBusy(false);
    }
  };

  const createProxy = async () => {
    return createProxyFromDraft(proxyDraft, () => setProxyDraft({ hostname: "", upstream_url: "", enabled: true, note: "" }));
  };

  const createProxyFromDraft = async (draft, onCreated) => {
    const zoneName = config.cloudflare?.zone_name || "";
    if (zoneName && !isHostnameInZone(draft.hostname, zoneName)) {
      setToast(t.proxyZoneMismatch.replace("{zone}", zoneName));
      return;
    }
    setBusy(true);
    try {
      const proxy = await api("/api/proxies", { method: "POST", body: JSON.stringify(draft) });
      setConfig((current) => ({
        ...current,
        proxies: [...current.proxies.filter((item) => item.id !== proxy.id), proxy],
      }));
      window.setTimeout(refreshStatus, 1000);
      onCreated?.(proxy);
      setToast(t.proxyCreated);
    } catch (error) {
      setToast(error.message);
    } finally {
      setBusy(false);
    }
  };

  const deleteProxy = async (id) => {
    setBusy(true);
    try {
      await api(`/api/proxies/${id}`, { method: "DELETE" });
      setConfig((current) => ({
        ...current,
        proxies: current.proxies.filter((item) => item.id !== id),
      }));
      window.setTimeout(refreshStatus, 1000);
      setToast(t.proxyDeleted);
    } catch (error) {
      setToast(error.message);
    } finally {
      setBusy(false);
    }
  };

  const setPassword = async (event) => {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    setBusy(true);
    try {
      await api("/api/admin/password", {
        method: "POST",
        body: JSON.stringify({ username: form.get("username"), password: form.get("password") }),
      });
      const fresh = await api("/api/config");
      setConfig(fresh);
      setAuthed(true);
      localStorage.setItem("hola.auth", "true");
      setActive("wizard");
      setToast(t.accountReady);
    } catch (error) {
      setToast(error.message);
    } finally {
      setBusy(false);
    }
  };

  const login = async (event) => {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    setBusy(true);
    try {
      await api("/api/login", {
        method: "POST",
        body: JSON.stringify({ username: form.get("username"), password: form.get("password") }),
      });
      setAuthed(true);
      localStorage.setItem("hola.auth", "true");
      setToast(t.loginSucceeded);
    } catch (error) {
      setToast(error.message);
    } finally {
      setBusy(false);
    }
  };

  if (needsSetup || !authed) {
    return (
      <AuthPage
        mode={needsSetup ? "setup" : "login"}
        t={t}
        toast={toast}
        setToast={setToast}
        busy={busy}
        onSubmit={needsSetup ? setPassword : login}
        lang={lang}
        setLang={switchLang}
        config={config}
      />
    );
  }

  return (
    <Shell
      config={config}
      t={t}
      active={active}
      setActive={setActive}
      lang={lang}
      setLang={switchLang}
      busy={busy}
      runSync={runSync}
      saveConfig={saveConfig}
    >
      {toast && <div className="toast" onClick={() => setToast("")}>{toast}</div>}
      {active === "wizard" && (
        <SetupWizard
          config={config}
          t={t}
          busy={busy}
          patch={patch}
          saveConfig={saveConfig}
          runSync={runSync}
          startCloudflareLogin={startCloudflareLogin}
          createCloudflareTunnel={createCloudflareTunnel}
          cloudflareLoginStatus={cloudflareLoginStatus}
          draft={proxyDraft}
          setDraft={setProxyDraft}
          createProxy={createProxy}
        />
      )}
      {active === "proxies" && (
        <Proxies
          config={config}
          t={t}
          draft={proxyDraft}
          setDraft={setProxyDraft}
          createProxy={createProxy}
          deleteProxy={deleteProxy}
        />
      )}
      {active === "settings" && (
        <SettingsView
          config={config}
          t={t}
          patch={patch}
          tab={settingsTab}
          setTab={setSettingsTab}
          busy={busy}
          startCloudflareLogin={startCloudflareLogin}
          logoutCloudflare={logoutCloudflare}
          createCloudflareTunnel={createCloudflareTunnel}
          cloudflareLoginStatus={cloudflareLoginStatus}
          cloudflareLoginRequested={cloudflareLoginRequested}
          cloudflareLoginCompleteSignal={cloudflareLoginCompleteSignal}
        />
      )}
      {active === "status" && <Status config={config} t={t} />}
    </Shell>
  );
}

createRoot(document.getElementById("root")).render(<App />);

function isHostnameInZone(hostname, zoneName) {
  const host = hostname.trim().toLowerCase().replace(/\.$/, "");
  const zone = zoneName.trim().toLowerCase().replace(/\.$/, "");
  return Boolean(zone && (host === zone || host.endsWith(`.${zone}`)));
}
