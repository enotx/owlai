// frontend/src/contexts/auth-context.tsx
"use client";

import { createContext, useContext, useEffect, useState, useCallback, type ReactNode, useRef } from "react";
import { supabase } from "@/lib/supabase";
import type { User, Session } from "@supabase/supabase-js";
import { syncPlatformConfig } from "@/lib/api";

interface AuthState {
  user: User | null;
  session: Session | null;
  loading: boolean;
  isCloud: boolean;
  signIn: (email: string, password: string) => Promise<{ error: string | null }>;
  signUp: (email: string, password: string) => Promise<{ error: string | null }>;
  signOut: () => Promise<void>;
}

const AuthContext = createContext<AuthState>({
  user: null,
  session: null,
  loading: true,
  isCloud: false,
  signIn: async () => ({ error: "Not initialized" }),
  signUp: async () => ({ error: "Not initialized" }),
  signOut: async () => {},
});

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<User | null>(null);
  const [session, setSession] = useState<Session | null>(null);
  const [loading, setLoading] = useState(true);

  // 判断是否为 cloud 模式：有 Supabase 配置 且 不是 Tauri 桌面
  const isCloud =
    !!process.env.NEXT_PUBLIC_SUPABASE_URL &&
    typeof window !== "undefined" &&
    !window.__TAURI__;

  useEffect(() => {
    if (!isCloud) {
      setLoading(false);
      return;
    }

    // 获取初始 session
    supabase.auth.getSession().then(({ data: { session } }) => {
      setSession(session);
      setUser(session?.user ?? null);
      setLoading(false);
      if (session?.access_token) handlePlatformSync(session.access_token);
    });

    // 监听 auth 状态变化
    const { data: { subscription } } = supabase.auth.onAuthStateChange(
      (_event, session) => {
        setSession(session);
        setUser(session?.user ?? null);
        // 登录或 token 刷新时同步平台配置
        if (session?.access_token) handlePlatformSync(session.access_token);
      }
    );

    return () => subscription.unsubscribe();
  }, [isCloud]);

  const syncingRef = useRef(false);
  const handlePlatformSync = useCallback(async (accessToken: string) => {
    if (syncingRef.current) return;  // 防止并发
    syncingRef.current = true;
    try {
      await syncPlatformConfig(accessToken);
    } finally {
      syncingRef.current = false;
    }
  }, []);

  const signIn = useCallback(async (email: string, password: string) => {
    const { error } = await supabase.auth.signInWithPassword({ email, password });
    return { error: error?.message ?? null };
  }, []);

  const signUp = useCallback(async (email: string, password: string) => {
    const { error } = await supabase.auth.signUp({ email, password });
    return { error: error?.message ?? null };
  }, []);

  const signOut = useCallback(async () => {
    await supabase.auth.signOut();
  }, []);

  return (
    <AuthContext.Provider value={{ user, session, loading, isCloud, signIn, signUp, signOut }}>
      {children}
    </AuthContext.Provider>
  );
}

export const useAuth = () => useContext(AuthContext);