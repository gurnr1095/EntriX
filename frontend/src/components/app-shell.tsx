import { useEffect, useState, type ReactNode } from "react";
import { Link, useLocation } from "@tanstack/react-router";
import { SignedIn, SignedOut, SignInButton, UserButton } from "@clerk/clerk-react";
import { UserRound, ArrowUpRight, CalendarDays, Moon, Sun, Ticket, Users, Shield, ArrowRight } from "lucide-react";
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
  return <div className="flex min-h-dvh flex-col overflow-x-clip">
    <header className="sticky top-0 z-30 border-b border-border bg-background/85 backdrop-blur supports-[backdrop-filter]:bg-background/70"><div className="mx-auto flex h-16 max-w-6xl items-center justify-between gap-3 px-4 md:h-18 md:px-8">
      <Link to="/" aria-label="EntriX home" className="flex min-w-0 items-center gap-2 rounded-md focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-background"><span className="flex size-9 shrink-0 -skew-x-6 items-center justify-center rounded-lg bg-primary text-primary-foreground shadow-lift"><ArrowUpRight className="size-5 skew-x-6" strokeWidth={3} /></span><span className="font-display text-2xl font-extrabold italic tracking-tight">Entri<span className="text-primary">X</span></span></Link>
      <nav aria-label="Desktop navigation" className="hidden h-full items-center gap-1 md:flex">{navItems.map(item => { const Icon = icons[item.icon]; const active = activeFor(item.to); return <Link key={item.to} to={item.to} aria-current={active ? "page" : undefined} className={`relative flex h-10 items-center gap-2 rounded-full px-4 text-sm font-semibold transition-colors duration-200 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring ${active ? "bg-primary-soft text-primary" : "text-muted-foreground hover:bg-muted hover:text-foreground"}`}><Icon className="size-4" />{item.label}</Link>; })}</nav>
      <div className="flex shrink-0 items-center gap-1.5 md:gap-3"><Button variant="ghost" size="icon" className="size-11 rounded-full" onClick={toggleTheme} aria-label={dark ? "Switch to light mode" : "Switch to dark mode"} title={dark ? "Switch to light mode" : "Switch to dark mode"}>{dark ? <Sun /> : <Moon />}</Button><span className="hidden h-5 border-l border-border sm:block" /><SignedOut><SignInButton mode="modal"><Button className="min-h-11 gap-2 rounded-full px-5 font-semibold">Sign in<ArrowRight /></Button></SignInButton></SignedOut><SignedIn><UserButton><UserButton.MenuItems><UserButton.Link label="My profile" labelIcon={<UserRound className="size-4" />} href="/me" /></UserButton.MenuItems></UserButton></SignedIn></div>
    </div></header>
    <main className="mx-auto w-full max-w-6xl flex-1 px-4 pb-12 pt-6 md:px-8 md:pt-10">{children}</main>
    <footer className="safe-bottom-space border-t border-border"><div className="mx-auto flex w-full max-w-6xl flex-col gap-2 px-4 py-6 text-xs text-muted-foreground sm:flex-row sm:items-center sm:justify-between md:px-8"><span className="font-display text-sm font-extrabold italic text-foreground">Entri<span className="text-primary">X</span></span><span>Made for the game. Built for every starting line.</span></div></footer>
    <nav aria-label="Mobile navigation" style={{ gridTemplateColumns: `repeat(${navItems.length}, minmax(0, 1fr))` }} className="mobile-nav fixed inset-x-0 bottom-0 z-30 grid border-t border-border bg-background/95 backdrop-blur md:hidden">{navItems.map(item => { const Icon = icons[item.icon]; const active = activeFor(item.to); return <Link key={item.to} to={item.to} aria-current={active ? "page" : undefined} className={`group flex min-h-16 min-w-0 flex-col items-center justify-center gap-1 px-1 text-[11px] font-semibold transition-colors duration-200 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-ring ${active ? "text-primary" : "text-muted-foreground"}`}><span className={`flex h-8 w-14 items-center justify-center rounded-full transition-colors duration-200 ${active ? "bg-primary-soft" : "group-hover:bg-muted"}`}><Icon className="size-5" /></span><span className="w-full truncate text-center">{item.label}</span></Link>; })}</nav>
  </div>;
}
