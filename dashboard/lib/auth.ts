// Lightweight demo auth (client-side only). Replace with Lovable Cloud for production.
const KEY = "fm_user";
export type User = { email: string; name: string; role: "Operator" | "Manager" | "CXO" };

export function getUser(): User | null {
  if (typeof window === "undefined") return null;
  try { return JSON.parse(localStorage.getItem(KEY) || "null"); } catch { return null; }
}
export function signIn(email: string, role: User["role"] = "Manager"): User {
  const name = email.split("@")[0].replace(/[._-]/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
  const u: User = { email, name, role };
  localStorage.setItem(KEY, JSON.stringify(u));
  return u;
}
export function signOut() { localStorage.removeItem(KEY); }
