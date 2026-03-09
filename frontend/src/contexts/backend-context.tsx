// frontend/src/contexts/backend-context.tsx
"use client";

import { createContext, useContext, useEffect, useState, ReactNode } from "react";
import { checkHealth } from "@/lib/api";

interface BackendContextValue {
  /** 后端连接状态 */
  status: "checking" | "connected" | "disconnected";
  /** 后端是否就绪（可以发起请求） */
  isReady: boolean;
  /** 手动触发重连 */
  reconnect: () => void;
}

const BackendContext = createContext<BackendContextValue | undefined>(undefined);

interface BackendProviderProps {
  children: ReactNode;
}

export function BackendProvider({ children }: BackendProviderProps) {
  const [status, setStatus] = useState<"checking" | "connected" | "disconnected">("checking");

  const attemptConnection = () => {
    let retryCount = 0;
    const maxRetries = 10;
    const retryDelay = 1000;

    const healthCheck = async () => {
      try {
        await checkHealth();
        setStatus("connected");
        console.log("✅ Backend connected successfully");
      } catch (error) {
        retryCount++;
        if (retryCount < maxRetries) {
          console.log(`⏳ Backend connection attempt ${retryCount}/${maxRetries}...`);
          setTimeout(healthCheck, retryDelay);
        } else {
          console.error("❌ Backend connection failed after max retries");
          setStatus("disconnected");
        }
      }
    };

    // Tauri 桌面模式下延迟启动
    const isTauri = typeof window !== "undefined" && !!window.__TAURI__;
    const initialDelay = isTauri ? 1000 : 0;

    setStatus("checking");
    setTimeout(healthCheck, initialDelay);
  };

  useEffect(() => {
    attemptConnection();
  }, []);

  const value: BackendContextValue = {
    status,
    isReady: status === "connected",
    reconnect: attemptConnection,
  };

  return (
    <BackendContext.Provider value={value}>
      {children}
    </BackendContext.Provider>
  );
}

/**
 * Hook：获取后端连接状态
 * @throws 如果在 BackendProvider 外部使用
 */
export function useBackend(): BackendContextValue {
  const context = useContext(BackendContext);
  if (!context) {
    throw new Error("useBackend must be used within BackendProvider");
  }
  return context;
}