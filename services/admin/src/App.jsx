import { useState } from "react";
import { loadSession, saveSession } from "./api.js";
import Login from "./components/Login.jsx";
import Console from "./components/Console.jsx";

export default function App() {
  const [session, setSession] = useState(loadSession);

  function logout() {
    saveSession(null);
    setSession(null);
  }

  if (!session) return <Login onAuthenticated={setSession} />;
  return <Console session={session} onLogout={logout} />;
}
