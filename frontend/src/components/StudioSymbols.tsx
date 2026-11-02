import type { SVGProps } from "react"

type SymbolProps = SVGProps<SVGSVGElement>

/** Original geometric Z: interlocking frames with a continuous diagonal cut. */
export function StudioBrandSymbol({ className, ...props }: SymbolProps) {
  return <svg viewBox="0 0 32 32" width={28} height={28} fill="none" aria-hidden="true" focusable="false" className={className} {...props}>
    <path d="M8 5h20l-6 6H2l6-6Z" fill="var(--studio-symbol-accent)" />
    <path d="M20 10h8L12 26H4l16-16Z" fill="var(--studio-symbol-secondary)" />
    <path d="M10 21h20l-6 6H4l6-6Z" fill="var(--studio-symbol-accent)" />
    <path d="M3 19v9h7M24 3h6v6" stroke="var(--studio-symbol-accent)" strokeWidth={1.8} strokeLinecap="round" strokeLinejoin="round" />
  </svg>
}

type NavigationSymbolProps = SymbolProps & { name: "generate" | "director" | "canvas" | "tools" | "assets" }

export function StudioNavigationSymbol({ name, className, ...props }: NavigationSymbolProps) {
  return <svg viewBox="0 0 24 24" width={22} height={22} fill="none" stroke="currentColor" strokeWidth={1.7} strokeLinecap="round" strokeLinejoin="round" aria-hidden="true" focusable="false" className={className} {...props}>
    {name === "generate" && <>
      <path d="M12.5 4H6a2 2 0 0 0-2 2v11a2 2 0 0 0 2 2h11a2 2 0 0 0 2-2v-4.5" />
      <path d="m5 14.7 4.5-4.5h5.6l-5.9 6H5v-1.5Z" fill="var(--studio-symbol-accent)" fillOpacity={0.48} stroke="none" />
      <path d="m18.3 1.8 1.1 2.7 2.7 1.1-2.7 1.1-1.1 2.7-1.1-2.7-2.7-1.1 2.7-1.1 1.1-2.7Z" fill="var(--studio-symbol-accent)" stroke="none" />
      <path d="m4.2 19.8 2.4-2.4" />
    </>}
    {name === "director" && <>
      <path d="m3.5 8.5 14.4-3.8a1.5 1.5 0 0 1 1.8 1.1l.6 2.2-16.2 4.3-.6-2.1a1.5 1.5 0 0 1 1.1-1.8Z" />
      <path d="m7.2 7.5 2.5 2.7m3.2-4.2 2.6 2.8M4.2 12v6.5a1.5 1.5 0 0 0 1.5 1.5h13a1.5 1.5 0 0 0 1.5-1.5V12H4.2Z" />
      <path d="M7.5 16.2H12" stroke="var(--studio-symbol-accent)" />
      <path d="M15 16.2h2" />
    </>}
    {name === "canvas" && <>
      <path d="M8 5V4a1.5 1.5 0 0 1 1.5-1.5h10A1.5 1.5 0 0 1 21 4v10a1.5 1.5 0 0 1-1.5 1.5H18" />
      <rect x={3.5} y={7.5} width={12} height={12} rx={1.8} />
      <path d="M7 16.7h5.5l-3.6 3.6H5.2L7 16.7Z" fill="var(--studio-symbol-accent)" fillOpacity={0.4} stroke="none" />
      <path d="M15.5 15.5h2a2 2 0 0 0 2-2v-2" stroke="var(--studio-symbol-accent)" />
      <circle cx={19.5} cy={10.8} r={1.1} fill="var(--studio-symbol-accent)" stroke="none" />
      <circle cx={10.8} cy={19.5} r={1.1} fill="var(--studio-symbol-accent)" stroke="none" />
    </>}
    {name === "assets" && <>
      <path d="M3.5 8V5.5A1.5 1.5 0 0 1 5 4h4l2 2h7.5A1.5 1.5 0 0 1 20 7.5V9" />
      <path d="M7 8h4l1.5 1.5H20a1 1 0 0 1 1 1.2L19.3 19H3.5V9.5A1.5 1.5 0 0 1 5 8h2Z" />
      <path d="M6 14h12l-1.1 2H4.8L6 14Z" fill="var(--studio-symbol-accent)" fillOpacity={0.32} stroke="none" />
    </>}
    {name === "tools" && <>
      <rect x={3.5} y={3.5} width={7.4} height={7.4} rx={1.7} />
      <rect x={13.1} y={3.5} width={7.4} height={7.4} rx={1.7} />
      <rect x={3.5} y={13.1} width={7.4} height={7.4} rx={1.7} />
      <path d="M13.1 16.8h7.4M16.8 13.1v7.4" stroke="var(--studio-symbol-accent)" />
    </>}
  </svg>
}
