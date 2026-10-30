/** The LocalDub mark: a waveform in a rounded tile (same drawing as the program icon). */
export function Logo({ size = 36 }: { size?: number }) {
  const bars = [0.18, 0.34, 0.56, 0.74, 0.5, 0.64, 0.3, 0.16];
  const left = 0.17;
  const pitch = 0.66 / bars.length;
  return (
    <svg width={size} height={size} viewBox="0 0 100 100" role="img" aria-label="LocalDub Studio" className="shrink-0">
      <defs>
        <linearGradient id="ld-tile" x1="0" y1="0" x2="1" y2="1">
          <stop offset="0" stopColor="var(--accent)" />
          <stop offset="1" stopColor="color-mix(in srgb, var(--accent) 60%, #f2b233)" />
        </linearGradient>
      </defs>
      <rect x="2" y="2" width="96" height="96" rx="22" fill="url(#ld-tile)" />
      {bars.map((h, i) => (
        <rect key={i} x={(left + pitch * (i + 0.5) - pitch * 0.29) * 100} y={(0.5 - h / 2) * 100} width={pitch * 0.58 * 100} height={h * 100} rx={pitch * 0.29 * 100} fill="#fff" />
      ))}
    </svg>
  );
}
