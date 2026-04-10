// frontend/src/contexts/i18n-context.tsx

"use client";

import { createContext, useContext, ReactNode } from "react";
import { useSettingsStore } from "@/stores/use-settings-store";
import { NextIntlClientProvider } from "next-intl";

const I18nContext = createContext<{ locale: string }>({ locale: "en" });

export function I18nProvider({ children }: { children: ReactNode }) {
  const locale = useSettingsStore((state) => state.locale);

  // 动态加载对应语言的翻译文件
  const messages = require(`@/locales/${locale}.json`);

  return (
    <NextIntlClientProvider locale={locale} messages={messages}>
      {children}
    </NextIntlClientProvider>
  );
}

export function useI18n() {
  return useContext(I18nContext);
}
