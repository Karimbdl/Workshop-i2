// Client HTTP : toutes les requêtes passent par la passerelle (/api).

const SESSION_KEY = "resilience.session";

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
  if (body && Array.isArray(body.detail)) return "Données invalides : vérifiez le formulaire.";
  if (status === 403) return "Requête bloquée par le pare-feu applicatif.";
  if (status === 429) return "Trop de requêtes : réessayez dans quelques secondes.";
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
  // 422 avec un paiement refusé : c'est une réponse métier, pas une erreur technique.
  if (!response.ok && !(response.status === 422 && data && data.status === "REJECTED")) {
    throw new ApiError(response.status, errorMessage(response.status, data), data);
  }
  return { status: response.status, data };
}

export const api = {
  login: (username, password, otp) =>
    request("/auth/login", { method: "POST", body: { username, password, ...(otp ? { otp } : {}) } }),
  accounts: (token) => request("/accounts/me", { token }),
  beneficiaries: (token) => request("/accounts/beneficiaries", { token }),
  payments: (token) => request("/payments?limit=20", { token }),
  pay: (token, payment, idempotencyKey) =>
    request("/payments", {
      token,
      method: "POST",
      body: payment,
      headers: { "Idempotency-Key": idempotencyKey },
    }),
};

export function formatEuros(value) {
  return new Intl.NumberFormat("fr-FR", { style: "currency", currency: "EUR" }).format(Number(value));
}

export function maskIban(iban) {
  return `${iban.slice(0, 4)} •••• ${iban.slice(-4)}`;
}
