// frontend/src/lib/i18n.ts

import { getRequestConfig } from 'next-intl/server';
export default getRequestConfig(async ({ locale }) => {
  const resolvedLocale = locale || 'en';
  return {
    locale: resolvedLocale,
    messages: (await import(`../locales/${resolvedLocale}.json`)).default
  };
});
