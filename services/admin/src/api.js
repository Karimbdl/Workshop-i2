// Client HTTP de la console admin. Les requêtes passent par la passerelle (/api),
// comme l'espace client, pour profiter du pare-feu applicatif.

const SESSION_KEY = "resilience.admin.session";

export function loadSession() {
  try {
    const raw = sessionStorage.getItem(SESSION_KEY);
    return raw ? JSON.parse(raw) : null;
  } catch {
    return null;
  }
}

export function saveSession(session) {
  try {
    if (session) sessionStorage.setItem(SESSION_KEY, JSON.stringify(session));
    else sessionStorage.removeItem(SESSION_KEY);
  } catch {
    // stockage indisponible : la session reste en mémoire
  }
}

export class ApiError extends Error {
  constructor(status, message, body) {
    super(message);
    this.status = status;
    this.body = body;
  }
}

function errorMessage(status, body) {
  if (body && typeof body.detail === "string") return body.detail;
  if (status === 401) return "Identifiant ou mot de passe incorrect.";
  if (status === 403) return "Requête bloquée par le pare-feu applicatif.";
  if (status === 429) return "Trop de tentatives : patientez quelques instants.";
  if (status >= 500) return "Service momentanément indisponible.";
  return `Erreur ${status}`;
}

export async function request(path, { token, method = "GET", body, headers = {} } = {}) {
  let response;
  try {
    response = await fetch(`/api${path}`, {
      method,
      headers: {
        ...(body ? { "Content-Type": "application/json" } : {}),
        ...(token ? { Authorization: `Bearer ${token}` } : {}),
        ...headers,
      },
      body: body ? JSON.stringify(body) : undefined,
    });
  } catch {
    throw new ApiError(0, "Plateforme injoignable.");
  }
  const text = await response.text();
  let data = null;
  try {
    data = text ? JSON.parse(text) : null;
  } catch {
    data = null;
  }
  if (!response.ok) {
    throw new ApiError(response.status, errorMessage(response.status, data), data);
  }
  return { status: response.status, data };
}

export const api = {
  // L'authentification réutilise auth-service (rôles operator/admin, MFA obligatoire).
  login: (username, password, otp) =>
    request("/auth/login", { method: "POST", body: { username, password, ...(otp ? { otp } : {}) } }),

  // --- Supervision (service admin-api, derrière la passerelle). ---
  overview: (token) => request("/admin/overview", { token }),
  incidents: (token) => request("/admin/incidents", { token }),
  services: (token) => request("/admin/services", { token }),
  remediations: (token) => request("/admin/remediations", { token }),

  // --- Actions de supervision (admin-api -> moteur de remédiation). ---
  blocklist: (token) => request("/admin/blocklist", { token }),
  actions: {
    remediate: (token) => request("/admin/actions/remediate", { token, method: "POST" }),
    blockIp: (token, ip) => request("/admin/actions/block-ip", { token, method: "POST", body: { ip } }),
    unblockIp: (token, ip) => request("/admin/actions/unblock-ip", { token, method: "POST", body: { ip } }),
    freezeLedger: (token, freeze, reason) =>
      request("/admin/actions/freeze-ledger", { token, method: "POST", body: { freeze, reason } }),
  },

  // --- Habilitations (auth-service, réservé aux administrateurs). ---
  users: {
    list: (token) => request("/auth/users", { token }),
    create: (token, body) => request("/auth/users", { token, method: "POST", body }),
    update: (token, username, body) =>
      request(`/auth/users/${encodeURIComponent(username)}`, { token, method: "PATCH", body }),
    remove: (token, username) =>
      request(`/auth/users/${encodeURIComponent(username)}`, { token, method: "DELETE" }),
  },
};

// --- Face-agent : reconnaissance faciale + pilotage LED, sur le PC Hôte (hors passerelle). ---
// 127.0.0.1 explicite (et pas « localhost ») : évite l'ambiguïté IPv4/IPv6 qui empêche
// le flux vidéo de charger quand le site est servi en IPv6.
const FACE_AGENT = import.meta.env.VITE_FACE_AGENT || "http://127.0.0.1:8070";
export const faceStreamUrl = FACE_AGENT + "/stream";
export const faceSnapshotUrl = FACE_AGENT + "/snapshot";

async function faceCall(path, { method = "POST", body } = {}) {
  let resp;
  try {
    resp = await fetch(FACE_AGENT + path, {
      method,
      headers: body ? { "Content-Type": "application/json" } : {},
      body: body ? JSON.stringify(body) : undefined,
    });
  } catch {
    throw new ApiError(0, "Service de reconnaissance injoignable.");
  }
  if (!resp.ok) throw new ApiError(resp.status, "Erreur du service de reconnaissance.");
  return resp.json();
}

export const face = {
  recognize: (username) => faceCall("/recognize", { body: { username } }),
  led: (state) => faceCall("/led", { body: { state } }).catch(() => {}), // LED best-effort
  list: () => faceCall("/faces", { method: "GET" }),
  enroll: (name, shots = 7) => faceCall("/enroll", { body: { name, shots } }),
  remove: (name) => faceCall(`/faces/${encodeURIComponent(name)}`, { method: "DELETE" }),
};

export function formatTime(iso) {
  try {
    return new Intl.DateTimeFormat("fr-FR", { hour: "2-digit", minute: "2-digit", second: "2-digit" }).format(new Date(iso));
  } catch {
    return iso;
  }
}
