// frontend/src/contexts/onboarding-context.tsx
"use client";

import { createContext, useContext, useEffect, useState, ReactNode } from "react";
import { useBackend } from "./backend-context";
import { useDatabase } from "./database-context";
import { fetchProviders } from "@/lib/api";

interface OnboardingContextValue {
  /** 是否应该显示新手引导 */
  shouldShowOnboarding: boolean;
  /** 是否有配置（至少一个 Provider） */
  hasConfiguration: boolean;
  /** 配置检测状态 */
  configCheckStatus: "idle" | "checking" | "checked";
  /** 重新检测配置 */
  recheckConfiguration: () => void;
  /** 临时跳过新手引导（仅当前会话有效） */
  skipOnboarding: () => void;
}

const OnboardingContext = createContext<OnboardingContextValue | undefined>(undefined);

interface OnboardingProviderProps {
  children: ReactNode;
}

export function OnboardingProvider({ children }: OnboardingProviderProps) {
  const { isReady } = useBackend();
  
  const [hasConfiguration, setHasConfiguration] = useState(false);
  const [configCheckStatus, setConfigCheckStatus] = useState<"idle" | "checking" | "checked">("idle");
  const [hasSkipped, setHasSkipped] = useState(false); // 临时跳过状态，不持久化

  const checkConfiguration = async () => {
    if (!isReady) return;
    
    setConfigCheckStatus("checking");
    try {
      const response = await fetchProviders();
      const hasConfig = response.data.length > 0;
      setHasConfiguration(hasConfig);
      console.log(`📋 Configuration check: ${response.data.length} provider(s) found`);
    } catch (error) {
      console.error("Failed to check configuration:", error);
      setHasConfiguration(false);
    } finally {
      setConfigCheckStatus("checked");
    }
  };

  const { shouldShowWarning: showDatabaseWarning, isChecking: isDatabaseChecking } = useDatabase();
  // 等待后端就绪 + 数据库检查完成 + 数据库兼容后再检测配置
  useEffect(() => {
    if (isReady && !isDatabaseChecking && !showDatabaseWarning && configCheckStatus === "idle") {
      checkConfiguration();
    }
  }, [isReady, isDatabaseChecking, showDatabaseWarning, configCheckStatus]);

  // 计算是否应该显示新手引导：后端就绪 + 检测完成 + 无配置 + 未跳过
  const shouldShowOnboarding =
    isReady &&
    configCheckStatus === "checked" &&
    !hasConfiguration &&
    !hasSkipped;

  const value: OnboardingContextValue = {
    shouldShowOnboarding,
    hasConfiguration,
    configCheckStatus,
    recheckConfiguration: checkConfiguration,
    skipOnboarding: () => setHasSkipped(true),
  };

  return (
    <OnboardingContext.Provider value={value}>
      {children}
    </OnboardingContext.Provider>
  );
}

export function useOnboarding(): OnboardingContextValue {
  const context = useContext(OnboardingContext);
  if (!context) {
    throw new Error("useOnboarding must be used within OnboardingProvider");
  }
  return context;
}