export function CoachAvatar() {
  return (
    <div className="relative w-40 h-40 mx-auto">
      <style>{`
        @keyframes coach-breathe {
          0%, 100% { transform: translateY(0); }
          50% { transform: translateY(-4px); }
        }
        @keyframes racket-tap {
          0%, 100% { transform: rotate(0deg); }
          50% { transform: rotate(-8deg); }
        }
        .coach-body { animation: coach-breathe 3.2s ease-in-out infinite; transform-origin: bottom center; }
        .coach-racket { animation: racket-tap 2.4s ease-in-out infinite; transform-origin: 70% 85%; }
      `}</style>
      <svg viewBox="0 0 160 160" className="coach-body w-full h-full">
        <circle cx="80" cy="80" r="76" fill="var(--color-accent)" opacity="0.12" />
        <circle cx="80" cy="80" r="76" fill="none" stroke="var(--color-border-strong)" strokeWidth="1.5" />
        {/* head */}
        <circle cx="80" cy="46" r="22" fill="#e7b790" />
        {/* body / polo */}
        <path d="M50 130 Q50 78 80 78 Q110 78 110 130 Z" fill="var(--color-accent)" />
        {/* arms */}
        <path d="M50 90 Q34 100 30 122" stroke="#e7b790" strokeWidth="10" strokeLinecap="round" fill="none" />
        <g className="coach-racket">
          <path d="M110 90 Q126 96 132 112" stroke="#e7b790" strokeWidth="10" strokeLinecap="round" fill="none" />
          {/* racket */}
          <line x1="132" y1="112" x2="146" y2="130" stroke="#9db2cd" strokeWidth="4" strokeLinecap="round" />
          <ellipse cx="150" cy="134" rx="10" ry="14" fill="none" stroke="#9db2cd" strokeWidth="4" transform="rotate(25 150 134)" />
        </g>
        {/* legs */}
        <path d="M64 130 L60 154" stroke="#3c5170" strokeWidth="10" strokeLinecap="round" />
        <path d="M96 130 L100 154" stroke="#3c5170" strokeWidth="10" strokeLinecap="round" />
        {/* simple smiling face */}
        <circle cx="72" cy="44" r="2.5" fill="#1f2937" />
        <circle cx="88" cy="44" r="2.5" fill="#1f2937" />
        <path d="M70 54 Q80 60 90 54" stroke="#1f2937" strokeWidth="2.5" fill="none" strokeLinecap="round" />
      </svg>
    </div>
  );
}
