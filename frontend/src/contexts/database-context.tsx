// frontend/src/contexts/database-context.tsx

"use client";

import { createContext, useContext, useState, useEffect, useCallback, useRef, ReactNode } from "react";
import { checkDatabaseCompatibility, type DBCompatibilityResponse } from "@/lib/api";
import { useBackend } from "./backend-context";

interface DatabaseContextType {
  compatibility: DBCompatibilityResponse | null;
  isChecking: boolean;
  shouldShowWarning: boolean;
  dismissWarning: () => void;
  recheckCompatibility: () => Promise<void>;
}

const DatabaseContext = createContext<DatabaseContextType | undefined>(undefined);

export function DatabaseProvider({ children }: { children: ReactNode }) {
  const { isReady } = useBackend();
  const [compatibility, setCompatibility] = useState<DBCompatibilityResponse | null>(null);
  const [isChecking, setIsChecking] = useState(false);
  const [shouldShowWarning, setShouldShowWarning] = useState(false);
  const hasCheckedRef = useRef(false); // 使用 ref 而不是 state，避免触发额外渲染

  const recheckCompatibility = useCallback(async () => {
    console.log("🔍 [DB] Starting database compatibility check...");
    setIsChecking(true);
    try {
      const result = await checkDatabaseCompatibility();
      console.log("📊 [DB] Compatibility result:", result);
      setCompatibility(result);
      
      // 如果不兼容且数据库存在，显示警告
      if (!result.compatible && result.exists) {
        console.log("⚠️ [DB] Database incompatible, showing warning dialog");
        setShouldShowWarning(true);
      } else {
        console.log("✅ [DB] Database compatible or doesn't exist, no warning needed");
        setShouldShowWarning(false);
      }
      
      hasCheckedRef.current = true;
    } catch (error) {
      console.error("❌ [DB] Compatibility check failed:", error);
      // 检查失败时不显示警告，避免误报
      // 注意：不设置 hasCheckedRef.current = true，允许重试
      setShouldShowWarning(false);
    } finally {
      setIsChecking(false);
    }
  }, []);

  const dismissWarning = useCallback(() => {
    console.log("👋 [DB] Warning dismissed");
    setShouldShowWarning(false);
  }, []);

  // 等待后端就绪后再执行兼容性检查（带延迟和重试）
  useEffect(() => {
    if (!isReady) {
      console.log("🔌 [DB] Backend not ready, skipping check");
      return;
    }

    if (hasCheckedRef.current) {
      console.log("✓ [DB] Already checked, skipping");
      return;
    }

    console.log("🚀 [DB] Backend ready, scheduling compatibility check...");

    // 延迟 500ms 再检查，给后端更多准备时间
    const initialDelay = setTimeout(() => {
      let retryCount = 0;
      const maxRetries = 3;

      const attemptCheck = async () => {
        try {
          await recheckCompatibility();
          console.log("✅ [DB] Check completed successfully");
        } catch (error) {
          retryCount++;
          if (retryCount < maxRetries && isReady) {
            console.log(`⏳ [DB] Check failed, retrying (${retryCount}/${maxRetries})...`);
            setTimeout(attemptCheck, 1000); // 1秒后重试
          } else {
            console.error(`❌ [DB] Check failed after ${retryCount} attempts`);
          }
        }
      };

      attemptCheck();
    }, 500);

    return () => clearTimeout(initialDelay);
  }, [isReady, recheckCompatibility]);

  return (
    <DatabaseContext.Provider
      value={{
        compatibility,
        isChecking,
        shouldShowWarning,
        dismissWarning,
        recheckCompatibility,
      }}
    >
      {children}
    </DatabaseContext.Provider>
  );
}

export function useDatabase() {
  const context = useContext(DatabaseContext);
  if (!context) {
    throw new Error("useDatabase must be used within DatabaseProvider");
  }
  return context;
}