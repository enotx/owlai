# backend/app/prompts/fragments/echarts_guide.py

"""
ECharts 可视化指南，分为 RULES（永远注入）和 EXAMPLES（按需注入）。
"""

ECHARTS_RULES = """\
## Data Visualization (ECharts)

### When to Create Charts
Create visualizations ONLY when **ALL** of these are true:
1. You have **finished computing** the analysis results (not during exploration)
2. The results **genuinely benefit** from visual representation
3. The data has been **aggregated to a reasonable size** (≤ 50 data points per series)

**Do NOT** create charts:
- During exploratory / data-inspection steps (use `print()` instead)
- When the user only asked for numbers, statistics, or a table
- Before you have actual computed results
- When data has geographic coordinates (lat/lng) and the user wants spatial visualization — use `create_map(title, map_config)` instead (see Map Visualization section below)

### How to Create Charts
Call `create_chart(title, chart_type, option)` inside `execute_python_code`.
This lets you use computed Python variables directly in the ECharts option.
**Do NOT use matplotlib / seaborn / plotly.** Only ECharts via `create_chart()`.

#### Chart Type Quick Reference
| Data pattern | Chart type | Notes |
|---|---|---|
| Compare categories | `bar` | Use horizontal bar if labels are long |
| Trend over time | `line` | Add `smooth: True` for curves |
| Proportions | `pie` | ≤ 7 slices; group small ones as "Other" |
| Correlation (x vs y) | `scatter` | Add regression line if needed |
| Distribution | `boxplot` | Or `bar` histogram-style |
| Multi-dimension compare | `radar` | ≤ 6 axes |
| Density / matrix | `heatmap` | Needs `visualMap` component |
| Funnel / conversion | `funnel` | Sorted descending |

#### ECharts Option Requirements
- `option` must be a **complete, self-contained** ECharts option object
- Data must be **embedded directly** (use `.tolist()` on pandas objects)
- Always include: `title`, `tooltip`, `series`
- Include `legend` when there are multiple series
- Include `xAxis` / `yAxis` for cartesian charts
- Rotate long axis labels: `axisLabel: { rotate: 45 }`
- Keep data volume ≤ 50 points per series; aggregate if more
"""

ECHARTS_EXAMPLES = """\
### ECharts Code Examples

#### Example — Bar Chart
```python
revenue = df.groupby('region')['revenue'].sum().sort_values(ascending=False)
create_chart('Revenue by Region', 'bar', {
    'title': {'text': 'Revenue by Region', 'left': 'center'},
    'tooltip': {'trigger': 'axis'},
    'xAxis': {'type': 'category', 'data': revenue.index.tolist()},
    'yAxis': {'type': 'value', 'name': 'Revenue ($)'},
    'series': [{'type': 'bar', 'data': revenue.values.tolist(), 'name': 'Revenue'}]
})
```

#### Example — Line Chart
```python
trend = df.groupby('month')['sales'].sum().reset_index()
create_chart('Monthly Sales Trend', 'line', {
    'title': {'text': 'Monthly Sales Trend', 'left': 'center'},
    'tooltip': {'trigger': 'axis'},
    'xAxis': {'type': 'category', 'data': trend['month'].tolist()},
    'yAxis': {'type': 'value'},
    'series': [{'type': 'line', 'data': trend['sales'].tolist(), 'smooth': True}]
})
```

#### Example — Pie Chart
```python
share = df.groupby('product')['revenue'].sum()
create_chart('Market Share', 'pie', {
    'title': {'text': 'Market Share', 'left': 'center'},
    'tooltip': {'trigger': 'item'},
    'legend': {'orient': 'vertical', 'left': 'left'},
    'series': [{'type': 'pie', 'radius': '50%',
        'data': [{'value': v, 'name': n} for n, v in share.items()]
    }]
})
```
"""

# 向后兼容：旧代码 import ECHARTS_GUIDE 不会报错
ECHARTS_GUIDE = ECHARTS_RULES + "\n\n" + ECHARTS_EXAMPLES
