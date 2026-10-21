// Petits éléments d'interface partagés de la console.

export function Spinner() {
  return <span className="h-4 w-4 animate-spin rounded-full border-2 border-white/30 border-t-white" aria-hidden="true" />;
}

export function Alert({ tone = "error", children }) {
  const tones = {
    error: "bg-rose-500/10 text-rose-300 ring-rose-500/30",
    warning: "bg-amber-500/10 text-amber-300 ring-amber-500/30",
    success: "bg-emerald-500/10 text-emerald-300 ring-emerald-500/30",
    info: "bg-brand-500/10 text-brand-200 ring-brand-500/30",
  };
  return <div className={`rounded-xl px-4 py-3 text-sm ring-1 ${tones[tone]}`}>{children}</div>;
}

// Pastille d'état colorée (services, incidents).
export function Pill({ tone = "slate", children }) {
  const tones = {
    emerald: "bg-emerald-500/10 text-emerald-300 ring-emerald-500/30",
    amber: "bg-amber-500/10 text-amber-300 ring-amber-500/30",
    rose: "bg-rose-500/10 text-rose-300 ring-rose-500/30",
    brand: "bg-brand-500/10 text-brand-200 ring-brand-500/30",
    slate: "bg-slate-500/10 text-slate-300 ring-slate-500/30",
  };
  return (
    <span className={`inline-flex items-center gap-1.5 rounded-full px-2.5 py-0.5 text-xs font-medium ring-1 ring-inset ${tones[tone]}`}>
      {children}
    </span>
  );
}

// Indicateur visuel reproduisant à l'écran l'état de la LED pilotée par l'ESP8266.
// state : "off" | "green-blink" | "green" | "red" | "red-blink"
export function LedIndicator({ state = "off" }) {
  const map = {
    off: ["bg-slate-700", "", "Éteinte"],
    "green-blink": ["bg-emerald-400", "led-blink", "Verte clignotante"],
    green: ["bg-emerald-400", "", "Verte fixe"],
    red: ["bg-rose-500", "", "Rouge fixe"],
    "red-blink": ["bg-rose-500", "led-blink", "Rouge clignotante"],
  };
  const [color, anim, text] = map[state] || map.off;
  const lit = state !== "off";
  return (
    <div className="flex items-center gap-2 text-xs text-slate-400">
      <span
        className={`h-3 w-3 rounded-full ${color} ${anim} ${lit ? "shadow-[0_0_10px_2px_currentColor]" : ""}`}
        aria-hidden="true"
      />
      <span>LED : {text}</span>
    </div>
  );
}
