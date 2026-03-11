// frontend/src/contexts/database-context.tsx

"use client";

import { createContext, useContext, useState, useEffect, ReactNode } from "react";
import { checkDatabaseCompatibility, type DBCompatibilityResponse } from "@/lib/api";

interface DatabaseContextType {
  compatibility: DBCompatibilityResponse | null;
  isChecking: boolean;
  shouldShowWarning: boolean;
  dismissWarning: () => void;
  recheckCompatibility: () => Promise<void>;
}

const DatabaseContext = createContext<DatabaseContextType | undefined>(undefined);

export function DatabaseProvider({ children }: { children: ReactNode }) {
  const [compatibility, setCompatibility] = useState<DBCompatibilityResponse | null>(null);
  const [isChecking, setIsChecking] = useState(false);
  const [shouldShowWarning, setShouldShowWarning] = useState(false);

  const recheckCompatibility = async () => {
    setIsChecking(true);
    try {
      const result = await checkDatabaseCompatibility();
      setCompatibility(result);
      
      // 如果不兼容且数据库存在，显示警告
      if (!result.compatible && result.exists) {
        setShouldShowWarning(true);
      } else {
        setShouldShowWarning(false);
      }
    } catch (error) {
      console.error("数据库兼容性检查失败:", error);
      // 检查失败时不显示警告，避免误报
      setShouldShowWarning(false);
    } finally {
      setIsChecking(false);
    }
  };

  const dismissWarning = () => {
    setShouldShowWarning(false);
  };

  // 初始检查（仅在组件挂载时执行一次）
  useEffect(() => {
    recheckCompatibility();
  }, []);

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