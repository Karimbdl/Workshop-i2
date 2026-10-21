import { useCallback, useEffect, useRef, useState } from "react";
import QRCode from "qrcode";
import { api, ApiError, face, faceSnapshotUrl } from "../api.js";
import { Alert, Pill, Spinner } from "./ui.jsx";

const ROLE_LABEL = { operator: "Opérateur", admin: "Administrateur" };

// Vignette vidéo de la webcam (images rafraîchies en boucle), pour l'enrôlement.
function CameraView() {
  const ref = useRef(null);
  useEffect(() => {
    let active = true;
    const tick = () => {
      if (active && ref.current) ref.current.src = `${faceSnapshotUrl}?t=${Date.now()}`;
    };
    tick();
    const id = setInterval(tick, 150);
    return () => { active = false; clearInterval(id); };
  }, []);
  return (
    <div className="relative flex aspect-video items-center justify-center overflow-hidden rounded-xl border border-grape-500/20 bg-slate-950/60">
      <img ref={ref} alt="Webcam" className="absolute inset-0 h-full w-full object-cover" />
      <span className="scan-line absolute left-[6%] right-[6%] h-px bg-gradient-to-r from-transparent via-grape-300 to-transparent" />
    </div>
  );
}

export default function Habilitations({ session }) {
  const [users, setUsers] = useState([]);
  const [faces, setFaces] = useState(null); // liste des noms enrôlés, ou null si face-agent injoignable
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [notice, setNotice] = useState(null);

  // Création
  const [form, setForm] = useState({ username: "", display_name: "", password: "", role: "operator" });
  const [creating, setCreating] = useState(false);
  const [created, setCreated] = useState(null); // { username, mfa_secret, otp_uri, qr }

  // Enrôlement du visage
  const [enrollFor, setEnrollFor] = useState(null); // username en cours d'enrôlement
  const [enrolling, setEnrolling] = useState(false);
  const [confirmDelete, setConfirmDelete] = useState(null);

  const refresh = useCallback(async () => {
    try {
      const res = await api.users.list(session.token);
      setUsers(res.data.users || []);
      setError(null);
    } catch (err) {
      setError(err.message || "Impossible de charger les comptes.");
    }
    // Les visages sont servis par le face-agent (PC hôte) : échec non bloquant.
    try {
      const f = await face.list();
      setFaces(f.enrolled || []);
    } catch {
      setFaces(null);
    }
    setLoading(false);
  }, [session.token]);

  useEffect(() => { refresh(); }, [refresh]);

  async function submitCreate(e) {
    e.preventDefault();
    setError(null);
    setCreating(true);
    try {
      const { data } = await api.users.create(session.token, form);
      const qr = await QRCode.toDataURL(data.otp_uri, { margin: 1, width: 220 }).catch(() => null);
      setCreated({ username: data.username, mfa_secret: data.mfa_secret, otp_uri: data.otp_uri, qr });
      setForm({ username: "", display_name: "", password: "", role: "operator" });
      refresh();
    } catch (err) {
      setError(err.message || "Création impossible.");
    } finally {
      setCreating(false);
    }
  }

  async function toggleActive(u) {
    setNotice(null);
    try {
      await api.users.update(session.token, u.username, { is_active: !u.is_active });
      refresh();
    } catch (err) {
      setError(err.message || "Mise à jour impossible.");
    }
  }

  async function removeUser(username) {
    setConfirmDelete(null);
    try {
      await api.users.remove(session.token, username);
      // On retire aussi son visage si le face-agent est joignable.
      face.remove(username).catch(() => {});
      setNotice(`Compte « ${username} » supprimé.`);
      refresh();
    } catch (err) {
      setError(err.message || "Suppression impossible.");
    }
  }

  async function doEnroll(username) {
    setEnrolling(true);
    setError(null);
    try {
      const res = await face.enroll(username);
      if (res.ok) {
        setNotice(`Visage enrôlé pour « ${username} » (${res.shots} prises).`);
        setEnrollFor(null);
        refresh();
      } else {
        setError(res.detail || "Enrôlement échoué.");
      }
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Service de reconnaissance injoignable.");
    } finally {
      setEnrolling(false);
    }
  }

  async function removeFace(username) {
    try {
      await face.remove(username);
      setNotice(`Visage retiré pour « ${username} ».`);
      refresh();
    } catch (err) {
      setError(err.message || "Service de reconnaissance injoignable.");
    }
  }

  const hasFace = (username) => Array.isArray(faces) && faces.includes(username);

  return (
    <div className="space-y-6">
      {error && <Alert tone="warning">{error}</Alert>}
      {notice && <Alert tone="success">{notice}</Alert>}
      {faces === null && (
        <Alert tone="info">
          Service de reconnaissance injoignable : l'enrôlement des visages est indisponible.
          Lancez le face-agent sur le PC hôte (port 8070).
        </Alert>
      )}

      {/* Création d'un compte */}
      <section className="panel p-5">
        <h2 className="mb-4 text-sm font-semibold text-slate-200">Créer un compte</h2>
        <form onSubmit={submitCreate} className="grid gap-3 sm:grid-cols-2 lg:grid-cols-5">
          <div className="lg:col-span-1">
            <label className="label">Identifiant</label>
            <input className="field" value={form.username} required
              onChange={(e) => setForm({ ...form, username: e.target.value })} placeholder="ex. ops2" />
          </div>
          <div className="lg:col-span-1">
            <label className="label">Nom affiché</label>
            <input className="field" value={form.display_name} required
              onChange={(e) => setForm({ ...form, display_name: e.target.value })} placeholder="ex. Opérateur 2" />
          </div>
          <div className="lg:col-span-1">
            <label className="label">Mot de passe</label>
            <input className="field" type="password" value={form.password} required minLength={8}
              onChange={(e) => setForm({ ...form, password: e.target.value })} placeholder="8 car. min." />
          </div>
          <div className="lg:col-span-1">
            <label className="label">Rôle</label>
            <select className="field" value={form.role}
              onChange={(e) => setForm({ ...form, role: e.target.value })}>
              <option value="operator">Opérateur</option>
              <option value="admin">Administrateur</option>
            </select>
          </div>
          <div className="flex items-end lg:col-span-1">
            <button type="submit" className="btn-primary" disabled={creating}>
              {creating ? <Spinner /> : "Créer le compte"}
            </button>
          </div>
        </form>

        {created && (
          <div className="mt-5 flex flex-col gap-4 rounded-xl bg-emerald-500/5 p-4 ring-1 ring-emerald-500/20 sm:flex-row sm:items-center">
            {created.qr && <img src={created.qr} alt="QR code MFA" className="h-40 w-40 rounded-lg bg-white p-2" />}
            <div className="space-y-1.5 text-sm">
              <p className="font-semibold text-emerald-200">Compte « {created.username} » créé.</p>
              <p className="text-slate-300">Scannez ce QR code dans une application d'authentification (Google Authenticator, etc.).</p>
              <p className="text-slate-400">Clé manuelle : <span className="select-all font-mono text-grape-200">{created.mfa_secret}</span></p>
              <p className="text-xs text-slate-500">Ce code ne sera plus affiché. L'opérateur en a besoin pour se connecter.</p>
              <button className="btn-ghost mt-1 text-xs" onClick={() => setCreated(null)}>Fermer</button>
            </div>
          </div>
        )}
      </section>

      {/* Liste des comptes */}
      <section className="panel p-5">
        <h2 className="mb-4 text-sm font-semibold text-slate-200">Comptes de supervision</h2>
        {loading ? (
          <p className="text-sm text-slate-500"><Spinner /></p>
        ) : users.length === 0 ? (
          <p className="text-sm text-slate-500">Aucun compte.</p>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-left text-sm">
              <thead className="text-xs uppercase tracking-wide text-slate-500">
                <tr className="border-b border-slate-800">
                  <th className="pb-2 pr-4 font-semibold">Identifiant</th>
                  <th className="pb-2 pr-4 font-semibold">Nom</th>
                  <th className="pb-2 pr-4 font-semibold">Rôle</th>
                  <th className="pb-2 pr-4 font-semibold">État</th>
                  <th className="pb-2 pr-4 font-semibold">MFA</th>
                  <th className="pb-2 pr-4 font-semibold">Visage</th>
                  <th className="pb-2 font-semibold">Actions</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-800/70">
                {users.map((u) => {
                  const self = u.username === session.username;
                  return (
                    <tr key={u.username} className="align-middle text-slate-300">
                      <td className="py-2.5 pr-4 font-mono text-slate-200">{u.username}{self && <span className="ml-1 text-xs text-slate-500">(vous)</span>}</td>
                      <td className="py-2.5 pr-4">{u.display_name}</td>
                      <td className="py-2.5 pr-4">{ROLE_LABEL[u.role] || u.role}</td>
                      <td className="py-2.5 pr-4"><Pill tone={u.is_active ? "emerald" : "slate"}>{u.is_active ? "actif" : "désactivé"}</Pill></td>
                      <td className="py-2.5 pr-4"><Pill tone={u.mfa_enabled ? "emerald" : "amber"}>{u.mfa_enabled ? "oui" : "non"}</Pill></td>
                      <td className="py-2.5 pr-4">
                        {faces === null ? <span className="text-xs text-slate-600">—</span>
                          : <Pill tone={hasFace(u.username) ? "emerald" : "slate"}>{hasFace(u.username) ? "enrôlé" : "aucun"}</Pill>}
                      </td>
                      <td className="py-2.5">
                        <div className="flex flex-wrap items-center gap-2">
                          {faces !== null && (
                            <button className="btn-ghost text-xs" onClick={() => { setEnrollFor(u.username); setCreated(null); }}>
                              {hasFace(u.username) ? "Réenrôler" : "Enrôler le visage"}
                            </button>
                          )}
                          {faces !== null && hasFace(u.username) && (
                            <button className="btn-ghost text-xs" onClick={() => removeFace(u.username)}>Retirer visage</button>
                          )}
                          <button className="btn-ghost text-xs" onClick={() => toggleActive(u)} disabled={self}>
                            {u.is_active ? "Désactiver" : "Activer"}
                          </button>
                          {confirmDelete === u.username ? (
                            <span className="inline-flex items-center gap-1.5">
                              <button className="rounded-lg bg-rose-500/20 px-2 py-1 text-xs font-medium text-rose-200 ring-1 ring-rose-500/40" onClick={() => removeUser(u.username)}>Confirmer</button>
                              <button className="btn-ghost text-xs" onClick={() => setConfirmDelete(null)}>Annuler</button>
                            </span>
                          ) : (
                            <button className="btn-ghost text-xs text-rose-300" onClick={() => setConfirmDelete(u.username)} disabled={self}>Supprimer</button>
                          )}
                        </div>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </section>

      {/* Panneau d'enrôlement du visage */}
      {enrollFor && (
        <div className="fixed inset-0 z-30 flex items-center justify-center bg-slate-950/70 p-4 backdrop-blur-sm" onClick={() => !enrolling && setEnrollFor(null)}>
          <div className="auth-card w-full max-w-md" onClick={(e) => e.stopPropagation()}>
            <h3 className="mb-1 text-lg font-bold"><span className="gradient-text">Enrôler le visage</span></h3>
            <p className="mb-4 text-sm text-slate-400">Compte : <span className="font-mono text-slate-200">{enrollFor}</span>. Placez le visage face à la caméra, bien éclairé.</p>
            <CameraView />
            <div className="mt-4 flex gap-2">
              <button className="btn-primary flex-1" onClick={() => doEnroll(enrollFor)} disabled={enrolling}>
                {enrolling ? <span className="inline-flex items-center gap-2"><Spinner /> Capture…</span> : "Capturer le visage"}
              </button>
              <button className="btn-ghost" onClick={() => setEnrollFor(null)} disabled={enrolling}>Fermer</button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
