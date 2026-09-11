/**
 * KaryaSetu AI — Official Brand Logo Mark.
 */
import Image from "next/image";

export function LogoMark({ size = 32 }: { size?: number }) {
  return (
    <div
      style={{ width: size, height: size }}
      className="relative shrink-0 flex items-center justify-center overflow-hidden rounded-md"
    >
      <Image
        src="/karyasetu-logo.png"
        alt="KaryaSetu AI"
        width={size}
        height={size}
        className="h-full w-full object-contain"
        priority
        unoptimized
      />
    </div>
  );
}
