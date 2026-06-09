import React from "react";
import { KeyRound, Lock } from "lucide-react";
import { Field, LanguageSelect } from "../components/controls.jsx";
import { FooterMeta } from "../components/layout.jsx";

export function AuthPage({ mode, t, toast, setToast, busy, onSubmit, lang, setLang, config }) {
  return (
    <div className="auth-page">
      <div className="auth-card">
        <div className="auth-copy">
          <div className="brand auth-brand">
            <div className="brand-mark">H</div>
            <div>
              <strong>Hola</strong>
              <span>{t.appSubtitle}</span>
            </div>
          </div>
          <KeyRound size={42} />
          <h1>{mode === "setup" ? t.setupTitle : t.loginTitle}</h1>
          <p>{mode === "setup" ? t.setupCopy : t.loginCopy}</p>
        </div>
        <form onSubmit={onSubmit} className="auth-form">
          <LanguageSelect lang={lang} setLang={setLang} />
          {toast && (
            <div className="toast compact" onClick={() => setToast("")}>
              {toast}
            </div>
          )}
          <Field label={t.username} name="username" required placeholder="admin" />
          <Field label={t.password} name="password" type="password" required minLength={6} maxLength={256} placeholder="******" />
          <button disabled={busy}>
            <Lock size={17} />
            {mode === "setup" ? t.createAccount : t.signIn}
          </button>
        </form>
      </div>
      <FooterMeta config={config} />
    </div>
  );
}
