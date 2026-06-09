import React from "react";
import { Languages } from "lucide-react";

export function Field({
  label,
  value,
  onChange,
  type = "text",
  placeholder = "",
  name,
  required = false,
  minLength,
  maxLength,
}) {
  const inputProps = onChange
    ? { value: value ?? "", onChange: (event) => onChange(event.target.value) }
    : { defaultValue: value ?? "" };

  return (
    <label className="field">
      {label && <span>{label}</span>}
      <input
        name={name}
        type={type}
        required={required}
        minLength={minLength}
        maxLength={maxLength}
        placeholder={placeholder}
        {...inputProps}
      />
    </label>
  );
}

export function Toggle({ checked, onChange, label }) {
  return (
    <label className="toggle">
      <input type="checkbox" checked={Boolean(checked)} onChange={(event) => onChange(event.target.checked)} />
      <span />
      {label}
    </label>
  );
}

export function StatusPill({ status, label, t }) {
  const state = status?.state || "unknown";
  return <span className={`pill ${state}`}>{label || t?.[state] || state}</span>;
}

export function LanguageSelect({ lang, setLang }) {
  return (
    <label className="language">
      <Languages size={16} />
      <select value={lang} onChange={(event) => setLang(event.target.value)}>
        <option value="zh">简体中文</option>
        <option value="en">English</option>
      </select>
    </label>
  );
}
