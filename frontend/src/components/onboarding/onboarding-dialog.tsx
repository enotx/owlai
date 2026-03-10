// frontend/src/components/onboarding/onboarding-dialog.tsx
"use client";

import { useState } from "react";
import { Dialog, DialogContent, DialogTitle } from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { ArrowLeft, Loader2 } from "lucide-react";
import { verifyActivationCode, applyActivationConfig } from "@/lib/api";
import { useSettingsStore } from "@/stores/use-settings-store";
import { useOnboarding } from "@/contexts/onboarding-context";

interface OnboardingDialogProps {
  open: boolean;
  onClose: () => void;
}

type Step = "welcome" | "activation";

export default function OnboardingDialog({ open, onClose }: OnboardingDialogProps) {
  const [step, setStep] = useState<Step>("welcome");
  const [activationCode, setActivationCode] = useState("");
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  
  const { setSettingsOpen } = useSettingsStore();
  const { recheckConfiguration } = useOnboarding();

  const handleActivationSubmit = async () => {
    if (!activationCode.trim()) {
      setError("Please enter an activation code");
      return;
    }

    setIsSubmitting(true);
    setError(null);

    try {
      // 1. 验证激活码
      const response = await verifyActivationCode(activationCode);

      if (!response.valid || !response.config) {
        setError(response.message || "Invalid activation code");
        return;
      }

      // 2. 应用配置
      await applyActivationConfig(response.config);

      // 3. 重新检测配置
      await recheckConfiguration();

      // 4. 关闭对话框
      onClose();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to activate. Please try again later");
    } finally {
      setIsSubmitting(false);
    }
  };

  const handleConfigureMyself = () => {
    onClose();
    setSettingsOpen(true);
  };

  const handleSkip = () => {
    onClose();
  };

  const handleBack = () => {
    setStep("welcome");
    setActivationCode("");
    setError(null);
  };

  return (
    <Dialog open={open} onOpenChange={(open) => !open && onClose()}>
      <DialogContent
        className="w-[90vw] sm:w-[500px] p-0 gap-0"
        showCloseButton={false}
      >
        <DialogTitle className="sr-only">
          {step === "welcome" ? "Welcome to Owl" : "Enter Activation Code"}
        </DialogTitle>

        {step === "welcome" ? (
          <div className="flex flex-col p-8 gap-6">
            <div className="text-center space-y-2">
              <h2 className="text-2xl font-bold">🦉 Welcome to Owl</h2>
              <p className="text-sm text-muted-foreground">
                Before you get started, please configure your AI model
              </p>
            </div>

            <div className="flex flex-col gap-3">
              <Button
                variant="outline"
                className="h-14 text-base justify-start"
                onClick={() => setStep("activation")}
              >
                Use Activation Code
              </Button>

              <Button
                variant="outline"
                className="h-14 text-base justify-start"
                onClick={handleConfigureMyself}
              >
                Configure AI Model Manually
              </Button>
            </div>

            <Button
              variant="ghost"
              className="text-muted-foreground"
              onClick={handleSkip}
            >
              Skip
            </Button>
          </div>
        ) : (
          <div className="flex flex-col p-8 gap-6">
            <Button
              variant="ghost"
              size="icon"
              className="absolute left-4 top-4 h-8 w-8"
              onClick={handleBack}
            >
              <ArrowLeft className="h-4 w-4" />
            </Button>

            <div className="text-center space-y-2 mt-8">
              <h2 className="text-xl font-bold">Enter Activation Code</h2>
              <p className="text-sm text-muted-foreground">
                After activation, your AI model will be configured automatically
              </p>
            </div>

            <div className="space-y-4">
              <Input
                placeholder="Please enter activation code"
                value={activationCode}
                onChange={(e) => {
                  setActivationCode(e.target.value);
                  setError(null);
                }}
                onKeyDown={(e) => {
                  if (e.key === "Enter" && !isSubmitting) {
                    handleActivationSubmit();
                  }
                }}
                disabled={isSubmitting}
                className="h-12 text-center text-lg"
              />

              {error && (
                <p className="text-sm text-destructive text-center">{error}</p>
              )}

              <Button
                className="w-full h-12 text-base"
                onClick={handleActivationSubmit}
                disabled={isSubmitting || !activationCode.trim()}
              >
                {isSubmitting ? (
                  <>
                    <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                    Activating...
                  </>
                ) : (
                  "Submit"
                )}
              </Button>
            </div>
          </div>
        )}
      </DialogContent>
    </Dialog>
  );
}