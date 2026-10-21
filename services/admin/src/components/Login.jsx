import { useEffect, useRef, useState } from "react";
import { api, ApiError, face, saveSession } from "../api.js";
import { Alert, LedIndicator, Spinner } from "./ui.jsx";

const ADMIN_ROLES = ["operator", "admin"];
const BLOCK_MS = 5 * 60 * 1000; // blocage 5 min après 1 réessai raté
const STEPS = [
  { key: "id", label: "Identifiant" },
  { key: "face", label: "Reconnaissance" },
  { key: "password", label: "Mot de passe" },
];

// Login en trois temps (consigne additionnelle 1) :
//   identifiant -> reconnaissance faciale (caméra USB sur l'hôte) -> mot de passe -> console.
// La LED (ESP8266 via MQTT) est pilotée par le face-agent ; on reflète son état à l'écran.
export default function Login({ onAuthenticated }) {
  const [step, setStep] = useState("id");
  const [led, setLed] = useState("off");
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [otp, setOtp] = useState("");
  const [mfaRequired, setMfaRequired] = useState(false);
  const [error, setError] = useState(null);
  const [loading, setLoading] = useState(false);
  const [recognizing, setRecognizing] = useState(false);
  const [recognizedName, setRecognizedName] = useState(null);
  const [faceAttempts, setFaceAttempts] = useState(0);
  const [blockedUntil, setBlockedUntil] = useState(0);
  const [now, setNow] = useState(Date.now());
  const timers = useRef([]);

  useEffect(() => () => timers.current.forEach(clearTimeout), []);
  useEffect(() => {
    const t = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(t);
  }, []);
  const later = (fn, ms) => timers.current.push(setTimeout(fn, ms));

  const blocked = blockedUntil > now;
  const remaining = Math.max(0, blockedUntil - now);
  const mmss = `${String(Math.floor(remaining / 60000)).padStart(2, "0")}:${String(Math.floor((remaining % 60000) / 1000)).padStart(2, "0")}`;

  function resetToId(message) {
    setStep("id");
    setLed("off");
    face.led("off");
    setPassword("");
    setOtp("");
    setMfaRequired(false);
    setUsername("");
    setRecognizedName(null);
    if (message) setError(message);
  }

  // Étape 1 : l'identifiant lance la reconnaissance (la caméra s'active côté hôte).
  function submitIdentifiant(e) {
    e.preventDefault();
    setError(null);
    if (!username.trim() || blocked) return;
    setStep("face");
    setLed("off");
    lancerReconnaissance();
  }

  async function lancerReconnaissance() {
    setRecognizing(true);
    setError(null);
    try {
      const res = await face.recognize();
      setRecognizing(false);
      if (res.recognized) {
        // Reconnu : LED vert clignotant, le mot de passe se débloque.
        setRecognizedName(res.name);
        setFaceAttempts(0);
        setLed("green-blink");
        setStep("password");
      } else {
        // Non reconnu : LED rouge fixe 30 s (gérée par l'ESP), puis on vide et on recommence.
        setLed("red");
        const n = faceAttempts + 1;
        setFaceAttempts(n);
        if (n >= 2) {
          setBlockedUntil(Date.now() + BLOCK_MS);
          setError("Visage non reconnu. Accès bloqué 5 minutes.");
          later(() => resetToId(), 2500);
        } else {
          setError("Visage non reconnu. Réessayez.");
          later(() => { setStep("id"); setUsername(""); setLed("off"); }, 3000);
        }
      }
    } catch (err) {
      setRecognizing(false);
      setError(err.message || "Service de reconnaissance injoignable.");
      later(() => { setStep("id"); setLed("off"); }, 2500);
    }
  }

  // Étape 3 : mot de passe (débloqué après reconnaissance).
  async function submitPassword(e) {
    e.preventDefault();
    setError(null);
    setLoading(true);
    try {
      const { data } = await api.login(username.trim(), password, mfaRequired ? otp : undefined);
      if (!ADMIN_ROLES.includes(data.role)) {
        setLoading(false);
        resetToId("Réservé aux opérateurs.");
        return;
      }
      // Mot de passe bon : LED vert fixe 30 s, puis la console s'ouvre.
      setLed("green");
      face.led("vert_fixe");
      setLoading(false);
      const session = {
        token: data.access_token,
        role: data.role,
        displayName: data.display_name,
        username: username.trim(),
      };
      saveSession(session);
      later(() => onAuthenticated(session), 1200);
    } catch (err) {
      setLoading(false);
      if (err instanceof ApiError && err.status === 401 && err.body?.mfa_required) {
        setMfaRequired(true);
        setError("Code à usage unique requis.");
        return;
      }
      if (err instanceof ApiError && err.status === 401) {
        // Mot de passe faux : LED rouge clignote 10x, puis on recommence l'identification.
        setLed("red-blink");
        face.led("rouge_clignote");
        later(() => resetToId("Mot de passe refusé."), 2600);
        return;
      }
      setError(err.message || "Connexion impossible.");
    }
  }

  const activeIndex = STEPS.findIndex((s) => s.key === step);

  return (
    <div className="relative flex min-h-screen items-center justify-center overflow-hidden p-4">
      <div className="pointer-events-none absolute inset-0 -z-10">
        <div className="blob absolute -left-24 top-10 h-80 w-80 rounded-full bg-brand-600/30 blur-3xl" />
        <div className="blob absolute right-0 top-1/3 h-96 w-96 rounded-full bg-grape-600/30 blur-3xl" style={{ animationDelay: "-4s" }} />
        <div className="blob absolute bottom-0 left-1/3 h-72 w-72 rounded-full bg-grape-500/20 blur-3xl" style={{ animationDelay: "-8s" }} />
      </div>

      <div className="auth-card w-full max-w-md">
        <header className="mb-6">
          <div className="mb-3 inline-flex items-center gap-2 rounded-lg bg-gradient-to-r from-brand-500/15 to-grape-500/15 px-2.5 py-1 text-xs font-semibold text-grape-200 ring-1 ring-grape-500/30">
            RESILIENCE-ALPHA
          </div>
          <h1 className="text-2xl font-bold"><span className="gradient-text">Console d'administration</span></h1>
          <p className="mt-1 text-sm text-slate-400">Réservé aux opérateurs.</p>
        </header>

        <div className="mb-6 flex items-center gap-2">
          {STEPS.map((s, i) => (
            <div key={s.key} className="flex flex-1 flex-col gap-1.5">
              <div className={`h-1.5 rounded-full transition-all duration-500 ${i <= activeIndex ? "bg-gradient-to-r from-brand-400 to-grape-400" : "bg-slate-700/70"}`} />
              <span className={`text-[11px] font-medium transition-colors ${i === activeIndex ? "text-grape-200" : "text-slate-500"}`}>{s.label}</span>
            </div>
          ))}
        </div>

        {error && (
          <div className="mb-4 animate-fade-up">
            <Alert tone={led === "red-blink" || led === "red" ? "error" : "warning"}>{error}</Alert>
          </div>
        )}

        <div key={step} className="animate-fade-up">
          {/* Étape 1 — identifiant */}
          {step === "id" && (
            <form onSubmit={submitIdentifiant} className="space-y-4">
              <div>
                <label className="label" htmlFor="username">Identifiant</label>
                <input
                  id="username"
                  className="field"
                  autoFocus
                  autoComplete="username"
                  value={username}
                  disabled={blocked}
                  onChange={(e) => setUsername(e.target.value)}
                  placeholder="ex. ops"
                />
              </div>
              {blocked ? (
                <div className="rounded-xl bg-rose-500/10 px-4 py-3 text-center text-sm text-rose-300 ring-1 ring-rose-500/30">
                  Accès bloqué — réessayez dans <span className="font-mono">{mmss}</span>
                </div>
              ) : (
                <button type="submit" className="btn-primary">Continuer</button>
              )}
            </form>
          )}

          {/* Étape 2 — reconnaissance faciale */}
          {step === "face" && (
            <div className="space-y-4">
              <div className="relative flex aspect-video items-center justify-center overflow-hidden rounded-2xl border border-grape-500/20 bg-slate-950/40">
                <span className="scan-ring absolute h-24 w-24 rounded-full border-2 border-grape-400/50" />
                <span className="scan-ring absolute h-24 w-24 rounded-full border-2 border-brand-400/50" style={{ animationDelay: "-1s" }} />
                <span className="scan-line absolute left-[8%] right-[8%] h-px bg-gradient-to-r from-transparent via-grape-300 to-transparent" />
                <div className="relative z-10 text-center">
                  <div className="mx-auto mb-2 flex h-11 w-11 items-center justify-center rounded-full bg-grape-500/20 ring-1 ring-grape-400/40">
                    <svg className="h-5 w-5 text-grape-200" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7">
                      <path d="M4 8V6a2 2 0 0 1 2-2h2M16 4h2a2 2 0 0 1 2 2v2M20 16v2a2 2 0 0 1-2 2h-2M8 20H6a2 2 0 0 1-2-2v-2" strokeLinecap="round" />
                      <circle cx="12" cy="11" r="2.4" />
                      <path d="M8.5 16.2a3.8 3.8 0 0 1 7 0" strokeLinecap="round" />
                    </svg>
                  </div>
                  <p className="text-sm font-medium text-slate-200">{recognizing ? "Analyse du visage…" : "Caméra active"}</p>
                  <p className="mt-0.5 text-xs text-slate-500">Webcam du PC Hôte</p>
                </div>
              </div>
              <p className="text-center text-xs text-slate-500">Identifiant : <span className="text-slate-300">{username}</span></p>
              <button type="button" className="btn-ghost w-full" onClick={() => resetToId()} disabled={recognizing}>Annuler</button>
            </div>
          )}

          {/* Étape 3 — mot de passe */}
          {step === "password" && (
            <form onSubmit={submitPassword} className="space-y-4">
              {recognizedName && (
                <div className="rounded-xl bg-emerald-500/10 px-4 py-2.5 text-sm text-emerald-300 ring-1 ring-emerald-500/30">
                  Visage reconnu — {recognizedName}
                </div>
              )}
              <div>
                <label className="label" htmlFor="username-ro">Identifiant</label>
                <input id="username-ro" className="field" value={username} disabled />
              </div>
              <div>
                <label className="label" htmlFor="password">Mot de passe</label>
                <input
                  id="password"
                  type="password"
                  className="field"
                  autoFocus
                  autoComplete="current-password"
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                />
              </div>
              {mfaRequired && (
                <div className="animate-fade-up">
                  <label className="label" htmlFor="otp">Code à usage unique</label>
                  <input
                    id="otp"
                    className="field tracking-[0.3em]"
                    inputMode="numeric"
                    maxLength={6}
                    placeholder="000000"
                    value={otp}
                    onChange={(e) => setOtp(e.target.value.replace(/\D/g, ""))}
                  />
                </div>
              )}
              <button type="submit" className="btn-primary" disabled={loading}>
                {loading ? <Spinner /> : "Se connecter"}
              </button>
            </form>
          )}
        </div>

        <footer className="mt-6 border-t border-white/5 pt-4">
          <LedIndicator state={led} />
        </footer>
      </div>
    </div>
  );
}
