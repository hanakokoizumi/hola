import React from "react";
import { Activity, Globe2, Settings } from "lucide-react";
import { LanguageSelect, StatusPill } from "./controls.jsx";

export function FooterMeta({ config }) {
  return (
    <div className="footer-meta">
      <span>Hola v{config.version || "0.1.0"}</span>
      <a href="https://github.com/hanakokoizumi/hola" target="_blank" rel="noreferrer">
        GitHub
      </a>
    </div>
  );
}

export function Shell({ config, t, active, setActive, lang, setLang, busy, runSync, saveConfig, children }) {
  const nav = [
    ["proxies", Globe2, t.proxies],
    ["settings", Settings, t.settings],
    ["status", Activity, t.status],
  ];

  return (
    <div className="shell">
      <aside>
        <div className="brand">
          <div className="brand-mark">H</div>
          <div>
            <strong>Hola</strong>
          </div>
        </div>
        <nav>
          {nav.map(([id, Icon, label]) => (
            <button key={id} className={active === id ? "active" : ""} onClick={() => setActive(id)}>
              <Icon size={18} />
              {label}
            </button>
          ))}
        </nav>
        <FooterMeta config={config} />
      </aside>
      <main>
        <header>
          <div>
            <h1>{{ proxies: t.proxies, settings: t.settings, status: t.status }[active]}</h1>
          </div>
          <div className="actions">
            <LanguageSelect lang={lang} setLang={setLang} />
            <StatusPill status={{ state: "ok" }} label={t.signedIn} t={t} />
            <button className="ghost" onClick={runSync} disabled={busy}>
              {t.sync}
            </button>
            <button onClick={() => saveConfig()} disabled={busy}>
              {t.save}
            </button>
          </div>
        </header>
        {children}
      </main>
    </div>
  );
}
