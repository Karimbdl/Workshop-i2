import { formatEuros, maskIban } from "../api.js";
import { Avatar, StatusPill, party } from "./ui.jsx";

function dayLabel(date) {
  const today = new Date();
  const yesterday = new Date(today);
  yesterday.setDate(today.getDate() - 1);
  if (date.toDateString() === today.toDateString()) return "Aujourd'hui";
  if (date.toDateString() === yesterday.toDateString()) return "Hier";
  return date.toLocaleDateString("fr-FR", { weekday: "long", day: "numeric", month: "long" });
}

// Regroupe les paiements par jour, dans l'ordre reçu (du plus récent au plus ancien).
function groupByDay(payments) {
  const groups = [];
  for (const p of payments) {
    const date = new Date(p.created_at);
    const label = dayLabel(date);
    if (!groups.length || groups[groups.length - 1].label !== label) groups.push({ label, items: [] });
    groups[groups.length - 1].items.push({ ...p, date });
  }
  return groups;
}

export default function History({ payments, names }) {
  return (
    <section className="card p-6">
      <div className="flex items-center justify-between">
        <h2 className="text-lg font-semibold tracking-tight">Activité récente</h2>
        <span className="text-xs text-slate-400">Mise à jour automatique</span>
      </div>

      {payments.length === 0 ? (
        <div className="mt-10 mb-6 text-center">
          <div className="mx-auto flex h-12 w-12 items-center justify-center rounded-2xl bg-slate-100 text-slate-400">
            <svg viewBox="0 0 24 24" className="h-6 w-6 fill-none stroke-current" strokeWidth="1.8" aria-hidden="true">
              <path d="M4 7h16M4 12h16M4 17h10" strokeLinecap="round" />
            </svg>
          </div>
          <p className="mt-3 text-sm font-medium text-slate-600">Aucun paiement pour l'instant</p>
          <p className="text-xs text-slate-400">Vos opérations apparaîtront ici.</p>
        </div>
      ) : (
        <div className="mt-4 space-y-5">
          {groupByDay(payments).map((group) => (
            <div key={group.label}>
              <p className="mb-1 text-xs font-semibold tracking-wide text-slate-400 uppercase first-letter:uppercase">
                {group.label}
              </p>
              <ul className="divide-y divide-slate-100">
                {group.items.map((p) => {
                  const known = names[p.credit_iban];
                  const name = known ? party(known).name : maskIban(p.credit_iban);
                  return (
                    <li key={p.id} className="flex items-center gap-3 py-3">
                      <Avatar name={known ? name : "?"} />
                      <div className="min-w-0 flex-1">
                        <p className="truncate text-sm font-medium">{name}</p>
                        <p className="truncate text-xs text-slate-500">
                          {p.label || "Paiement"} · {p.date.toLocaleTimeString("fr-FR", { hour: "2-digit", minute: "2-digit" })}
                        </p>
                      </div>
                      <div className="flex shrink-0 flex-col items-end gap-1">
                        <span
                          className={`text-sm font-semibold tabular-nums ${p.status === "REJECTED" ? "text-slate-400 line-through" : ""}`}
                        >
                          −{formatEuros(p.amount)}
                        </span>
                        <StatusPill status={p.status} />
                      </div>
                    </li>
                  );
                })}
              </ul>
            </div>
          ))}
        </div>
      )}
    </section>
  );
}
