import { useEffect, useRef, useState } from "react";
import { api } from "../api.js";
import { Alert, Pill, Spinner } from "./ui.jsx";

// Assistant SOC (RAG) : répond à partir de la documentation du projet et de l'état
// en direct de la plateforme, en citant ses sources. Il n'exécute aucune action.

const SUGGESTIONS = [
  "Que se passe-t-il en ce moment et que dois-je faire ?",
  "Quelle est la conduite à tenir face à une force brute ?",
  "Vault est scellé après un redémarrage, que faire ?",
  "Comment restaurer la plateforme après un sinistre ?",
];

// Rendu minimal et sûr (sans HTML injecté) : gras, code, citations [n], listes.
function Inline({ text }) {
  const parts = text.split(/(\*\*[^*]+\*\*|`[^`]+`|\[\d+\])/g).filter(Boolean);
  return parts.map((p, i) => {
    if (p.startsWith("**") && p.endsWith("**")) return <strong key={i} className="text-white">{p.slice(2, -2)}</strong>;
    if (p.startsWith("`") && p.endsWith("`"))
      return <code key={i} className="rounded bg-slate-800 px-1 py-0.5 text-[0.8em] text-grape-200">{p.slice(1, -1)}</code>;
    if (/^\[\d+\]$/.test(p))
      return <sup key={i} className="mx-0.5 rounded bg-brand-500/20 px-1 text-[0.7em] font-semibold text-brand-200">{p.slice(1, -1)}</sup>;
    return <span key={i}>{p}</span>;
  });
}

function Answer({ text }) {
  const blocks = [];
  let code = null;
  text.split("\n").forEach((line, i) => {
    if (line.trim().startsWith("```")) {
      if (code) { blocks.push(<pre key={`c${i}`} className="overflow-x-auto rounded-lg bg-slate-950 p-3 text-xs text-slate-200 ring-1 ring-slate-800">{code.join("\n")}</pre>); code = null; }
      else code = [];
      return;
    }
    if (code) { code.push(line); return; }
    if (!line.trim()) { blocks.push(<div key={i} className="h-2" />); return; }
    const list = line.match(/^\s*([-*]|\d+\.)\s+(.*)$/);
    if (list) {
      blocks.push(
        <div key={i} className="flex gap-2 pl-1">
          <span className="text-grape-300">{/\d/.test(list[1]) ? list[1] : "•"}</span>
          <span><Inline text={list[2]} /></span>
        </div>
      );
      return;
    }
    blocks.push(<p key={i}><Inline text={line.replace(/^#+\s*/, "")} /></p>);
  });
  if (code) blocks.push(<pre key="c-end" className="overflow-x-auto rounded-lg bg-slate-950 p-3 text-xs text-slate-200">{code.join("\n")}</pre>);
  return <div className="space-y-1 text-sm leading-relaxed text-slate-300">{blocks}</div>;
}

export default function Assistant({ session, onUnauthorized }) {
  const [messages, setMessages] = useState([]);
  const [question, setQuestion] = useState("");
  const [busy, setBusy] = useState(false);
  const [status, setStatus] = useState(null);
  const bottom = useRef(null);

  useEffect(() => {
    api.assistant.status(session.token).then((r) => setStatus(r.data)).catch(() => setStatus({ ready: false }));
  }, [session.token]);

  useEffect(() => { bottom.current?.scrollIntoView({ behavior: "smooth" }); }, [messages, busy]);

  async function ask(q) {
    const text = (q ?? question).trim();
    if (text.length < 3 || busy) return;
    setQuestion("");
    setMessages((m) => [...m, { role: "user", text }]);
    setBusy(true);
    try {
      const { data } = await api.assistant.ask(session.token, text);
      setMessages((m) => [...m, { role: "assistant", ...data }]);
    } catch (err) {
      if (err.status === 401) return onUnauthorized?.();
      setMessages((m) => [...m, { role: "error", text: err.message }]);
    } finally {
      setBusy(false);
    }
  }

  const ready = status?.ready;

  return (
    <section className="panel flex flex-col p-5">
      <div className="mb-4 flex flex-wrap items-center justify-between gap-2">
        <div>
          <h2 className="text-sm font-semibold text-slate-200">Assistant SOC</h2>
          <p className="text-xs text-slate-500">
            Répond à partir de nos procédures et de l'état en direct. Il ne déclenche aucune action.
          </p>
        </div>
        {status && (
          <Pill tone={ready ? "emerald" : "amber"}>
            {ready ? `${status.chunks} extraits · ${status.sources?.length ?? 0} documents` : "Base documentaire en préparation"}
          </Pill>
        )}
      </div>

      <div className="min-h-[18rem] flex-1 space-y-4">
        {messages.length === 0 && (
          <div className="space-y-3">
            <p className="text-sm text-slate-400">Exemples de questions :</p>
            <div className="flex flex-wrap gap-2">
              {SUGGESTIONS.map((s) => (
                <button key={s} className="btn-ghost text-left text-xs ring-1 ring-slate-700" disabled={busy} onClick={() => ask(s)}>
                  {s}
                </button>
              ))}
            </div>
          </div>
        )}

        {messages.map((m, i) =>
          m.role === "user" ? (
            <div key={i} className="ml-auto max-w-[85%] rounded-2xl rounded-br-sm bg-gradient-to-r from-brand-500/25 to-grape-500/25 px-4 py-2 text-sm text-white ring-1 ring-grape-500/30">
              {m.text}
            </div>
          ) : m.role === "error" ? (
            <Alert key={i} tone="warning">{m.text}</Alert>
          ) : (
            <div key={i} className="max-w-[95%] space-y-3 rounded-2xl rounded-bl-sm bg-slate-900/70 px-4 py-3 ring-1 ring-slate-800">
              {m.contexte?.incident && (
                <div className="text-xs text-amber-300">
                  Incident en cours pris en compte : {m.contexte.incident.label} ({m.contexte.incident.gravite})
                </div>
              )}
              <Answer text={m.answer || ""} />
              {m.sources?.length > 0 && (
                <div className="border-t border-slate-800 pt-2">
                  <div className="mb-1 text-[0.7rem] uppercase tracking-wide text-slate-500">Sources</div>
                  <ul className="space-y-0.5 text-xs text-slate-400">
                    {m.sources.map((s) => (
                      <li key={s.n} title={s.extrait}>
                        <span className="mr-1 font-semibold text-brand-200">[{s.n}]</span>
                        {s.source}{s.section ? ` › ${s.section}` : ""}
                      </li>
                    ))}
                  </ul>
                </div>
              )}
              {m.timings_ms && (
                <div className="text-[0.7rem] text-slate-600">
                  {m.model} · recherche {m.timings_ms.recherche} ms · génération {(m.timings_ms.generation / 1000).toFixed(1)} s
                </div>
              )}
            </div>
          )
        )}

        {busy && (
          <div className="flex items-center gap-2 text-sm text-slate-400">
            <Spinner /> L'assistant consulte la documentation…
          </div>
        )}
        <div ref={bottom} />
      </div>

      <form
        className="mt-4 flex gap-2"
        onSubmit={(e) => { e.preventDefault(); ask(); }}
      >
        <input
          className="field flex-1"
          placeholder={ready === false ? "Assistant indisponible pour le moment" : "Posez une question (incident, procédure, commande…)"}
          value={question}
          maxLength={800}
          onChange={(e) => setQuestion(e.target.value)}
          disabled={busy}
        />
        <button className="btn-primary" disabled={busy || question.trim().length < 3}>
          Envoyer
        </button>
      </form>
    </section>
  );
}
