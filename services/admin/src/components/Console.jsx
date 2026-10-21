import { useCallback, useEffect, useRef, useState } from "react";
import { api, ApiError, formatTime } from "../api.js";
import { Alert, Pill, Spinner } from "./ui.jsx";

const REFRESH_MS = 10_000;
const GRAVITE_TONE = { "élevée": "rose", "moyenne": "amber", "faible": "slate" };

export default function Console({ session, onLogout }) {
  const [overview, setOverview] = useState(null);
  const [incidents, setIncidents] = useState([]);
  const [services, setServices] = useState([]);
  const [remediations, setRemediations] = useState(null); // { list, engineConnected }
  const [error, setError] = useState(null);
  const [loading, setLoading] = useState(true);
  const [updatedAt, setUpdatedAt] = useState(null);
  const timer = useRef(null);

  const refresh = useCallback(async () => {
    try {
      const [ov, inc, svc, rem] = await Promise.all([
        api.overview(session.token),
        api.incidents(session.token),
        api.services(session.token),
        api.remediations(session.token),
      ]);
      setOverview(ov.data);
      setIncidents(inc.data.incidents || []);
      setServices(svc.data.services || []);
      setRemediations({ list: rem.data.remediations || [], engineConnected: rem.data.engine_connected });
      setError(null);
      setUpdatedAt(Date.now());
    } catch (err) {
      // Jeton expiré : on renvoie vers l'écran de connexion.
      if (err instanceof ApiError && err.status === 401) {
        onLogout();
        return;
      }
      setError(err.message || "Impossible de récupérer les données.");
    } finally {
      setLoading(false);
    }
  }, [session.token, onLogout]);

  useEffect(() => {
    refresh();
    timer.current = setInterval(refresh, REFRESH_MS);
    return () => clearInterval(timer.current);
  }, [refresh]);

  const phase = overview?.detector_state;
  const score = overview?.anomaly_score;

  const kpis = [
    { label: "Incidents actifs", value: overview ? (overview.incident_active ? "1" : "0") : "·" },
    { label: "Services en ligne", value: overview ? `${overview.services_up} / ${overview.services_total}` : "·" },
    { label: "Score d'anomalie", value: score == null ? "·" : score.toFixed(3) },
    { label: "Requêtes bloquées (WAF)", value: overview?.waf_blocked_total ?? "·" },
  ];

  return (
    <div className="min-h-screen">
      <header className="sticky top-0 z-10 border-b border-slate-800 bg-slate-950/80 backdrop-blur">
        <div className="mx-auto flex max-w-6xl items-center justify-between px-4 py-3">
          <div className="flex items-center gap-3">
            <span className="inline-flex items-center gap-2 rounded-lg bg-gradient-to-r from-brand-500/15 to-grape-500/15 px-2.5 py-1 text-xs font-semibold text-grape-200 ring-1 ring-grape-500/30">
              RESILIENCE-ALPHA
            </span>
            <span className="text-sm font-medium text-slate-300">Supervision & remédiation</span>
            {phase && (
              <Pill tone={phase === "surveillance" ? "emerald" : "amber"}>
                détecteur : {phase}
              </Pill>
            )}
          </div>
          <div className="flex items-center gap-3 text-sm">
            <div className="text-right">
              <div className="font-medium text-white">{session.displayName}</div>
              <div className="text-xs text-slate-400">{session.role}</div>
            </div>
            <button className="btn-ghost" onClick={onLogout}>Déconnexion</button>
          </div>
        </div>
      </header>

      <main className="mx-auto max-w-6xl space-y-6 px-4 py-6">
        <div className="flex items-center justify-between">
          <p className="text-xs text-slate-500">
            {loading ? "Chargement…" : updatedAt ? `Mis à jour ${formatTime(updatedAt)}` : ""}
          </p>
          <button className="btn-ghost text-xs" onClick={refresh}>Rafraîchir</button>
        </div>

        {error && <Alert tone="warning">{error}</Alert>}

        {/* Indicateurs clés */}
        <section className="grid grid-cols-2 gap-3 sm:grid-cols-4">
          {kpis.map((k) => (
            <div key={k.label} className="panel p-4">
              <div className="text-2xl font-bold text-white">{k.value}</div>
              <div className="mt-1 text-xs text-slate-400">{k.label}</div>
            </div>
          ))}
        </section>

        <div className="grid gap-6 lg:grid-cols-3">
          {/* Incidents en direct */}
          <section className="panel p-5 lg:col-span-2">
            <h2 className="mb-4 text-sm font-semibold text-slate-200">Incidents en direct</h2>
            {incidents.length === 0 ? (
              <p className="text-sm text-slate-500">
                {loading ? <Spinner /> : "Aucun incident."}
              </p>
            ) : (
              <ul className="space-y-3">
                {incidents.map((i) => (
                  <li key={i.id} className="rounded-xl bg-slate-800/40 p-4 ring-1 ring-slate-800">
                    <div className="flex items-center justify-between">
                      <span className="font-mono text-sm text-slate-300">{i.id}</span>
                      <Pill tone={GRAVITE_TONE[i.gravite] || "slate"}>{i.gravite}</Pill>
                    </div>
                    <div className="mt-2 flex flex-wrap items-center gap-x-4 gap-y-1 text-sm text-slate-400">
                      <span className="font-medium text-slate-200">{i.label || i.type}</span>
                      {i.started_at && <span>depuis {formatTime(i.started_at)}</span>}
                      {i.peak_score != null && <span>score {Number(i.peak_score).toFixed(3)}</span>}
                    </div>
                    {i.causes?.length > 0 && (
                      <div className="mt-2 flex flex-wrap gap-1.5">
                        {i.causes.map((c) => <Pill key={c} tone="slate">{c}</Pill>)}
                      </div>
                    )}
                  </li>
                ))}
              </ul>
            )}
          </section>

          {/* État des services */}
          <section className="panel p-5">
            <h2 className="mb-4 text-sm font-semibold text-slate-200">État des services</h2>
            {services.length === 0 ? (
              <p className="text-sm text-slate-500">{loading ? <Spinner /> : "Indisponible."}</p>
            ) : (
              <ul className="space-y-2">
                {services.map((s) => (
                  <li key={s.name} className="flex items-center justify-between text-sm">
                    <span className="text-slate-300">{s.label}</span>
                    <Pill tone={s.up ? "emerald" : "rose"}>{s.up ? "en ligne" : "hors ligne"}</Pill>
                  </li>
                ))}
              </ul>
            )}
          </section>
        </div>

        {/* Historique des remédiations */}
        <section className="panel p-5">
          <h2 className="mb-4 text-sm font-semibold text-slate-200">Historique des remédiations</h2>
          {remediations && remediations.list.length === 0 ? (
            <Alert tone="info">
              {remediations.engineConnected
                ? "Aucune remédiation."
                : "Moteur de remédiation pas encore branché."}
            </Alert>
          ) : remediations ? (
            <div className="overflow-x-auto">
              <table className="w-full text-left text-sm">
                <thead className="text-xs uppercase tracking-wide text-slate-500">
                  <tr className="border-b border-slate-800">
                    <th className="pb-2 pr-4 font-semibold">Heure</th>
                    <th className="pb-2 pr-4 font-semibold">Incident</th>
                    <th className="pb-2 pr-4 font-semibold">Action</th>
                    <th className="pb-2 font-semibold">Résultat</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-800/70">
                  {remediations.list.map((r, idx) => (
                    <tr key={idx} className="text-slate-300">
                      <td className="py-2 pr-4 whitespace-nowrap text-slate-400">{formatTime(r.at)}</td>
                      <td className="py-2 pr-4"><span className="font-medium text-slate-200">{r.incident}</span></td>
                      <td className="py-2 pr-4">{r.action}</td>
                      <td className="py-2"><Pill tone="emerald">{r.resultat}</Pill></td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : (
            <p className="text-sm text-slate-500"><Spinner /></p>
          )}
        </section>
      </main>
    </div>
  );
}
