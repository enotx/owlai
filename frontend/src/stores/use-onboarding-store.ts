// frontend/src/stores/use-onboarding-store.ts
import { create } from "zustand";
import { persist } from "zustand/middleware";

interface OnboardingStore {
  /** 是否已完成新手引导 */
  hasCompletedOnboarding: boolean;
  /** 标记为已完成 */
  completeOnboarding: () => void;
  /** 重置（用于测试） */
  resetOnboarding: () => void;
}

export const useOnboardingStore = create<OnboardingStore>()(
  persist(
    (set) => ({
      hasCompletedOnboarding: false,
      completeOnboarding: () => set({ hasCompletedOnboarding: true }),
      resetOnboarding: () => set({ hasCompletedOnboarding: false }),
    }),
    {
      name: "owl-onboarding",
    }
  )
);