// frontend/src/components/chat/leaflet-map-view.tsx

"use client";

import React, { useEffect, useRef } from "react";
import { FileCode2 } from "lucide-react";

type MarkerConfig = {
  latlng: [number, number];
  type?: "circle" | "pin";
  radius?: number;
  color?: string;
  fillColor?: string;
  fillOpacity?: number;
  popup?: string;
  tooltip?: string;
};

type MapConfig = {
  center: [number, number];
  zoom?: number;
  markers?: MarkerConfig[];
  tile?: "amap" | "osm";
};

function sanitizeHTML(html: string): string {
  return html.replace(
    /<script\b[^<]*(?:(?!<\/script>)<[^<]*)*<\/script>/gi,
    ""
  );
}

function generateStandaloneHTML(config: MapConfig, title: string): string {
  const configJSON = JSON.stringify(config, null, 2);
  const tileURL =
    config.tile === "osm"
      ? "https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
      : "https://webrd02.is.autonavi.com/appmaptile?lang=zh_cn&size=1&scale=1&style=8&x={x}&y={y}&z={z}";

  return `<!DOCTYPE html>
<html>
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>${title}</title>
  <link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/leaflet@1.9.3/dist/leaflet.css"/>
  <script src="https://cdn.jsdelivr.net/npm/leaflet@1.9.3/dist/leaflet.js"><\/script>
  <style>
    * { margin: 0; padding: 0; box-sizing: border-box; }
    html, body { width: 100%; height: 100%; }
    #map { width: 100%; height: 100%; }
  </style>
</head>
<body>
  <div id="map"></div>
  <script>
    var config = ${configJSON};
    var map = L.map('map').setView(config.center, config.zoom || 11);
    L.tileLayer('${tileURL}', {
      maxZoom: 18,
      attribution: config.tile === 'osm' ? '© OpenStreetMap' : '© 高德地图'
    }).addTo(map);
    L.control.scale().addTo(map);
    (config.markers || []).forEach(function(m) {
      var marker;
      if (m.type === 'circle') {
        marker = L.circleMarker(m.latlng, {
          radius: m.radius || 8,
          color: m.color || '#3388ff',
          fillColor: m.fillColor || m.color || '#3388ff',
          fillOpacity: m.fillOpacity || 0.7
        });
      } else {
        marker = L.marker(m.latlng);
      }
      if (m.popup) marker.bindPopup(m.popup, { maxWidth: 250 });
      if (m.tooltip) marker.bindTooltip(m.tooltip, { sticky: true });
      marker.addTo(map);
    });
  <\/script>
</body>
</html>`;
}

function downloadFile(content: string, filename: string) {
  const blob = new Blob([content], { type: "text/html;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  URL.revokeObjectURL(url);
}

export default function LeafletMapView({
  config,
  height = 400,
}: {
  config: MapConfig;
  height?: number;
}) {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const leafletMapRef = useRef<any>(null);

  useEffect(() => {
    const existingLink = document.querySelector<HTMLLinkElement>(
      'link[data-leaflet-css="true"]'
    );
    if (existingLink) return;

    const link = document.createElement("link");
    link.rel = "stylesheet";
    link.href = "https://cdn.jsdelivr.net/npm/leaflet@1.9.3/dist/leaflet.css";
    link.dataset.leafletCss = "true";
    document.head.appendChild(link);

    return () => {
      link.remove();
    };
  }, []);

  useEffect(() => {
    let disposed = false;

    async function mount() {
      if (!containerRef.current) return;
      // 防止重复初始化
      if (leafletMapRef.current) return;

      const L = await import("leaflet");
      if (disposed) return;

      // ── 修复 Leaflet 默认 icon 路径（Next.js 打包后丢失） ──
      delete (L.Icon.Default.prototype as any)._getIconUrl;
      L.Icon.Default.mergeOptions({
        iconRetinaUrl:
          "https://cdn.jsdelivr.net/npm/leaflet@1.9.3/dist/images/marker-icon-2x.png",
        iconUrl:
          "https://cdn.jsdelivr.net/npm/leaflet@1.9.3/dist/images/marker-icon.png",
        shadowUrl:
          "https://cdn.jsdelivr.net/npm/leaflet@1.9.3/dist/images/marker-shadow.png",
      });

      const map = L.map(containerRef.current, {
        center: config.center,
        zoom: config.zoom || 11,
        zoomControl: true,
        attributionControl: true,
      });

      const tileURL =
        config.tile === "osm"
          ? "https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
          : "https://webrd02.is.autonavi.com/appmaptile?lang=zh_cn&size=1&scale=1&style=8&x={x}&y={y}&z={z}";

      L.tileLayer(tileURL, {
        maxZoom: 18,
        attribution:
          config.tile === "osm" ? "© OpenStreetMap" : "© 高德地图",
      }).addTo(map);

      L.control.scale().addTo(map);

      (config.markers || []).forEach((m) => {
        let marker: any;
        if (m.type === "circle") {
          marker = L.circleMarker(m.latlng, {
            radius: m.radius || 8,
            color: m.color || "#3388ff",
            fillColor: m.fillColor || m.color || "#3388ff",
            fillOpacity: m.fillOpacity ?? 0.7,
          });
        } else {
          marker = L.marker(m.latlng);
        }
        if (m.popup) marker.bindPopup(sanitizeHTML(m.popup), { maxWidth: 250 });
        if (m.tooltip) marker.bindTooltip(m.tooltip, { sticky: true });
        marker.addTo(map);
      });

      leafletMapRef.current = map;

      // ── 关键：延迟 invalidateSize，确保容器已完成布局 ──
      requestAnimationFrame(() => {
        if (!disposed) map.invalidateSize();
      });
    }

    mount();

    return () => {
      disposed = true;
      if (leafletMapRef.current) {
        try {
          leafletMapRef.current.remove();
        } catch {
          // ignore
        }
        leafletMapRef.current = null;
      }
    };
  }, [config]);

  const handleExportHTML = () => {
    const html = generateStandaloneHTML(config, "Map Visualization");
    downloadFile(html, "map.html");
  };

  return (
    <div className="w-full">
      {/*
        关键样式：
        - position:relative  → Leaflet 的绝对定位 pane 相对于此容器
        - overflow:hidden     → 防止瓦片/控件溢出到聊天区域
        - z-index:0           → 压住 Leaflet 内部的高 z-index pane
      */}
      <div
        ref={containerRef}
        className="w-full rounded-md border bg-background"
        style={{
          height,
          position: "relative",
          overflow: "hidden",
          zIndex: 0,
        }}
      />
      <div className="flex items-center gap-1 mt-1 justify-end">
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