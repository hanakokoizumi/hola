import React from "react";
import { Activity, Cloud, Server, ShieldCheck } from "lucide-react";
import { StatusPill } from "../components/controls.jsx";

export function Dashboard({ config, t }) {
  const cards = [
    [t.cloudflare, Cloud, config.status?.cloudflare, `${config.proxies?.filter((p) => p.enabled).length || 0} ${t.activeHosts}`],
    [t.caddy, Server, config.status?.caddy, config.caddy?.admin_url],
    [t.adguard, ShieldCheck, config.status?.adguard, config.adguard?.url || t.externalInstance],
    [t.overall, Activity, config.status?.overall, config.status?.overall?.message],
  ];
  return (
    <section className="grid cards">
      {cards.map(([label, Icon, status, detail]) => (
        <article className="card" key={label}>
          <div className="card-top">
            <Icon size={22} />
            <StatusPill status={status} t={t} />
          </div>
          <h2>{label}</h2>
          <p>{detail || t.notConfigured}</p>
        </article>
      ))}
    </section>
  );
}
