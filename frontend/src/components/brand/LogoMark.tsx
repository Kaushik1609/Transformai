/**
 * TransformIQ — Brand logo mark.
 */
export function LogoMark({ size = 32 }: { size?: number }) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 32 32"
      fill="none"
      aria-hidden="true"
      xmlns="http://www.w3.org/2000/svg"
      className="shrink-0"
    >
      <defs>
        <linearGradient id="tiq-mark" x1="4" y1="4" x2="28" y2="28" gradientUnits="userSpaceOnUse">
          <stop style={{ stopColor: "var(--logo-gradient-from)" }} />
          <stop offset="1" style={{ stopColor: "var(--logo-gradient-to)" }} />
        </linearGradient>
      </defs>
      <rect width="32" height="32" rx="8" fill="url(#tiq-mark)" />
      <path
        d="M9 11h14M9 16h10M9 21h6"
        stroke="white"
        strokeWidth="2"
        strokeLinecap="round"
      />
      <circle cx="21" cy="21" r="2.4" fill="white" />
    </svg>
  );
}
