// frontend/src/components/settings/about-view.tsx

"use client";

/**
 * About & Update 视图：
 * - 显示当前版本号
 * - 检查更新、展示 Release Notes
 * - 下载更新（SSE 进度）
 * - 打开安装包
 */

import { useEffect, useState, useCallback } from "react";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Separator } from "@/components/ui/separator";
import {
  Loader2,
  Download,
  CheckCircle,
  RefreshCw,
  FolderOpen,
  ExternalLink,
  AlertCircle,
} from "lucide-react";
import { useSettingsStore } from "@/stores/use-settings-store";
import {
  checkForUpdate,
  getPlatformInfo,
  installUpdate,
  getBaseUrl,
} from "@/lib/api";

/** 判断是否在 Tauri 桌面环境 */
function isTauri(): boolean {
  return typeof window !== "undefined" && "__TAURI__" in window;
}

/** 格式化文件大小 */
function formatBytes(bytes: number): string {
  if (bytes === 0) return "0 B";
  const k = 1024;
  const sizes = ["B", "KB", "MB", "GB"];
  const i = Math.floor(Math.log(bytes) / Math.log(k));
  return parseFloat((bytes / Math.pow(k, i)).toFixed(1)) + " " + sizes[i];
}

export default function AboutView() {
  const {
    updateStatus,
    updateInfo,
    downloadProgress,
    downloadedFilePath,
    setUpdateStatus,
    setUpdateInfo,
    setDownloadProgress,
    setDownloadedFilePath,
  } = useSettingsStore();

  const [currentVersion, setCurrentVersion] = useState<string>("...");
  const [platformLabel, setPlatformLabel] = useState<string>("");
  const [installMessage, setInstallMessage] = useState<string>("");

  // 获取当前版本和平台信息
  useEffect(() => {
    (async () => {
      try {
        if (isTauri()) {
          const { getVersion } = await import("@tauri-apps/api/app");
          const ver = await getVersion();
          setCurrentVersion(ver);

          const { platform, arch } = await import("@tauri-apps/plugin-os");
          const p = await platform();
          const a = await arch();
          setPlatformLabel(`${p} / ${a}`);
        } else {
          // 非 Tauri 环境，从后端获取
          const info = await getPlatformInfo();
          setPlatformLabel(`${info.platform} / ${info.arch}`);
          setCurrentVersion("dev");
        }
      } catch {
        setCurrentVersion("unknown");
      }
    })();
  }, []);

  // 检查更新
  const handleCheckUpdate = useCallback(async () => {
    if (!isTauri() || currentVersion === "..." || currentVersion === "unknown") return;

    setUpdateStatus("checking");
    setUpdateInfo(null);

    try {
      let plat = "macos";
      let architecture = "aarch64";

      try {
        const { platform, arch } = await import("@tauri-apps/plugin-os");
        const p = await platform();
        const a = await arch();
        plat = p === "macos" ? "macos" : p === "windows" ? "windows" : p;
        architecture = a === "aarch64" ? "aarch64" : "x86_64";
      } catch {
        // fallback 到后端
        const info = await getPlatformInfo();
        plat = info.platform;
        architecture = info.arch;
      }

      const result = await checkForUpdate(currentVersion, plat, architecture);
      setUpdateInfo(result);
      setUpdateStatus(result.has_update ? "has_update" : "up_to_date");
    } catch (err) {
      console.error("Check update failed:", err);
      setUpdateStatus("error");
    }
  }, [currentVersion, setUpdateStatus, setUpdateInfo]);

  // 进入 About 页面时自动检查（仅首次）
  useEffect(() => {
    if (updateStatus === "idle" && isTauri() && currentVersion !== "..." && currentVersion !== "unknown") {
      handleCheckUpdate();
    }
  }, [updateStatus, currentVersion, handleCheckUpdate]);

  // 下载更新
  const handleDownload = useCallback(async () => {
    if (!updateInfo?.download_url || !updateInfo?.file_name) return;

    setUpdateStatus("downloading");
    setDownloadProgress({ percent: 0, downloaded: 0, total: updateInfo.file_size || 0 });

    try {
      const baseUrl = await getBaseUrl();
      const params = new URLSearchParams({
        url: updateInfo.download_url,
        file_name: updateInfo.file_name,
      });
      const sseUrl = `${baseUrl}/updates/download-stream?${params.toString()}`;

      const response = await fetch(sseUrl);
      if (!response.ok || !response.body) {
        setUpdateStatus("error");
        return;
      }

      const reader = response.body.getReader();
      const decoder = new TextDecoder();
      let buffer = "";

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;

        buffer += decoder.decode(value, { stream: true });
        const parts = buffer.split("\n\n");
        buffer = parts.pop() || "";

        for (const part of parts) {
          for (const line of part.split("\n")) {
            if (!line.startsWith("data: ")) continue;
            try {
              const data = JSON.parse(line.slice(6));
              if (data.type === "progress") {
                setDownloadProgress({
                  percent: data.percent,
                  downloaded: data.downloaded_bytes,
                  total: data.total_bytes,
                });
              } else if (data.type === "complete") {
                setDownloadedFilePath(data.file_path);
                setUpdateStatus("downloaded");
                setDownloadProgress(null);
              } else if (data.type === "error") {
                console.error("Download error:", data.message);
                setUpdateStatus("error");
                setDownloadProgress(null);
              }
            } catch {
              // ignore parse errors
            }
          }
        }
      }
    } catch (err) {
      console.error("Download failed:", err);
      setUpdateStatus("error");
      setDownloadProgress(null);
    }
  }, [updateInfo, setUpdateStatus, setDownloadProgress, setDownloadedFilePath]);

  // 安装更新
  const handleInstall = useCallback(async () => {
    if (!downloadedFilePath) return;

    try {
      const result = await installUpdate(downloadedFilePath);
      setInstallMessage(result.data.message);
    } catch (err) {
      console.error("Install failed:", err);
      setInstallMessage("Failed to open installer. Please open the file manually.");
    }
  }, [downloadedFilePath]);

  // 打开日志目录（复用已有的 Tauri command）
  const handleOpenLogs = useCallback(async () => {
    if (isTauri()) {
      try {
        const { invoke } = await import("@tauri-apps/api/core");
        await invoke("open_log_directory");
      } catch (err) {
        console.error("Failed to open log directory:", err);
      }
    }
  }, []);

  return (
    <div className="h-full overflow-y-auto p-6">
      <div className="max-w-xl mx-auto space-y-8">
        {/* 应用信息 */}
        <div className="text-center space-y-2">
          <div className="text-4xl">🦉</div>
          <h1 className="text-xl font-bold">Owl Data Analyst</h1>
          <p className="text-sm text-muted-foreground">
            Version {currentVersion}
          </p>
          {platformLabel && (
            <p className="text-xs text-muted-foreground">{platformLabel}</p>
          )}
        </div>

        <Separator />

        {/* 更新区域 */}
        {isTauri() && (
          <div className="space-y-4">
            <h2 className="text-sm font-semibold">Software Update</h2>

            {/* 检查中 */}
            {updateStatus === "checking" && (
              <div className="flex items-center gap-2 text-sm text-muted-foreground">
                <Loader2 className="h-4 w-4 animate-spin" />
                Checking for updates...
              </div>
            )}

            {/* 已是最新 */}
            {updateStatus === "up_to_date" && (
              <div className="flex items-center justify-between">
                <div className="flex items-center gap-2 text-sm text-green-600">
                  <CheckCircle className="h-4 w-4" />
                  You&apos;re up to date
                </div>
                <Button variant="ghost" size="sm" onClick={handleCheckUpdate}>
                  <RefreshCw className="h-3 w-3 mr-1" />
                  Re-check
                </Button>
              </div>
            )}

            {/* 检查失败 */}
            {updateStatus === "error" && (
              <div className="flex items-center justify-between">
                <div className="flex items-center gap-2 text-sm text-destructive">
                  <AlertCircle className="h-4 w-4" />
                  Failed to check for updates
                </div>
                <Button variant="ghost" size="sm" onClick={handleCheckUpdate}>
                  <RefreshCw className="h-3 w-3 mr-1" />
                  Retry
                </Button>
              </div>
            )}

            {/* 有更新可用 */}
            {(updateStatus === "has_update" || updateStatus === "downloading" || updateStatus === "downloaded") &&
              updateInfo && (
                <div className="rounded-lg border p-4 space-y-4">
                  {/* 版本标题 */}
                  <div className="flex items-center justify-between">
                    <div className="flex items-center gap-2">
                      <Badge variant="default" className="text-xs">
                        v{updateInfo.latest_version}
                      </Badge>
                      <span className="text-sm font-medium">New version available</span>
                    </div>
                    {updateInfo.file_size && (
                      <span className="text-xs text-muted-foreground">
                        {formatBytes(updateInfo.file_size)}
                      </span>
                    )}
                  </div>

                  {/* Release Notes */}
                  {updateInfo.release_notes && (
                    <div className="rounded-md bg-muted/50 p-3 max-h-48 overflow-y-auto">
                      <pre className="text-xs whitespace-pre-wrap font-sans leading-relaxed">
                        {updateInfo.release_notes}
                      </pre>
                    </div>
                  )}

                  {/* 下载进度条 */}
                  {updateStatus === "downloading" && downloadProgress && (
                    <div className="space-y-2">
                      <div className="w-full bg-muted rounded-full h-2">
                        <div
                          className="bg-primary h-2 rounded-full transition-all duration-300"
                          style={{ width: `${downloadProgress.percent}%` }}
                        />
                      </div>
                      <div className="flex justify-between text-xs text-muted-foreground">
                        <span>
                          {formatBytes(downloadProgress.downloaded)} / {formatBytes(downloadProgress.total)}
                        </span>
                        <span>{downloadProgress.percent}%</span>
                      </div>
                    </div>
                  )}

                  {/* 安装提示 */}
                  {installMessage && (
                    <div className="rounded-md bg-blue-50 dark:bg-blue-950 p-3 text-xs text-blue-700 dark:text-blue-300">
                      {installMessage}
                    </div>
                  )}

                  {/* 操作按钮 */}
                  <div className="flex gap-2">
                    {updateStatus === "has_update" && (
                      <Button size="sm" onClick={handleDownload}>
                        <Download className="h-3 w-3 mr-1" />
                        Download Update
                      </Button>
                    )}

                    {updateStatus === "downloading" && (
                      <Button size="sm" disabled>
                        <Loader2 className="h-3 w-3 mr-1 animate-spin" />
                        Downloading...
                      </Button>
                    )}

                    {updateStatus === "downloaded" && (
                      <Button size="sm" onClick={handleInstall}>
                        <ExternalLink className="h-3 w-3 mr-1" />
                        Open Installer
                      </Button>
                    )}
                  </div>
                </div>
              )}

            {/* 空闲状态（首次未检查） */}
            {updateStatus === "idle" && (
              <Button variant="outline" size="sm" onClick={handleCheckUpdate}>
                <RefreshCw className="h-3 w-3 mr-1" />
                Check for Updates
              </Button>
            )}
          </div>
        )}

        {/* 非 Tauri 环境提示 */}
        {!isTauri() && (
          <div className="text-sm text-muted-foreground text-center">
            Auto-update is available in the desktop app.
          </div>
        )}

        <Separator />

        {/* 实用链接 */}
        <div className="space-y-3">
          {isTauri() && (
            <Button
              variant="outline"
              size="sm"
              className="w-full justify-start"
              onClick={handleOpenLogs}
            >
              <FolderOpen className="h-3 w-3 mr-2" />
              Open Log Directory
            </Button>
          )}
        </div>
      </div>
    </div>
  );
}