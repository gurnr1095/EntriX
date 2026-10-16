import type { CSSProperties, ReactNode } from "react";

/** The page title as a poster line: very large, no label above it, no rule under it. */
export function PageHeader({ title, children }: { title: string; children?: ReactNode }) {
  return (
    <header className="mb-6 md:mb-8">
      <h1 className="rise text-[clamp(1.5rem,5.2vw,3.5rem)] leading-[1]">{title}</h1>
      {children && (
        <p className="rise mt-3 max-w-xl text-lg" style={{ "--i": 1 } as CSSProperties}>{children}</p>
      )}
    </header>
  );
}
