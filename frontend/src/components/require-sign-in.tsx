import { useEffect, useState, type ReactNode } from "react";
import { SignInButton, useAuth } from "@clerk/clerk-react";
import { LogIn, WifiOff } from "lucide-react";
import { Button } from "@/components/ui/button";
import { EmptyState, ListSkeleton } from "@/components/page-state";

/** Signed-out visitors get a clear prompt instead of a failing request. */
export function RequireSignIn({ children, what }: { children: ReactNode; what: string }) {
  const { isLoaded, isSignedIn } = useAuth();
  const [stuck, setStuck] = useState(false);

  // Clerk is loaded from the internet; an ad blocker or a bad connection can stop it. Say so
  // instead of showing a skeleton forever.
  useEffect(() => {
    if (isLoaded) { setStuck(false); return; }
    const t = setTimeout(() => setStuck(true), 12_000);
    return () => clearTimeout(t);
  }, [isLoaded]);

  if (!isLoaded) {
    if (stuck) {
      return (
        <EmptyState icon={<WifiOff className="size-6 text-muted-foreground" />} title="Sign-in is not loading">
          <p className="mb-4">Check your connection, or turn off any ad blocker for this site, then reload.</p>
          <Button className="min-h-11 rounded-none px-6 font-semibold" onClick={() => window.location.reload()}>Reload</Button>
        </EmptyState>
      );
    }
    return <ListSkeleton rows={2} />;
  }
  if (!isSignedIn) {
    return (
      <EmptyState icon={<LogIn className="size-6 text-muted-foreground" />} title="Sign in to continue">
        <p className="mb-4">Sign in to see {what}.</p>
        <SignInButton mode="modal"><Button className="min-h-11 rounded-none px-6 font-semibold">Sign in</Button></SignInButton>
      </EmptyState>
    );
  }
  return <>{children}</>;
}
