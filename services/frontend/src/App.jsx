import { useCallback, useEffect, useMemo, useState } from "react";
import { api, formatEuros, loadSession, saveSession } from "./api.js";
import AccountCard from "./components/AccountCard.jsx";
import History from "./components/History.jsx";
import Login from "./components/Login.jsx";
import Logo from "./components/Logo.jsx";
import PaymentForm from "./components/PaymentForm.jsx";
import { Alert, Avatar } from "./components/ui.jsx";

function greeting() {
  const hour = new Date().getHours();
  return hour >= 18 || hour < 5 ? "Bonsoir" : "Bonjour";
}

export default function App() {
  const [session, setSession] = useState(loadSession);
  const [accounts, setAccounts] = useState([]);
  const [payments, setPayments] = useState([]);
  const [beneficiaries, setBeneficiaries] = useState([]);
  const [loaded, setLoaded] = useState(false);
  const [error, setError] = useState("");

  const login = (s) => {
    saveSession(s);
    setSession(s);
  };
  const logout = useCallback(() => {
    saveSession(null);
    setSession(null);
    setAccounts([]);
    setPayments([]);
    setBeneficiaries([]);
    setLoaded(false);
  }, []);

  const refresh = useCallback(async () => {
    if (!session || session.role !== "client") return;
    try {
      const [acc, pay] = await Promise.all([api.accounts(session.token), api.payments(session.token)]);
      setAccounts(acc.data);
      setPayments(pay.data);
      setError("");
    } catch (err) {
      if (err.status === 401) logout();
      else setError(err.message);
    } finally {
      setLoaded(true);
    }
  }, [session, logout]);

  useEffect(() => {
    refresh();
    // Rafraîchissement régulier : un paiement en attente passe à « exécuté » sans action de l'utilisateur.
    const timer = setInterval(refresh, 5000);
    return () => clearInterval(timer);
  }, [refresh]);

  useEffect(() => {
    if (!session || session.role !== "client") return;
    api
      .beneficiaries(session.token)
      .then(({ data }) => setBeneficiaries(data))
      .catch((err) => (err.status === 401 ? logout() : null));
  }, [session, logout]);

  const names = useMemo(() => Object.fromEntries(beneficiaries.map((b) => [b.iban, b.label])), [beneficiaries]);
  const total = accounts.reduce((sum, a) => sum + Number(a.balance), 0);
  const month = new Date().toISOString().slice(0, 7);
  const spent = payments
    .filter((p) => p.status === "COMPLETED" && p.created_at.startsWith(month))
    .reduce((sum, p) => sum + Number(p.amount), 0);
  const pending = payments.filter((p) => p.status === "PENDING").length;

  if (!session) return <Login onLogin={login} />;

  const firstName = (session.displayName || session.username).split(" ")[0];

  return (
    <div className="min-h-screen">
      <header className="sticky top-0 z-10 border-b border-slate-200/70 bg-white/80 backdrop-blur-md">
        <div className="mx-auto flex max-w-6xl items-center justify-between px-4 py-3">
          <div className="flex items-center gap-2.5">
            <Logo className="h-8 w-8" />
            <span className="text-lg font-semibold tracking-tight">Devolut</span>
          </div>
          <div className="flex items-center gap-3">
            <div className="hidden text-right sm:block">
              <p className="text-sm leading-tight font-medium">{session.displayName}</p>
              <p className="text-xs leading-tight text-slate-500">Espace client</p>
            </div>
            <Avatar name={session.displayName || session.username} size="h-9 w-9 text-sm" />
            <button
              onClick={logout}
              className="ml-1 inline-flex items-center gap-2 rounded-xl border border-slate-200 px-3 py-2 text-sm font-medium text-slate-600 transition hover:border-slate-300 hover:bg-slate-50 hover:text-slate-900"
            >
              <svg viewBox="0 0 24 24" className="h-5 w-5 fill-none stroke-current" strokeWidth="1.8" aria-hidden="true">
                <path d="M15 4h3a2 2 0 0 1 2 2v12a2 2 0 0 1-2 2h-3M10 17l5-5-5-5M15 12H3" strokeLinecap="round" strokeLinejoin="round" />
              </svg>
              <span>Déconnexion</span>
            </button>
          </div>
        </div>
      </header>

      <main className="mx-auto max-w-6xl space-y-8 px-4 py-8">
        {session.role !== "client" ? (
          <Alert tone="warning">L'espace client est réservé aux clients. Les opérateurs utilisent la console de supervision.</Alert>
        ) : (
          <>
            <section className="grid grid-cols-1 items-center gap-6 lg:grid-cols-[1fr_24rem]">
              <div className="animate-fade-up">
                <p className="text-sm font-medium text-slate-500">
                  {greeting()}, {firstName}
                </p>
                <p className="mt-1 text-4xl font-semibold tracking-tight tabular-nums sm:text-5xl">
                  {loaded ? formatEuros(total) : <span className="inline-block h-12 w-56 animate-pulse rounded-xl bg-slate-200" />}
                </p>
                <p className="mt-1 text-sm text-slate-500">Solde total disponible</p>
                <div className="mt-6 grid max-w-md grid-cols-2 gap-3">
                  <Stat label="Dépenses du mois" value={formatEuros(spent)} />
                  <Stat label="En attente" value={pending} highlight={pending > 0} />
                </div>
              </div>
              <div className="space-y-4">
                {!loaded && <div className="h-48 animate-pulse rounded-3xl bg-slate-200" />}
                {accounts.map((a, i) => (
                  <AccountCard key={a.id} account={a} variant={i} />
                ))}
              </div>
            </section>

            {error && <Alert>{error}</Alert>}

            <div className="grid grid-cols-1 gap-6 lg:grid-cols-5">
              <div className="lg:col-span-2">
                <PaymentForm
                  token={session.token}
                  accounts={accounts}
                  beneficiaries={beneficiaries}
                  onDone={refresh}
                  onAuthError={logout}
                />
              </div>
              <div className="lg:col-span-3">
                <History payments={payments} names={names} />
              </div>
            </div>
          </>
        )}
      </main>

      <footer className="mx-auto max-w-6xl px-4 pt-4 pb-10 text-center text-xs text-slate-400">
        Devolut · Plateforme de paiement en ligne · Donne les sous
      </footer>
    </div>
  );
}

function Stat({ label, value, highlight = false }) {
  return (
    <div className={`card px-4 py-3 ${highlight ? "ring-amber-300" : ""}`}>
      <p className="text-xs font-medium text-slate-500">{label}</p>
      <p className={`mt-1 text-lg font-semibold tabular-nums ${highlight ? "text-amber-600" : ""}`}>{value}</p>
    </div>
  );
}
