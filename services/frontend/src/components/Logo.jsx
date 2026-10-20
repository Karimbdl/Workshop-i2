import { useId } from "react";

// Logo Devolut : un « D » avec une flèche montante, sur fond dégradé de la marque.
export default function Logo({ className = "h-10 w-10" }) {
  const gradient = useId();
  return (
    <svg viewBox="0 0 48 48" className={className} role="img" aria-label="Devolut">
      <defs>
        <linearGradient id={gradient} x1="0" y1="0" x2="1" y2="1">
          <stop offset="0" stopColor="#3b6ef5" />
          <stop offset="1" stopColor="#16245e" />
        </linearGradient>
      </defs>
      <rect width="48" height="48" rx="12" fill={`url(#${gradient})`} />
      <path d="M14 12h10a12 12 0 0 1 0 24H14z" fill="none" stroke="#fff" strokeWidth="4" strokeLinejoin="round" />
      <path d="M19 28l5-6 5 6" fill="none" stroke="#7dd3fc" strokeWidth="3" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}
