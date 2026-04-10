// frontend/src/components/settings/providers-list.tsx

"use client";

/**
 * Providers 列表视图
 */
import { useSettingsStore } from "@/stores/use-settings-store";
import { Button } from "@/components/ui/button";
import { deleteProvider } from "@/lib/api";
import { Sparkles } from "lucide-react";

export default function ProvidersList() {
  const { providers, setCurrentView, setEditingProvider, removeProvider } =
    useSettingsStore();

  const handleEdit = (provider: typeof providers[0]) => {
    setEditingProvider(provider);
    setCurrentView("edit");
  };

  const handleNew = () => {
    setEditingProvider(null);
    setCurrentView("edit");
  };

  const handleDisconnect = async (id: string) => {
    if (!confirm("Are you sure you want to delete this provider?")) return;
    try {
      await deleteProvider(id);
      removeProvider(id);
    } catch (err) {
      alert("Failed to delete provider");
    }
  };

  return (
    <div className="flex flex-col h-full">
      {/* 头部 */}
      <div className="px-6 py-4 border-b">
        <h3 className="text-lg font-semibold">Connected Providers</h3>
      </div>

      {/* 列表 */}
      <div className="flex-1 overflow-y-auto p-6">
        <div className="space-y-3">
          {providers.map((provider) => (
            <div
              key={provider.id}
              className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-3 p-4 border rounded-lg hover:bg-accent/50 transition-colors"
            >
              <div className="flex items-center gap-3 min-w-0">
                <Sparkles className="h-5 w-5 text-primary" />
                <span className="font-medium">{provider.display_name}</span>
              </div>
              <div className="flex gap-2 self-end sm:self-auto">
                <Button
                  variant="outline"
                  size="sm"
                  onClick={() => handleEdit(provider)}
                >
                  Edit
                </Button>
                <Button
                  variant="outline"
                  size="sm"
                  onClick={() => handleDisconnect(provider.id)}
                >
                  Disconnect
                </Button>
              </div>
            </div>
          ))}
        </div>

        {/* 新建按钮 */}
        <Button
          variant="outline"
          className="w-full mt-4"
          onClick={handleNew}
        >
          + New LLM
        </Button>
      </div>
    </div>
  );
}