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

// ─── 布局修正（仅对单 grid 简单图表生效，多 grid 复杂图表保持原样） ───
function normalizeOption(rawOption: EChartsOption): EChartsOption {
  const option = structuredClone(rawOption) as Record<string, unknown>;

  const isMultiGrid =
    Array.isArray(option.grid) && (option.grid as unknown[]).length > 1;

  // ══════════════════════════════════════════════════════
  // 多 Grid 布局（K线+MACD+RSI 等多面板图表）
  // 只调整 title / legend 位置，保留 grid/axis 原始布局
  // ══════════════════════════════════════════════════════
  if (isMultiGrid) {
    // ── 标题：主标题固定顶部居中 ──
    if (Array.isArray(option.title)) {
      const titles = option.title as Record<string, unknown>[];
      if (titles.length > 0) {
        titles[0] = { ...titles[0], top: 4, left: "center" };
      }
    } else if (option.title && typeof option.title === "object") {
      option.title = {
        ...(option.title as Record<string, unknown>),
        top: 4,
        left: "center",
      };
    }
    // ── 压缩 grid 布局，为底部腾出空间 ──
    const grids = option.grid as Record<string, unknown>[];
    const BOTTOM_RESERVE = 25; // 底部保留 20% 给 x轴标签 + legend
    const parsed = grids.map((g) => ({
      top: parseFloat(String(g.top ?? "0").replace("%", "")),
      height: parseFloat(String(g.height ?? "0").replace("%", "")),
    }));
    const startOffset = parsed[0]?.top || 8;
    const maxBottom = Math.max(
      ...parsed.map((p) => p.top + p.height)
    );
    const usedSpace = maxBottom - startOffset;
    const targetSpace = 100 - BOTTOM_RESERVE - startOffset;
    if (usedSpace > 0 && targetSpace < usedSpace) {
      const scale = targetSpace / usedSpace;
      option.grid = grids.map((g, i) => ({
        ...g,
        top: `${(startOffset + (parsed[i].top - startOffset) * scale).toFixed(1)}%`,
        height: `${(parsed[i].height * scale).toFixed(1)}%`,
      }));
      // 同步压缩子面板标题位置（title 数组中 index ≥ 1 的条目）
      if (Array.isArray(option.title)) {
        const titles = option.title as Record<string, unknown>[];
        for (let i = 1; i < titles.length; i++) {
          const t = titles[i];
          if (t && typeof t === "object" && t.top != null) {
            const oldTop = parseFloat(
              String(t.top).replace("%", "")
            );
            if (!isNaN(oldTop) && oldTop >= startOffset) {
              const newTop =
                startOffset + (oldTop - startOffset) * scale;
              titles[i] = { ...t, top: `${newTop.toFixed(1)}%` };
            }
          }
        }
      }
    }
    // ── legend 移到底部 ──
    if (option.legend) {
      const patchLegend = (leg: Record<string, unknown>) => {
        const patched = {
          ...leg,
          bottom: 0,
          left: "center",
          orient: leg.orient || "horizontal",
          type: "scroll" as const, // 图例过多时可滚动
          textStyle: { fontSize: 11, ...(typeof leg.textStyle === "object" ? leg.textStyle : {}) },
        };
        delete patched.top;
        return patched;
      };
      if (Array.isArray(option.legend)) {
        option.legend = (
          option.legend as Record<string, unknown>[]
        ).map((item) =>
          item && typeof item === "object" ? patchLegend(item) : item
        );
      } else if (typeof option.legend === "object") {
        option.legend = patchLegend(
          option.legend as Record<string, unknown>
        );
      }
    }
    return option;
  }

  // ══════════════════════════════════════════════════════
  // 单 Grid 布局（普通柱状图/折线图/饼图等）
  // ══════════════════════════════════════════════════════
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
  } else if (!option.grid) {
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
  const htmlOption = structuredClone(option) as Record<string, unknown>;

  // 多 grid 图表不覆盖布局
  const isMultiGrid =
    Array.isArray(htmlOption.grid) &&
    (htmlOption.grid as unknown[]).length > 1;
  if (!isMultiGrid) {
    // 仅单 grid 时调整布局
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
  } else {
    // 多 grid：将 legend 移到底部（与 normalizeOption 同逻辑）
    if (htmlOption.legend && typeof htmlOption.legend === "object" && !Array.isArray(htmlOption.legend)) {
      const leg = htmlOption.legend as Record<string, unknown>;
      const patched: Record<string, unknown> = { ...leg, bottom: 0, left: "center" };
      delete patched.top;
      htmlOption.legend = patched;
    }
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
    #chart { width: 100%; height: 100%; min-height: 580px; }
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

  // 多面板图表自动增大高度，确保每个面板有足够空间
  const effectiveHeight = React.useMemo(() => {
    if (
      Array.isArray(option.grid) &&
      (option.grid as unknown[]).length > 1
    ) {
      const gridCount = (option.grid as unknown[]).length;
      // 每面板 200px + 底部 80px 给标签和 legend
      return Math.max(height, gridCount * 200 + 80, 600);
    }
    return height;
  }, [option, height]);


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