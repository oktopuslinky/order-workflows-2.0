"use client";

// Session context: probes /auth/me once on mount, exposes the signed-in user,
// and gates app pages behind /login. The session itself is an HttpOnly cookie —
// nothing auth-related is stored in JS-accessible state beyond the profile.

import { usePathname, useRouter } from "next/navigation";
import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useState,
} from "react";
import { api, type UserPublic } from "@/lib/api";

interface AuthState {
  user: UserPublic | null;
  loading: boolean;
  setUser: (user: UserPublic | null) => void;
  logout: () => Promise<void>;
}

const AuthContext = createContext<AuthState>({
  user: null,
  loading: true,
  setUser: () => {},
  logout: async () => {},
});

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [user, setUser] = useState<UserPublic | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    api
      .me()
      .then(setUser)
      .catch(() => setUser(null))
      .finally(() => setLoading(false));
  }, []);

  const logout = useCallback(async () => {
    try {
      await api.logout();
    } finally {
      setUser(null);
    }
  }, []);

  return (
    <AuthContext.Provider value={{ user, loading, setUser, logout }}>
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth(): AuthState {
  return useContext(AuthContext);
}

/** Public routes render without a session; the guides stay readable pre-login. */
function isPublic(pathname: string): boolean {
  return pathname === "/login" || pathname.startsWith("/guide");
}

export function AuthGuard({ children }: { children: React.ReactNode }) {
  const { user, loading } = useAuth();
  const pathname = usePathname();
  const router = useRouter();
  const open = isPublic(pathname);

  useEffect(() => {
    if (!loading && !user && !open) {
      router.replace(`/login?next=${encodeURIComponent(pathname)}`);
    }
  }, [loading, user, open, pathname, router]);

  if (!open && (loading || !user)) {
    return <p className="p-6 text-sm text-[var(--muted)]">Checking session…</p>;
  }
  return <>{children}</>;
}
