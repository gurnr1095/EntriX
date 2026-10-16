import { useEffect, useState, type ReactNode } from "react";
import { Link, useLocation } from "@tanstack/react-router";
import { SignedIn, SignedOut, SignInButton, UserButton } from "@clerk/clerk-react";
import { ArrowUpRight, CalendarDays, Moon, Sun, Ticket, Users, Shield, ArrowRight } from "lucide-react";
import { Button } from "@/components/ui/button";
import { navigation } from "@/lib/navigation";
import { canScan, isOrganizer, useMe } from "@/hooks/use-me";
const icons = { events: CalendarDays, registrations: Ticket, teams: Users, staff: Shield };
export function AppShell({ children }: { children: ReactNode }) {
  const [dark, setDark] = useState(false);
  const pathname = useLocation({ select: (location) => location.pathname });
  useEffect(() => {
    const saved = localStorage.getItem("entrix-theme");
    const enabled = saved ? saved === "dark" : window.matchMedia("(prefers-color-scheme: dark)").matches;
    setDark(enabled);
    document.documentElement.classList.toggle("dark", enabled);
  }, []);
  const toggleTheme = () => {
    const next = !dark;
    setDark(next);
    document.documentElement.classList.toggle("dark", next);
    localStorage.setItem("entrix-theme", next ? "dark" : "light");
  };
  const { data: me } = useMe();
  const staff = canScan(me?.role);
  // Staff sees organizers' dashboard; volunteers go straight to the scanner. The server decides access.
  const navItems = navigation
    .map((item) => (item.icon === "staff" && staff ? { ...item, visible: true, to: isOrganizer(me?.role) ? "/organizer" : "/scan" } : item))
    .filter((item) => item.visible);
  const activeFor = (to: string) => to === "/" ? pathname === "/" || pathname.startsWith("/events/") : pathname.startsWith(to);
  return <div className="flex min-h-dvh flex-col">
    <header className="border-b border-border bg-background"><div className="mx-auto flex h-20 max-w-6xl items-center justify-between gap-4 px-5 md:px-8">
      <Link to="/" aria-label="EntriX home" className="flex items-center gap-2.5"><span className="flex size-9 items-center justify-center rounded-md bg-primary text-primary-foreground"><ArrowUpRight className="size-6" strokeWidth={2.8} /></span><span className="font-display text-2xl font-bold">Entri<span className="text-primary">X</span></span></Link>
      <nav aria-label="Desktop navigation" className="hidden h-full items-center gap-8 md:flex">{navItems.map(item => { const Icon = icons[item.icon]; const active = activeFor(item.to); return <Link key={item.to} to={item.to} aria-current={active ? "page" : undefined} className={`relative flex h-full items-center gap-2 text-sm font-medium transition-colors ${active ? "text-primary after:absolute after:inset-x-0 after:bottom-0 after:h-0.5 after:bg-primary" : "text-muted-foreground hover:text-foreground"}`}><Icon className="size-4" />{item.label}</Link>; })}</nav>
      <div className="flex items-center gap-2 md:gap-4"><Button variant="ghost" size="icon" onClick={toggleTheme} aria-label={dark ? "Switch to light mode" : "Switch to dark mode"} title={dark ? "Switch to light mode" : "Switch to dark mode"}>{dark ? <Sun /> : <Moon />}</Button><span className="hidden h-5 border-l border-border sm:block" /><SignedOut><SignInButton mode="modal"><Button className="gap-2 px-4">Sign in<ArrowRight /></Button></SignInButton></SignedOut><SignedIn><UserButton /></SignedIn></div>
    </div></header>
    <main className="mx-auto w-full max-w-6xl flex-1 px-5 pb-12 pt-9 md:px-8 md:pt-12">{children}</main>
    <footer className="mx-auto mb-24 flex w-full max-w-6xl items-center justify-between border-t border-border px-5 py-6 text-xs text-muted-foreground md:mb-0 md:px-8"><span className="font-display font-semibold text-foreground">EntriX</span><span>Made for the game.</span></footer>
    <nav aria-label="Mobile navigation" style={{ gridTemplateColumns: `repeat(${navItems.length}, minmax(0, 1fr))` }} className="mobile-nav fixed inset-x-0 bottom-0 z-20 grid border-t border-border bg-background md:hidden">{navItems.map(item => { const Icon = icons[item.icon]; const active = activeFor(item.to); return <Link key={item.to} to={item.to} aria-current={active ? "page" : undefined} className={`flex min-h-18 flex-col items-center justify-center gap-1.5 px-1 text-[11px] font-medium ${active ? "text-primary" : "text-muted-foreground"}`}><Icon className="size-5" />{item.label}</Link>; })}</nav>
  </div>;
}
