// frontend/src/contexts/onboarding-context.tsx
"use client";

import {
  createContext,
  useContext,
  useEffect,
  useState,
  useCallback,
  useRef,
  ReactNode,
} from "react";
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
  recheckConfiguration: () => Promise<void>;
  /** 临时跳过新手引导（仅当前会话有效） */
  skipOnboarding: () => void;
}

const OnboardingContext = createContext<OnboardingContextValue | undefined>(undefined);

interface OnboardingProviderProps {
  children: ReactNode;
}

export function OnboardingProvider({ children }: OnboardingProviderProps) {
  const { isReady } = useBackend();
  const { shouldShowWarning: showDatabaseWarning, isChecking: isDatabaseChecking } = useDatabase();

  const [hasConfiguration, setHasConfiguration] = useState(false);
  const [configCheckStatus, setConfigCheckStatus] = useState<"idle" | "checking" | "checked">("idle");
  const [hasSkipped, setHasSkipped] = useState(false);

  // 防止自动检查重复触发
  const hasAutoCheckedRef = useRef(false);

  const checkConfiguration = useCallback(async () => {
    if (!isReady) return;

    const maxRetries = 3;
    const retryDelay = 1000;

    setConfigCheckStatus("checking");

    for (let attempt = 1; attempt <= maxRetries; attempt++) {
      try {
        console.log(`📋 [Onboarding] Configuration check attempt ${attempt}/${maxRetries}...`);
        const response = await fetchProviders();
        const hasConfig = response.data.length > 0;

        setHasConfiguration(hasConfig);
        setConfigCheckStatus("checked");
        console.log(`✅ [Onboarding] ${response.data.length} provider(s) found`);

        return; // 成功即结束
      } catch (error) {
        console.error(`❌ [Onboarding] Check attempt ${attempt} failed:`, error);

        if (attempt < maxRetries) {
          await new Promise((resolve) => setTimeout(resolve, retryDelay));
        } else {
          // 所有重试都失败：保守处理，不弹 onboarding（避免误导用户）
          setHasConfiguration(true);
          setConfigCheckStatus("checked");
          console.error("❌ [Onboarding] All retries failed, suppress onboarding for this session");
        }
      }
    }
  }, [isReady]);

  // 自动检查：等待后端就绪 + 数据库检查结束 + 无数据库警告
  useEffect(() => {
    if (!isReady) return;
    if (isDatabaseChecking) return;
    if (showDatabaseWarning) return;
    if (hasAutoCheckedRef.current) return;

    hasAutoCheckedRef.current = true;

    // 给后端一点缓冲时间，避免 health 刚通时其他接口还未稳定
    const timer = setTimeout(() => {
      checkConfiguration();
    }, 500);

    return () => clearTimeout(timer);
  }, [isReady, isDatabaseChecking, showDatabaseWarning, checkConfiguration]);

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