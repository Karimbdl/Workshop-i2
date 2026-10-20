// Petits éléments d'interface partagés.

const AVATAR_COLORS = [
  "bg-sky-100 text-sky-700",
  "bg-violet-100 text-violet-700",
  "bg-emerald-100 text-emerald-700",
  "bg-amber-100 text-amber-700",
  "bg-rose-100 text-rose-700",
  "bg-indigo-100 text-indigo-700",
];

export function initials(name = "") {
  const parts = name.trim().split(/\s+/).filter(Boolean);
  if (!parts.length) return "?";
  return (parts[0][0] + (parts[1]?.[0] || "")).toUpperCase();
}

export function Avatar({ name, size = "h-10 w-10 text-sm" }) {
  let hash = 0;
  for (const c of name || "") hash = (hash * 31 + c.charCodeAt(0)) >>> 0;
  const color = AVATAR_COLORS[hash % AVATAR_COLORS.length];
  return (
    <span className={`inline-flex shrink-0 items-center justify-center rounded-full font-semibold ${size} ${color}`}>
      {initials(name)}
    </span>
  );
}

const STATUS = {
  COMPLETED: ["Exécuté", "bg-emerald-50 text-emerald-700 ring-emerald-600/20", "bg-emerald-500"],
  PENDING: ["En attente", "bg-amber-50 text-amber-700 ring-amber-600/20", "bg-amber-500 animate-pulse"],
  REJECTED: ["Refusé", "bg-rose-50 text-rose-700 ring-rose-600/20", "bg-rose-500"],
};

export function StatusPill({ status }) {
  const [text, cls, dot] = STATUS[status] || [status, "bg-slate-50 text-slate-600 ring-slate-500/20", "bg-slate-400"];
  return (
    <span className={`inline-flex items-center gap-1.5 rounded-full px-2 py-0.5 text-xs font-medium ring-1 ring-inset ${cls}`}>
      <span className={`h-1.5 w-1.5 rounded-full ${dot}`} />
      {text}
    </span>
  );
}

export function Spinner() {
  return <span className="h-4 w-4 animate-spin rounded-full border-2 border-white/40 border-t-white" aria-hidden="true" />;
}

export function Alert({ tone = "error", children }) {
  const tones = {
    error: "bg-rose-50 text-rose-700 ring-rose-200",
    warning: "bg-amber-50 text-amber-800 ring-amber-200",
    success: "bg-emerald-50 text-emerald-800 ring-emerald-200",
  };
  return <div className={`rounded-2xl px-4 py-3 text-sm ring-1 ${tones[tone]}`}>{children}</div>;
}

// Nom lisible d'un compte : « Compte courant Bob Durand » → Bob Durand (Particulier),
// « Boutique en ligne NovaShop » → NovaShop (Boutique en ligne).
export function party(label = "") {
  const person = label.match(/^Compte courant (.+)$/);
  if (person) return { name: person[1], sub: "Particulier" };
  if (label.startsWith("Compte ")) return { name: label, sub: "Compte" };
  const words = label.trim().split(/\s+/);
  if (words.length < 2) return { name: label, sub: "Commerçant" };
  return { name: words[words.length - 1], sub: words.slice(0, -1).join(" ") };
}

export function shortAccount(label = "") {
  return label.replace(/^(Compte courant) .+$/, "$1");
}
