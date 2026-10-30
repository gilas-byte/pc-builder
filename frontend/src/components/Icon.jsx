// Ícones SVG das categorias (usados quando a peça não tem foto) e da navegação.
const PATHS = {
  cpu: <><rect x="6" y="6" width="12" height="12" rx="1.5" /><rect x="9.5" y="9.5" width="5" height="5" /><path d="M9 2v4M15 2v4M9 18v4M15 18v4M2 9h4M2 15h4M18 9h4M18 15h4" /></>,
  motherboard: <><rect x="3" y="3" width="18" height="18" rx="2" /><rect x="6" y="6" width="5" height="5" /><path d="M14 6h4M14 9h4M6 14h12M6 17h8" /></>,
  ram: <><rect x="2" y="7" width="20" height="9" rx="1" /><path d="M6 10v3M10 10v3M14 10v3M18 10v3M5 16v3M19 16v3" /></>,
  gpu: <><rect x="2" y="6" width="20" height="11" rx="1.5" /><circle cx="9" cy="11.5" r="3" /><circle cx="16" cy="11.5" r="3" /><path d="M4 17v2" /></>,
  storage: <><rect x="4" y="3" width="16" height="18" rx="2" /><circle cx="12" cy="11" r="4" /><circle cx="12" cy="11" r="1" /><path d="M8 18h8" /></>,
  psu: <><rect x="3" y="5" width="18" height="14" rx="2" /><circle cx="10" cy="12" r="4" /><path d="M17 9l-2 3h2l-2 3" /></>,
  case: <><rect x="6" y="2" width="12" height="20" rx="2" /><circle cx="12" cy="7" r="2" /><path d="M9 13h6M9 16h6" /></>,
  cooler: <><circle cx="12" cy="12" r="9" /><circle cx="12" cy="12" r="2" /><path d="M12 10c0-4 3-6 5-5M14 12c4 0 6 3 5 5M12 14c0 4-3 6-5 5M10 12c-4 0-6-3-5-5" /></>,
  deals: <><path d="M3 12l9-9h8v8l-9 9z" /><circle cx="16" cy="8" r="1.5" /></>,
  parts: <><rect x="3" y="3" width="7" height="7" rx="1" /><rect x="14" y="3" width="7" height="7" rx="1" /><rect x="3" y="14" width="7" height="7" rx="1" /><rect x="14" y="14" width="7" height="7" rx="1" /></>,
  star: <path d="M12 3l2.8 5.7 6.2.9-4.5 4.4 1 6.2L12 17.3 6.5 20.2l1-6.2L3 9.6l6.2-.9z" />,
  builds: <><path d="M14.7 6.3a4 4 0 0 0-5.4 5.4L3 18l3 3 6.3-6.3a4 4 0 0 0 5.4-5.4l-2.5 2.5-2.4-.6-.6-2.4z" /></>,
  ext: <><path d="M14 4h6v6M20 4l-9 9M18 14v5a1 1 0 0 1-1 1H5a1 1 0 0 1-1-1V7a1 1 0 0 1 1-1h5" /></>,
  back: <path d="M15 5l-7 7 7 7" />,
  channels: <><path d="M21 4L3 11l6 2.5L11 20l3-5 5 4z" /><path d="M9 13.5L21 4" /></>,
  gear: <><circle cx="12" cy="12" r="3" /><path d="M19.4 15a1.7 1.7 0 0 0 .3 1.8l.1.1a2 2 0 1 1-2.8 2.8l-.1-.1a1.7 1.7 0 0 0-1.8-.3 1.7 1.7 0 0 0-1 1.5V21a2 2 0 1 1-4 0v-.1a1.7 1.7 0 0 0-1.1-1.5 1.7 1.7 0 0 0-1.8.3l-.1.1a2 2 0 1 1-2.8-2.8l.1-.1a1.7 1.7 0 0 0 .3-1.8 1.7 1.7 0 0 0-1.5-1H3a2 2 0 1 1 0-4h.1a1.7 1.7 0 0 0 1.5-1.1 1.7 1.7 0 0 0-.3-1.8l-.1-.1a2 2 0 1 1 2.8-2.8l.1.1a1.7 1.7 0 0 0 1.8.3H9a1.7 1.7 0 0 0 1-1.5V3a2 2 0 1 1 4 0v.1a1.7 1.7 0 0 0 1 1.5 1.7 1.7 0 0 0 1.8-.3l.1-.1a2 2 0 1 1 2.8 2.8l-.1.1a1.7 1.7 0 0 0-.3 1.8V9a1.7 1.7 0 0 0 1.5 1H21a2 2 0 1 1 0 4h-.1a1.7 1.7 0 0 0-1.5 1z" /></>,
  wand: <><path d="M4 20L16 8M14 4v2M19 9h2M18 5l1.5-1.5M10 4l.5 1.5" /></>,
}

export default function Icon({ name, size = 24, filled = false, className = '' }) {
  return (
    <svg
      className={`icon ${className}`}
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill={filled ? 'currentColor' : 'none'}
      stroke="currentColor"
      strokeWidth="1.6"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
    >
      {PATHS[name] || PATHS.parts}
    </svg>
  )
}
