import { formatEuros } from "../api.js";

const GRADIENTS = [
  "from-brand-600 via-brand-800 to-brand-950",
  "from-slate-700 via-slate-800 to-slate-950",
  "from-sky-500 via-brand-600 to-brand-900",
];

function groupIban(iban) {
  return iban.replace(/(.{4})/g, "$1 ").trim();
}

// Compte présenté comme une carte bancaire.
export default function AccountCard({ account, variant = 0 }) {
  const frozen = account.status !== "ACTIVE";
  return (
    <div
      className={`animate-fade-up relative overflow-hidden rounded-3xl bg-gradient-to-br p-6 text-white shadow-xl shadow-brand-900/20 ${GRADIENTS[variant % GRADIENTS.length]} ${frozen ? "grayscale" : ""}`}
    >
      <div className="pointer-events-none absolute -top-16 -right-16 h-48 w-48 rounded-full bg-white/10" />
      <div className="pointer-events-none absolute -right-4 -bottom-24 h-56 w-56 rounded-full bg-white/5" />

      <div className="relative flex items-start justify-between">
        <div>
          <p className="text-sm font-medium text-white/70">{account.label}</p>
          <p className="mt-2 text-3xl font-semibold tracking-tight tabular-nums">{formatEuros(account.balance)}</p>
        </div>
        {/* Puce de carte */}
        <div className="h-8 w-11 rounded-md bg-gradient-to-br from-amber-200 to-amber-400 opacity-90 ring-1 ring-black/10" />
      </div>

      <div className="relative mt-10 flex items-end justify-between gap-3">
        <p className="font-mono text-xs tracking-wider text-white/70">{groupIban(account.iban)}</p>
        {frozen ? (
          <span className="rounded-full bg-rose-500/90 px-2.5 py-0.5 text-xs font-semibold">Compte gelé</span>
        ) : (
          <span className="text-sm font-semibold tracking-tight text-white/90 italic">Devolut</span>
        )}
      </div>
    </div>
  );
}
