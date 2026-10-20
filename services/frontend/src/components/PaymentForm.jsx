import { useEffect, useState } from "react";
import { api, formatEuros, maskIban } from "../api.js";
import { Alert, Avatar, Spinner, party, shortAccount } from "./ui.jsx";

function newKey() {
  return crypto.randomUUID();
}

export default function PaymentForm({ token, accounts, beneficiaries, onDone, onAuthError }) {
  const [debit, setDebit] = useState("");
  const [creditIban, setCreditIban] = useState("");
  const [amount, setAmount] = useState("");
  const [label, setLabel] = useState("");
  // Une clé par intention de paiement : un double clic ou une nouvelle tentative ne débite pas deux fois.
  const [idempotencyKey, setIdempotencyKey] = useState(newKey);
  const [result, setResult] = useState(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (!debit && accounts.length) setDebit(accounts[0].id);
  }, [accounts, debit]);

  async function submit(event) {
    event.preventDefault();
    if (!creditIban) {
      setResult({ status: "ERROR", failure_reason: "Choisissez un bénéficiaire." });
      return;
    }
    setBusy(true);
    setResult(null);
    try {
      const { data } = await api.pay(
        token,
        { debit_account_id: debit, credit_iban: creditIban, amount: amount.replace(",", "."), label },
        idempotencyKey,
      );
      setResult(data);
      if (data.status !== "PENDING") {
        setIdempotencyKey(newKey());
        if (data.status === "COMPLETED") {
          setAmount("");
          setLabel("");
        }
      }
      onDone();
    } catch (err) {
      if (err.status === 401) return onAuthError();
      setResult({ status: "ERROR", failure_reason: err.message });
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="card p-6">
      <div className="flex items-center gap-3">
        <span className="flex h-10 w-10 items-center justify-center rounded-2xl bg-brand-50 text-brand-600">
          <svg viewBox="0 0 24 24" className="h-5 w-5 fill-none stroke-current" strokeWidth="2" aria-hidden="true">
            <path d="M5 12h14M13 6l6 6-6 6" strokeLinecap="round" strokeLinejoin="round" />
          </svg>
        </span>
        <div>
          <h2 className="text-lg font-semibold tracking-tight">Envoyer de l'argent</h2>
          <p className="text-xs text-slate-500">Paiement immédiat vers un bénéficiaire</p>
        </div>
      </div>

      <form onSubmit={submit} className="mt-6 space-y-5">
        <div>
          <span className="label">Bénéficiaire</span>
          <div className="grid grid-cols-2 gap-2">
            {beneficiaries.map((b) => {
              const active = b.iban === creditIban;
              const who = party(b.label);
              return (
                <button
                  type="button"
                  key={b.iban}
                  onClick={() => setCreditIban(b.iban)}
                  aria-pressed={active}
                  title={`${b.label} · ${maskIban(b.iban)}`}
                  className={`flex items-center gap-2.5 rounded-2xl border p-2.5 text-left transition ${
                    active
                      ? "border-brand-500 bg-brand-50 ring-4 ring-brand-100"
                      : "border-slate-200 hover:border-slate-300 hover:bg-slate-50"
                  }`}
                >
                  <Avatar name={who.name} size="h-8 w-8 text-xs" />
                  <span className="min-w-0">
                    <span className="block truncate text-sm font-medium">{who.name}</span>
                    <span className="block truncate text-[11px] text-slate-500">{who.sub}</span>
                  </span>
                </button>
              );
            })}
            {beneficiaries.length === 0 && (
              <p className="col-span-2 text-sm text-slate-400">Chargement des bénéficiaires…</p>
            )}
          </div>
        </div>

        <label className="block">
          <span className="label">Montant</span>
          <div className="relative">
            <input
              className="field pr-10 text-2xl font-semibold tabular-nums"
              inputMode="decimal"
              placeholder="0,00"
              value={amount}
              onChange={(e) => setAmount(e.target.value)}
              pattern="^\d{1,4}([.,]\d{1,2})?$"
              required
            />
            <span className="pointer-events-none absolute inset-y-0 right-4 flex items-center text-xl font-semibold text-slate-400">
              €
            </span>
          </div>
        </label>

        <div className="space-y-5">
          <label className="block">
            <span className="label">Depuis</span>
            <select className="field" value={debit} onChange={(e) => setDebit(e.target.value)} required>
              {accounts.map((a) => (
                <option key={a.id} value={a.id}>
                  {shortAccount(a.label)} · {formatEuros(a.balance)}
                </option>
              ))}
            </select>
          </label>
          <label className="block">
            <span className="label">Libellé</span>
            <input
              className="field"
              maxLength={140}
              placeholder="Facultatif"
              value={label}
              onChange={(e) => setLabel(e.target.value)}
            />
          </label>
        </div>

        <button type="submit" disabled={busy || !accounts.length} className="btn-primary">
          {busy && <Spinner />}
          {busy ? "Envoi en cours…" : amount ? `Payer ${formatAmount(amount)}` : "Payer"}
        </button>
      </form>
      {result && (
        <div className="animate-fade-up mt-4">
          <PaymentResult result={result} />
        </div>
      )}
    </section>
  );
}

function formatAmount(raw) {
  const value = Number(raw.replace(",", "."));
  return Number.isFinite(value) && value > 0 ? formatEuros(value) : "";
}

function PaymentResult({ result }) {
  const styles = {
    COMPLETED: ["success", "Paiement exécuté."],
    PENDING: ["warning", "Paiement enregistré, en attente de traitement : il sera finalisé automatiquement."],
    REJECTED: ["error", `Paiement refusé : ${result.failure_reason || "règle métier"}.`],
    ERROR: ["error", result.failure_reason],
  };
  const [tone, message] = styles[result.status] || styles.ERROR;
  return <Alert tone={tone}>{message}</Alert>;
}
