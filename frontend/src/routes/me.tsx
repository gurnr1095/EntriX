import { PageHeader } from "@/components/page-header";
import { useEffect, useState, type FormEvent } from "react";
import { createFileRoute } from "@tanstack/react-router";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { ErrorState, ListSkeleton, Spinner } from "@/components/page-state";
import { RequireSignIn } from "@/components/require-sign-in";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { useMe } from "@/hooks/use-me";
import { api } from "@/lib/api";
import { messageFor } from "@/lib/errors";
import { blankToNull } from "@/lib/registration";
import type { UserPatch } from "@/types";

export const Route = createFileRoute("/me")({
  head: () => ({ meta: [{ title: "My profile | EntriX" }, { name: "description", content: "My profile on EntriX." }, { property: "og:title", content: "My profile | EntriX" }, { property: "og:description", content: "My profile on EntriX." }, { property: "og:type", content: "website" }, { name: "twitter:card", content: "summary_large_image" }] }),
  component: Page,
});

function Page() {
  return (
    <section>
      <PageHeader title="My profile" />
      <RequireSignIn what="your profile">
        <ProfileForm />
      </RequireSignIn>
    </section>
  );
}

function ProfileForm() {
  const me = useMe();
  const qc = useQueryClient();
  const [name, setName] = useState("");
  const [college, setCollege] = useState("");
  const [rollNo, setRollNo] = useState("");
  const [phone, setPhone] = useState("");
  const [nameError, setNameError] = useState<string | null>(null);

  useEffect(() => {
    if (!me.data) return;
    setName(me.data.name);
    setCollege(me.data.college ?? "");
    setRollNo(me.data.roll_no ?? "");
    setPhone(me.data.phone ?? "");
  }, [me.data]);

  const save = useMutation({
    mutationFn: (patch: UserPatch) => api.patchMe(patch),
    onSuccess: (user) => {
      qc.setQueryData(["me"], user);
      toast.success("Profile saved.");
    },
    onError: (e) => toast.error(messageFor(e)),
  });

  function submit(e: FormEvent) {
    e.preventDefault();
    if (!name.trim()) { setNameError("Please enter your name."); return; }
    setNameError(null);
    save.mutate({ name: name.trim(), college: blankToNull(college), roll_no: blankToNull(rollNo), phone: blankToNull(phone) });
  }

  if (me.isPending) return <ListSkeleton rows={2} />;
  if (me.isError) return <ErrorState error={me.error} onRetry={() => void me.refetch()} />;

  return (
    <Card className="max-w-xl rounded-none">
      <CardContent className="p-5 sm:p-6">
        <form onSubmit={submit} className="space-y-5" noValidate>
          <div className="space-y-2">
            <Label htmlFor="email">Email</Label>
            <Input id="email" value={me.data.email} readOnly disabled />
            <p className="text-xs text-muted-foreground">Your email comes from your sign-in and cannot be changed here.</p>
          </div>
          <div className="space-y-2">
            <Label htmlFor="name">Full name</Label>
            <Input id="name" value={name} onChange={(e) => setName(e.target.value)} autoComplete="name" aria-invalid={!!nameError} aria-describedby={nameError ? "name-error" : undefined} />
            {nameError && <p id="name-error" role="alert" className="text-sm text-destructive">{nameError}</p>}
          </div>
          <div className="space-y-2">
            <Label htmlFor="college">College</Label>
            <Input id="college" value={college} onChange={(e) => setCollege(e.target.value)} autoComplete="organization" />
          </div>
          <div className="grid gap-5 sm:grid-cols-2">
            <div className="space-y-2">
              <Label htmlFor="roll">Roll number</Label>
              <Input id="roll" value={rollNo} onChange={(e) => setRollNo(e.target.value)} />
            </div>
            <div className="space-y-2">
              <Label htmlFor="phone">Phone</Label>
              <Input id="phone" type="tel" inputMode="tel" value={phone} onChange={(e) => setPhone(e.target.value)} autoComplete="tel" />
            </div>
          </div>
          <Button type="submit" className="min-h-11 rounded-none px-6 font-semibold" disabled={save.isPending}>
            {save.isPending ? <Spinner label="Saving..." /> : "Save profile"}
          </Button>
        </form>
      </CardContent>
    </Card>
  );
}
