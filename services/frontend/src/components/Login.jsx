import { useState } from "react";
import { api } from "../api.js";
import Logo from "./Logo.jsx";
import { Alert, Spinner } from "./ui.jsx";

const FEATURES = [
  ["Paiements instantanés", "Vos paiements sont exécutés en quelques secondes."],
  ["Sécurité renforcée", "Pare-feu applicatif, authentification forte et surveillance continue."],
  ["Toujours disponible", "La plateforme se rétablit seule en cas d'incident."],
];

export default function Login({ onLogin }) {
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [otp, setOtp] = useState("");
  const [needOtp, setNeedOtp] = useState(false);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  async function submit(event) {
    event.preventDefault();
    setError("");
    setBusy(true);
    try {
      const { data } = await api.login(username.trim(), password, needOtp ? otp : undefined);
      onLogin({ token: data.access_token, role: data.role, displayName: data.display_name, username: username.trim() });
    } catch (err) {
      if (err.body && err.body.mfa_required) {
        setNeedOtp(true);
        setError("Saisissez le code à 6 chiffres de votre application d'authentification.");
      } else {
        setError(err.message);
      }
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="grid min-h-screen lg:grid-cols-2">
      {/* Panneau de marque, visible sur grand écran */}
      <aside className="relative hidden overflow-hidden bg-brand-950 p-12 text-white lg:flex lg:flex-col lg:justify-between">
        <div className="pointer-events-none absolute -top-32 -right-32 h-96 w-96 rounded-full bg-brand-500/30 blur-3xl" />
        <div className="pointer-events-none absolute -bottom-40 -left-20 h-96 w-96 rounded-full bg-sky-400/20 blur-3xl" />

        <div className="relative flex items-center gap-3">
          <Logo className="h-10 w-10" />
          <span className="text-xl font-semibold tracking-tight">Devolut</span>
        </div>

        <div className="relative max-w-md">
          <h2 className="text-4xl leading-tight font-semibold tracking-tight">
            Votre argent,
            <br />
            <span className="bg-gradient-to-r from-brand-300 to-accent bg-clip-text text-transparent">sans interruption.</span>
          </h2>
          <ul className="mt-10 space-y-5">
            {FEATURES.map(([title, text]) => (
              <li key={title} className="flex gap-4">
                <span className="mt-0.5 flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-white/10 ring-1 ring-white/20">
                  <svg viewBox="0 0 20 20" className="h-3.5 w-3.5 fill-accent" aria-hidden="true">
                    <path d="M7.6 13.4 4.2 10l-1.2 1.2 4.6 4.6 10-10-1.2-1.2z" />
                  </svg>
                </span>
                <div>
                  <p className="font-medium">{title}</p>
                  <p className="text-sm text-brand-200">{text}</p>
                </div>
              </li>
            ))}
          </ul>
        </div>

        <p className="relative text-sm text-brand-300">Donne les sous</p>
      </aside>

      {/* Formulaire */}
      <main className="flex items-center justify-center px-4 py-12">
        <div className="animate-fade-up w-full max-w-sm">
          <div className="mb-8 text-center lg:text-left">
            <Logo className="mx-auto mb-5 h-14 w-14 lg:hidden" />
            <h1 className="text-3xl font-semibold tracking-tight">Bon retour</h1>
            <p className="mt-2 text-sm text-slate-500">Plateforme de paiement en ligne</p>
          </div>

          <form onSubmit={submit} className="space-y-5">
            <label className="block">
              <span className="label">Identifiant</span>
              <input
                className="field"
                autoComplete="username"
                placeholder="ex. alice"
                value={username}
                onChange={(e) => setUsername(e.target.value)}
                required
              />
            </label>
            <label className="block">
              <span className="label">Mot de passe</span>
              <input
                type="password"
                className="field"
                autoComplete="current-password"
                placeholder="••••••••"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                required
              />
            </label>
            {needOtp && (
              <label className="animate-fade-up block">
                <span className="label">Code de vérification</span>
                <input
                  inputMode="numeric"
                  pattern="\d{6}"
                  maxLength={6}
                  autoComplete="one-time-code"
                  placeholder="000000"
                  className="field text-center text-lg tracking-[0.5em]"
                  value={otp}
                  onChange={(e) => setOtp(e.target.value.replace(/\D/g, ""))}
                  required
                />
              </label>
            )}
            {error && <Alert tone={needOtp && !otp ? "warning" : "error"}>{error}</Alert>}
            <button type="submit" disabled={busy} className="btn-primary">
              {busy && <Spinner />}
              {busy ? "Connexion…" : "Se connecter"}
            </button>
          </form>

          <p className="mt-8 flex items-center justify-center gap-2 text-xs text-slate-400 lg:justify-start">
            <svg viewBox="0 0 20 20" className="h-3.5 w-3.5 fill-current" aria-hidden="true">
              <path d="M10 1 3 4v5c0 4.4 3 8.6 7 10 4-1.4 7-5.6 7-10V4z" />
            </svg>
            Connexion chiffrée et protégée
          </p>
          <p className="mt-2 text-center text-xs text-slate-400 lg:hidden">Donne les sous</p>
        </div>
      </main>
    </div>
  );
}
