import type { CSSProperties, ReactNode } from "react";

/** The page title as a poster line: very large, no label above it, no rule under it. */
export function PageHeader({ title, children }: { title: string; children?: ReactNode }) {
  return (
    <header className="mb-10 md:mb-14">
      <h1 className="rise text-[clamp(1.5rem,6.6vw,5rem)] leading-[0.98]">{title}</h1>
      {children && (
        <p className="rise mt-5 max-w-xl text-lg" style={{ "--i": 1 } as CSSProperties}>{children}</p>
      )}
    </header>
  );
}
