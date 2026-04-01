// frontend/src/components/chat/echarts-view.tsx

"use client";

import React, { useEffect, useRef } from "react";
import { Download, FileCode2 } from "lucide-react";

type EChartsOption = Record<string, unknown>;

// ─── 从 option 中提取图表标题，用于文件命名 ───
function getChartTitle(option: EChartsOption): string {
  if (
    option.title &&
    typeof option.title === "object" &&
    !Array.isArray(option.title)
  ) {
    const title = option.title as Record<string, unknown>;
    if (typeof title.text === "string" && title.text.trim()) {
      return title.text.trim();
    }
  }
  return "chart";
}

// ─── 布局修正（保留标题，legend/toolbox 移到底部） ───
function normalizeOption(rawOption: EChartsOption): EChartsOption {
  const option = structuredClone(rawOption) as Record<string, unknown>;

  if (
    option.title &&
    typeof option.title === "object" &&
    !Array.isArray(option.title)
  ) {
    option.title = { ...option.title, top: 18, left: "center" };
  }

  if (
    option.grid &&
    typeof option.grid === "object" &&
    !Array.isArray(option.grid)
  ) {
    option.grid = {
      ...option.grid,
      top: 80,
      bottom: 40,
      left: 20,
      right: 20,
      containLabel: true,
    };
  } else {
    option.grid = {
      top: 80,
      bottom: 40,
      left: 20,
      right: 20,
      containLabel: true,
    };
  }

  if (
    option.toolbox &&
    typeof option.toolbox === "object" &&
    !Array.isArray(option.toolbox)
  ) {
    option.toolbox = {
      ...option.toolbox,
      top: "auto",
      bottom: 8,
      left: 8,
      right: "auto",
    };
  }

  if (option.legend) {
    if (Array.isArray(option.legend)) {
      option.legend = option.legend.map((item) =>
        item && typeof item === "object"
          ? { ...item, top: "auto", bottom: 8, left: "center" }
          : item
      );
    } else if (typeof option.legend === "object") {
      option.legend = {
        ...option.legend,
        top: "auto",
        bottom: 8,
        left: "center",
      };
    }
  }

  if (option.dataZoom && Array.isArray(option.dataZoom)) {
    option.dataZoom = option.dataZoom.map((item) => {
      if (!item || typeof item !== "object") return item;
      const z = item as Record<string, unknown>;
      return z.type === "slider" ? { ...z, top: "auto", bottom: 36 } : z;
    });
  }

  return option;
}

// ─── 生成独立 HTML 文件（保留完整交互能力） ───
function generateStandaloneHTML(
  option: EChartsOption,
  title: string
): string {
  // 对独立页面做轻量布局调整（不需要和嵌入式一样激进）
  const htmlOption = structuredClone(option) as Record<string, unknown>;

  // 独立页面自适应，移除硬编码宽高
  if (
    htmlOption.grid &&
    typeof htmlOption.grid === "object" &&
    !Array.isArray(htmlOption.grid)
  ) {
    htmlOption.grid = {
      ...htmlOption.grid,
      top: 80,
      bottom: 40,
      left: 20,
      right: 20,
      containLabel: true,
    };
  }

  const optionJSON = JSON.stringify(htmlOption, null, 2);

  return `<!DOCTYPE html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>${title}</title>
  <script src="https://cdn.jsdelivr.net/npm/echarts@6/dist/echarts.min.js"><\/script>
  <style>
    * { margin: 0; padding: 0; box-sizing: border-box; }
    html, body { width: 100%; height: 100%; background: #fff; }
    #chart { width: 100%; height: 100%; min-height: 480px; }
  </style>
</head>
<body>
  <div id="chart"></div>
  <script>
    var chart = echarts.init(document.getElementById('chart'));
    var option = ${optionJSON};
    chart.setOption(option);
    window.addEventListener('resize', function () { chart.resize(); });
  <\/script>
</body>
</html>`;
}

// ─── 触发浏览器下载 ───
function downloadFile(
  content: string | Blob,
  filename: string,
  mimeType?: string
) {
  const blob =
    content instanceof Blob
      ? content
      : new Blob([content], { type: mimeType || "application/octet-stream" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  URL.revokeObjectURL(url);
}

// ─── 组件主体 ───
export default function EChartsView({
  option,
  height = 360,
}: {
  option: EChartsOption;
  height?: number;
}) {
  const divRef = useRef<HTMLDivElement | null>(null);
  const chartRef = useRef<unknown>(null);

  useEffect(() => {
    let disposed = false;

    async function mount() {
      if (!divRef.current) return;

      const echarts = await import("echarts");
      if (disposed) return;

      const chart = echarts.init(divRef.current);
      const normalizedOption = normalizeOption(option);
      chart.setOption(normalizedOption as any, { notMerge: true });

      chartRef.current = chart;

      const onResize = () => {
        try {
          (chart as any).resize();
        } catch {
          // ignore
        }
      };
      window.addEventListener("resize", onResize);

      return () => {
        window.removeEventListener("resize", onResize);
        try {
          (chart as any).dispose();
        } catch {
          // ignore
        }
      };
    }

    const cleanupPromise = mount();

    return () => {
      disposed = true;
      Promise.resolve(cleanupPromise).then((cleanup) => cleanup && cleanup());
    };
  }, [option]);

  // ─── 保存为 PNG 图片 ───
  const handleSaveImage = () => {
    const chart = chartRef.current as any;
    if (!chart) return;

    const title = getChartTitle(option);
    const dataURL = chart.getDataURL({
      type: "png",
      pixelRatio: 2,
      backgroundColor: "#fff",
    });

    const a = document.createElement("a");
    a.href = dataURL;
    a.download = `${title}.png`;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
  };

  // ─── 导出为独立 HTML（保留交互） ───
  const handleExportHTML = () => {
    const title = getChartTitle(option);
    const html = generateStandaloneHTML(option, title);
    downloadFile(html, `${title}.html`, "text/html;charset=utf-8");
  };

  return (
    <div className="w-full">
      {/* 图表主体 */}
      <div
        ref={divRef}
        className="w-full rounded-md border bg-background"
        style={{ height }}
      />

      {/* 导出工具栏 */}
      <div className="flex items-center gap-1 mt-1 justify-end">
        <button
          onClick={handleSaveImage}
          className="inline-flex items-center gap-1 px-2 py-1 text-xs
                     text-muted-foreground hover:text-foreground
                     rounded hover:bg-muted transition-colors"
          title="保存为图片"
        >
          <Download className="h-3 w-3" />
          <span>图片</span>
        </button>
        <button
          onClick={handleExportHTML}
          className="inline-flex items-center gap-1 px-2 py-1 text-xs
                     text-muted-foreground hover:text-foreground
                     rounded hover:bg-muted transition-colors"
          title="导出为可交互 HTML"
        >
          <FileCode2 className="h-3 w-3" />
          <span>HTML</span>
        </button>
      </div>
    </div>
  );
}