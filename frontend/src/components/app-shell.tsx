import { useEffect, useState, type ReactNode } from "react";
import { Link, useLocation } from "@tanstack/react-router";
import { SignedIn, SignedOut, SignInButton, UserButton } from "@clerk/clerk-react";
import { ArrowRight, ArrowUpRight, CalendarDays, Moon, Shield, Sun, Ticket, UserRound, Users } from "lucide-react";
import { Button } from "@/components/ui/button";
import { canScan, isOrganizer, useMe } from "@/hooks/use-me";
import { navigation } from "@/lib/navigation";

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
  // Staff sees the organizer area; volunteers go straight to the scanner. The server decides access.
  const navItems = navigation
    .map((item) => (item.icon === "staff" && staff ? { ...item, visible: true, to: isOrganizer(me?.role) ? "/organizer" : "/scan" } : item))
    .filter((item) => item.visible);
  const activeFor = (to: string) =>
    to === "/" ? pathname === "/" || pathname.startsWith("/events/") : pathname.startsWith(to) || (to === "/organizer" && pathname.startsWith("/scan"));

  return (
    <div className="flex min-h-dvh flex-col overflow-x-clip">
      <header className="bg-background">
        <div className="mx-auto flex h-16 max-w-6xl items-center justify-between gap-3 px-4 md:h-20 md:px-8">
          <Link to="/" aria-label="EntriX home" className="flex min-w-0 items-center gap-2.5 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-background">
            <span className="flex size-9 items-center justify-center bg-primary text-primary-foreground"><ArrowUpRight className="size-6" strokeWidth={3} /></span>
            <span className="font-display text-xl">Entri<span className="text-primary-text">X</span></span>
          </Link>

          <nav aria-label="Desktop navigation" className="hidden items-center gap-1 md:flex">
            {navItems.map((item) => {
              const Icon = icons[item.icon];
              const active = activeFor(item.to);
              return (
                <Link key={item.to} to={item.to} aria-current={active ? "page" : undefined}
                  className={`inline-flex min-h-11 items-center gap-2 px-4 text-sm font-medium ${active ? "bg-foreground text-background" : "text-foreground hover:bg-card"}`}>
                  <Icon className="size-4" />{item.label}
                </Link>
              );
            })}
          </nav>

          <div className="flex shrink-0 items-center gap-1.5 md:gap-3">
            <Button variant="ghost" size="icon" className="size-11" onClick={toggleTheme}
              aria-label={dark ? "Switch to light mode" : "Switch to dark mode"} title={dark ? "Switch to light mode" : "Switch to dark mode"}>
              {dark ? <Sun /> : <Moon />}
            </Button>
            <SignedOut>
              <SignInButton mode="modal"><Button className="min-h-11 gap-2 px-5 font-semibold">Sign in<ArrowRight /></Button></SignInButton>
            </SignedOut>
            <SignedIn>
              <UserButton>
                <UserButton.MenuItems>
                  <UserButton.Link label="My profile" labelIcon={<UserRound className="size-4" />} href="/me" />
                </UserButton.MenuItems>
              </UserButton>
            </SignedIn>
          </div>
        </div>
      </header>

      <main className="mx-auto w-full max-w-6xl flex-1 px-4 pb-16 pt-6 md:px-8 md:pt-10">{children}</main>

      <footer className="safe-bottom-space field-dark">
        <div className="mx-auto max-w-6xl px-4 pb-8 pt-12 md:px-8 md:pt-16">
          <p aria-hidden className="font-display text-[clamp(2.75rem,15vw,13rem)] leading-[0.85] text-field-accent">EntriX</p>
          <p className="mt-8 max-w-md text-lg">Pick your sport, grab a seat, show your pass at the gate.</p>
        </div>
      </footer>

      <nav aria-label="Mobile navigation" style={{ gridTemplateColumns: `repeat(${navItems.length}, minmax(0, 1fr))` }}
        className="mobile-nav fixed inset-x-0 bottom-0 z-30 grid bg-foreground text-background md:hidden">
        {navItems.map((item) => {
          const Icon = icons[item.icon];
          const active = activeFor(item.to);
          return (
            <Link key={item.to} to={item.to} aria-current={active ? "page" : undefined}
              className={`flex min-h-16 flex-col items-center justify-center gap-1 px-1 text-[13px] font-medium ${active ? "bg-primary text-primary-foreground" : ""}`}>
              <Icon className="size-5" />{item.label}
            </Link>
          );
        })}
      </nav>
    </div>
  );
}
