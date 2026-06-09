import React from "react";
import { Globe2, Plus, Trash2 } from "lucide-react";
import { Field, StatusPill, Toggle } from "../components/controls.jsx";

export function Proxies({ config, t, draft, setDraft, createProxy, deleteProxy }) {
  const zoneName = config.cloudflare?.zone_name || "";
  const hostname = draft.hostname.trim().toLowerCase().replace(/\.$/, "");
  const hostOutsideZone = Boolean(zoneName && hostname && hostname !== zoneName && !hostname.endsWith(`.${zoneName}`));
  const hostnamePlaceholder = zoneName ? `nas.${zoneName}` : "nas.example.com";

  return (
    <section className="stack">
      <div className="panel">
        <div className="panel-heading">
          <h2>{t.addProxy}</h2>
          {zoneName && (
            <div className="zone-chip" title={t.selectedZone}>
              <Globe2 size={15} />
              <span>{zoneName}</span>
            </div>
          )}
        </div>
        <div className="form-grid proxy-form">
          <div className="field-stack">
            <Field label={t.hostname} value={draft.hostname} onChange={(value) => setDraft({ ...draft, hostname: value })} placeholder={hostnamePlaceholder} />
            {hostOutsideZone && <span className="field-error">{t.proxyZoneMismatch.replace("{zone}", zoneName)}</span>}
          </div>
          <Field label={t.upstream} value={draft.upstream_url} onChange={(value) => setDraft({ ...draft, upstream_url: value })} placeholder="http://192.168.1.20:5000" />
          <Field label={t.note} value={draft.note} onChange={(value) => setDraft({ ...draft, note: value })} placeholder="NAS" />
          <Toggle checked={draft.enabled} onChange={(value) => setDraft({ ...draft, enabled: value })} label={t.enabled} />
          <button onClick={createProxy} disabled={hostOutsideZone}>
            <Plus size={17} />
            {t.addProxy}
          </button>
        </div>
      </div>
      <div className="table">
        {(config.proxies || []).map((proxy) => (
          <div className="row" key={proxy.id}>
            <div>
              <strong>{proxy.hostname}</strong>
              <span>{proxy.upstream_url}</span>
            </div>
            <StatusPill status={{ state: proxy.enabled ? "ok" : "warning" }} t={t} />
            <button className="icon danger" onClick={() => deleteProxy(proxy.id)} title="Delete proxy">
              <Trash2 size={17} />
            </button>
          </div>
        ))}
        {(!config.proxies || config.proxies.length === 0) && <div className="empty">{t.noProxy}</div>}
      </div>
    </section>
  );
}
