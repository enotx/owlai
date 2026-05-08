// owlai/frontend/src/components/data/cloud-hub-tab.tsx

"use client";

import { Cloud, Lock } from "lucide-react";

export default function CloudHubTab() {
  return (
    <div className="flex flex-1 flex-col items-center justify-center gap-4 p-8 text-muted-foreground">
      <div className="relative">
        <Cloud className="h-12 w-12 opacity-30" />
        <Lock className="h-4 w-4 absolute -bottom-1 -right-1 opacity-50" />
      </div>
      <div className="text-center space-y-1.5">
        <p className="text-sm font-medium text-foreground/70">Cloud Hub</p>
        <p className="text-xs max-w-[240px]">
          Public datasets hosted on owl-server will appear here.
          Subscribe to Pro to access curated datasets for your analysis.
        </p>
      </div>
      <div className="mt-2 rounded-lg border border-dashed px-4 py-3 text-center">
        <p className="text-[11px] text-muted-foreground">Coming soon</p>
      </div>
    </div>
  );
}