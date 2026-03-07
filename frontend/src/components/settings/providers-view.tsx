// frontend/src/components/settings/providers-view.tsx

"use client";

/**
 * Providers 列表和编辑视图
 */
import { useSettingsStore } from "@/stores/use-settings-store";
import ProvidersList from "./providers-list";
import ProviderForm from "./provider-form";

export default function ProvidersView() {
  const { currentView } = useSettingsStore();

  return currentView === "list" ? <ProvidersList /> : <ProviderForm />;
}