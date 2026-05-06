import { createFileRoute, useNavigate, Link } from "@tanstack/react-router";
import { useState } from "react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Logo } from "@/components/Logo";
import { signIn, type User } from "@/lib/auth";
import { ArrowRight, ShieldCheck } from "lucide-react";

export const Route = createFileRoute("/login")({
  head: () => ({ meta: [{ title: "Sign in — FactoryMind" }, { name: "description", content: "Access your FactoryMind dashboards." }] }),
  component: LoginPage,
});

function LoginPage() {
  const nav = useNavigate();
  const [email, setEmail] = useState("vishal@cognizant.com");
  const [password, setPassword] = useState("demo");
  const [role, setRole] = useState<User["role"]>("Manager");
  const [loading, setLoading] = useState(false);

  const submit = (e: React.FormEvent) => {
    e.preventDefault();
    setLoading(true);
    setTimeout(() => {
      signIn(email, role);
      nav({ to: "/dashboard" });
    }, 500);
  };

  return (
    <div className="grid min-h-screen md:grid-cols-2">
      {/* Left: form */}
      <div className="flex items-center justify-center px-6 py-12">
        <div className="w-full max-w-sm">
          <Link to="/"><Logo /></Link>
          <h1 className="mt-10 font-display text-3xl font-bold tracking-tight">Welcome back</h1>
          <p className="mt-1 text-sm text-muted-foreground">Sign in to your factory control plane.</p>

          <form onSubmit={submit} className="mt-8 space-y-4">
            <div>
              <Label htmlFor="email">Work email</Label>
              <Input id="email" type="email" required value={email} onChange={(e) => setEmail(e.target.value)} className="mt-1.5" />
            </div>
            <div>
              <Label htmlFor="password">Password</Label>
              <Input id="password" type="password" required value={password} onChange={(e) => setPassword(e.target.value)} className="mt-1.5" />
            </div>
            <div>
              <Label>Role</Label>
              <div className="mt-1.5 grid grid-cols-3 gap-2">
                {(["Operator", "Manager", "CXO"] as const).map((r) => (
                  <button
                    type="button"
                    key={r}
                    onClick={() => setRole(r)}
                    className={`rounded-md border px-3 py-2 text-xs font-medium transition ${
                      role === r ? "border-primary bg-primary text-primary-foreground" : "border-border hover:border-primary/40"
                    }`}
                  >{r}</button>
                ))}
              </div>
            </div>
            <Button type="submit" className="w-full" disabled={loading}>
              {loading ? "Signing in…" : <>Sign in <ArrowRight className="ml-2 h-4 w-4" /></>}
            </Button>
            <p className="text-center text-xs text-muted-foreground">Demo · use any email & password</p>
          </form>
        </div>
      </div>

      {/* Right: visual */}
      <div className="relative hidden overflow-hidden gradient-mesh md:block">
        <div className="absolute inset-0 grid-bg opacity-50" />
        <div className="relative flex h-full flex-col justify-between p-12">
          <div className="inline-flex items-center gap-2 rounded-full border border-border bg-card/70 px-3 py-1 text-xs font-medium backdrop-blur w-fit">
            <ShieldCheck className="h-3.5 w-3.5 text-primary" /> SOC2 · Bedrock Guardrails
          </div>
          <div>
            <p className="font-display text-3xl font-bold leading-tight tracking-tight">
              "FactoryMind cut our unplanned downtime by <span className="text-primary">42%</span> in the first quarter."
            </p>
            <p className="mt-4 text-sm text-muted-foreground">— Plant Director, Tier-1 Automotive Supplier</p>
          </div>
        </div>
      </div>
    </div>
  );
}
