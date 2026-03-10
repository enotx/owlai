// frontend/src/contexts/onboarding-context.tsx
"use client";

import { createContext, useContext, useEffect, useState, ReactNode } from "react";
import { useBackend } from "./backend-context";
import { fetchProviders } from "@/lib/api";
import { useOnboardingStore } from "@/stores/use-onboarding-store";

interface OnboardingContextValue {
  /** 是否应该显示新手引导 */
  shouldShowOnboarding: boolean;
  /** 是否有配置（至少一个 Provider） */
  hasConfiguration: boolean;
  /** 配置检测状态 */
  configCheckStatus: "idle" | "checking" | "checked";
  /** 重新检测配置 */
  recheckConfiguration: () => void;
  /** 标记新手引导已完成 */
  completeOnboarding: () => void;
}

const OnboardingContext = createContext<OnboardingContextValue | undefined>(undefined);

interface OnboardingProviderProps {
  children: ReactNode;
}

export function OnboardingProvider({ children }: OnboardingProviderProps) {
  const { isReady } = useBackend();
  const { hasCompletedOnboarding, completeOnboarding: markCompleted } = useOnboardingStore();
  
  const [hasConfiguration, setHasConfiguration] = useState(false);
  const [configCheckStatus, setConfigCheckStatus] = useState<"idle" | "checking" | "checked">("idle");

  const checkConfiguration = async () => {
    if (!isReady) return;
    
    setConfigCheckStatus("checking");
    try {
      const response = await fetchProviders();
      setHasConfiguration(response.data.length > 0);
      console.log(`📋 Configuration check: ${response.data.length} provider(s) found`);
    } catch (error) {
      console.error("Failed to check configuration:", error);
      setHasConfiguration(false);
    } finally {
      setConfigCheckStatus("checked");
    }
  };

  // 后端就绪后自动检测配置
  useEffect(() => {
    if (isReady && configCheckStatus === "idle") {
      checkConfiguration();
    }
  }, [isReady]);

  // 计算是否应该显示新手引导
  const shouldShowOnboarding =
    isReady &&
    configCheckStatus === "checked" &&
    !hasConfiguration &&
    !hasCompletedOnboarding;

  const value: OnboardingContextValue = {
    shouldShowOnboarding,
    hasConfiguration,
    configCheckStatus,
    recheckConfiguration: checkConfiguration,
    completeOnboarding: markCompleted,
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