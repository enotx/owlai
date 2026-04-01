# backend/app/prompts/fragments/map_guide.py

"""
Leaflet + AMap 地图可视化指南，分为 RULES（永远注入）和 EXAMPLES（按需注入）。
"""

MAP_RULES = """\
## Map Visualization (Leaflet + AMap)

### When to Create Maps
Create maps ONLY when **ALL** of these are true:
1. Data contains **geographic coordinates** (latitude/longitude) or addresses
2. The spatial distribution is **meaningful** to the analysis
3. Data has been **aggregated to ≤ 500 markers** (performance limit)

**Do NOT** create maps:
- When data has no geographic dimension
- For simple location lists (use a table instead)
- Before geocoding addresses to coordinates

### How to Create Maps
Call `create_map(title, map_config)` inside `execute_python_code`.

#### Map Config Schema
```python
{
    "center": [31.23, 121.47],      # [latitude, longitude] - map center
    "zoom": 11,                      # zoom level (1-18, default: 11)
    "markers": [                     # list of markers
        {
            "latlng": [31.198, 121.460],  # [lat, lng] (required)
            "type": "circle",             # "circle" or "pin"
            "radius": 8,                  # circle size in pixels (for "circle")
            "color": "#E63946",           # border color
            "fillColor": "#E63946",       # fill color
            "fillOpacity": 0.7,           # 0.0 - 1.0
            "popup": "<b>Name</b><br>Value: 123",  # HTML popup (on click)
            "tooltip": "Name (123)"       # plain text tooltip (on hover)
        }
    ],
    "tile": "amap"  # "amap" (高德) or "osm" (OpenStreetMap), default: "amap"
}
```

### Map Config Requirements
- `center` must be `[latitude, longitude]` (required)
- `zoom` should be 1-18 (default: 11)
- `markers` must be a list (≤ 500 items for performance)
- Each marker must have `latlng` field
- Use `type: "circle"` for dense data, `type: "pin"` for sparse locations
- `popup` supports HTML; `tooltip` should be plain text
"""

MAP_EXAMPLES = """\
### Map Code Examples

#### Example — Scatter Map (点位分布)
```python
top_locations = df.nlargest(20, 'order_count')
markers = []
for _, row in top_locations.iterrows():
    markers.append({
        "latlng": [row['latitude'], row['longitude']],
        "type": "circle",
        "radius": 8,
        "color": "#E63946",
        "fillColor": "#E63946",
        "fillOpacity": 0.7,
        "popup": f"<b>{row['name']}</b><br>订单量: {row['order_count']}",
        "tooltip": f"{row['name']} ({row['order_count']})"
    })

create_map('订单热点分布 Top 20', {
    "center": [top_locations['latitude'].mean(), top_locations['longitude'].mean()],
    "zoom": 11,
    "markers": markers,
    "tile": "amap"
})
```

#### Example — Bubble Map (气泡大小编码数值)
```python
max_count = df['order_count'].max()
markers = []
for _, row in df.iterrows():
    radius = 5 + (row['order_count'] / max_count) * 15
    markers.append({
        "latlng": [row['lat'], row['lng']],
        "type": "circle",
        "radius": int(radius),
        "color": "#3388ff",
        "fillColor": "#3388ff",
        "fillOpacity": 0.6,
        "popup": f"{row['name']}: {row['order_count']}",
        "tooltip": row['name']
    })

create_map('订单量气泡图', {
    "center": [df['lat'].mean(), df['lng'].mean()],
    "zoom": 10,
    "markers": markers
})
```

#### Example — Color-Coded Map (颜色编码分类)
```python
color_map = {'A': '#E63946', 'B': '#F1C40F', 'C': '#2ECC71'}
markers = []
for _, row in df.iterrows():
    markers.append({
        "latlng": [row['lat'], row['lng']],
        "type": "pin",
        "color": color_map.get(row['category'], '#999'),
        "popup": f"<b>{row['name']}</b><br>类别: {row['category']}",
        "tooltip": row['name']
    })

create_map('门店分类分布', {
    "center": [31.23, 121.47],
    "zoom": 12,
    "markers": markers
})
```
"""

# 向后兼容
MAP_GUIDE = MAP_RULES + "\n\n" + MAP_EXAMPLES
