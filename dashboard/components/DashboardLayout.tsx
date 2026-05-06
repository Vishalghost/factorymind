import { useLocation, Outlet } from "@tanstack/react-router";
import { Logo } from "./Logo";
import { Button } from "@/components/ui/button";
import { getUser, signOut } from "@/lib/auth";
import { useEffect, useState } from "react";
import { Activity, Boxes, Cpu, Eye, Gauge, Leaf, LogOut, MessageSquare, Wrench } from "lucide-react";

// Each nav item ships both the typed `to` (for TanStack Router type-safety)
// and the raw href (used by the imperative click handler below).
type NavItem = { to: string; label: string; icon: typeof Gauge };
const NAV: NavItem[] = [
  { to: "/dashboard", label: "Overview", icon: Gauge },
  { to: "/dashboard/twin", label: "Digital Twin", icon: Boxes },
  { to: "/dashboard/quality", label: "Quality Vision", icon: Eye },
  { to: "/dashboard/maintenance", label: "Predictive Maint.", icon: Wrench },
  { to: "/dashboard/edge", label: "Edge AI", icon: Cpu },
  { to: "/dashboard/sustainability", label: "Sustainability", icon: Leaf },
  { to: "/dashboard/assistant", label: "GenAI Assistant", icon: MessageSquare },
];

export function DashboardLayout() {
  const loc = useLocation();
  const [user, setUser] = useState(getUser());

  // If the user isn't signed in, send them to /login. Using a plain redirect
  // avoids depending on the router's `useNavigate` identity, which appears to
  // cause spurious re-render churn on this build.
  useEffect(() => {
    if (!user) window.location.assign("/login");
  }, [user]);

  if (!user) return null;

  return (
    <div className="flex min-h-screen bg-secondary/40">
      <aside className="sticky top-0 flex h-screen w-64 flex-col border-r border-border bg-sidebar">
        <div className="border-b border-sidebar-border px-5 py-4"><Logo /></div>
        <nav className="flex-1 space-y-0.5 p-3">
          {NAV.map(({ to, label, icon: Icon }) => {
            const active = loc.pathname === to;
            // Use an anchor with onClick so:
            //  1. Right-click / middle-click opens in a new tab (real href works)
            //  2. The click handler explicitly calls TanStack Router's navigate
            //     bypassing any Link-component edge case
            //  3. We log clicks to the browser console so navigation is debuggable
            return (
              <a
                key={to}
                href={to}
                onClick={(e) => {
                  // Plain anchor navigation — let the browser do a real page
                  // load. We only intercept to avoid history weirdness on
                  // modifier-key clicks (open in new tab still works).
                  if (e.metaKey || e.ctrlKey || e.shiftKey || e.button !== 0) return;
                  e.preventDefault();
                  // eslint-disable-next-line no-console
                  console.log("[nav]", to);
                  window.location.assign(to);
                }}
                className={`flex items-center gap-3 rounded-md px-3 py-2 text-sm transition-colors ${
                  active ? "bg-primary text-primary-foreground shadow-sm" : "text-sidebar-foreground hover:bg-sidebar-accent"
                }`}
              >
                <Icon className="h-4 w-4" />
                {label}
              </a>
            );
          })}
        </nav>
        <div className="border-t border-sidebar-border p-3">
          <div className="mb-2 rounded-md bg-sidebar-accent p-3">
            <div className="text-xs text-muted-foreground">Signed in as</div>
            <div className="truncate text-sm font-semibold">{user.name}</div>
            <div className="text-xs text-primary">{user.role}</div>
          </div>
          <Button variant="outline" size="sm" className="w-full" onClick={() => { signOut(); setUser(null); }}>
            <LogOut className="mr-2 h-3.5 w-3.5" /> Sign out
          </Button>
        </div>
      </aside>

      <main className="flex-1">
        <header className="sticky top-0 z-10 flex items-center justify-between border-b border-border bg-background/80 px-8 py-4 backdrop-blur">
          <div>
            <h1 className="font-display text-xl font-bold tracking-tight">
              {NAV.find((n) => n.to === loc.pathname)?.label ?? "Dashboard"}
            </h1>
            <p className="text-xs text-muted-foreground">FactoryMind · Smart Manufacturing Intelligence</p>
          </div>
          <div className="flex items-center gap-3">
            <div className="flex items-center gap-2 rounded-full border border-border bg-card px-3 py-1.5 text-xs">
              <span className="relative inline-flex h-2 w-2 items-center justify-center text-success pulse-dot">
                <span className="h-2 w-2 rounded-full bg-success" />
              </span>
              <span className="font-mono">Live · 247 sensors</span>
            </div>
            <div className="flex items-center gap-2 rounded-full border border-border bg-card px-3 py-1.5 text-xs">
              <Activity className="h-3.5 w-3.5 text-primary" />
              <span className="font-mono">Edge latency 7ms</span>
            </div>
          </div>
        </header>
        <div className="p-8"><Outlet /></div>
      </main>
    </div>
  );
}
