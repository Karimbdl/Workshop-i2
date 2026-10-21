import tailwindcss from "@tailwindcss/vite";
import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

// En production, la console est servie par la passerelle sous /console/ : les
// ressources (JS/CSS/polices) doivent donc être préfixées. En développement on
// reste à la racine du serveur Vite (port 5174).
export default defineConfig(({ command }) => ({
  base: command === "build" ? "/console/" : "/",
  plugins: [react(), tailwindcss()],
  server: {
    // Port dédié à la console admin, distinct de l'espace client.
    port: 5174,
    // En développement, l'API passe par la passerelle (WAF) comme en production.
    proxy: { "/api": "http://localhost:8080" },
  },
}));
