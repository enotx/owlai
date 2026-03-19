# backend/app/prompts/fragments/data_conventions.py

"""DataFrame 变量命名规范 — 用于自动捕获结果"""

DATAFRAME_NAMING_CONVENTION = """\
## DataFrame Naming Convention (IMPORTANT)
When your code produces **key result DataFrames** that would be valuable for the user to preview, \
you MUST name them using one of these prefixes so the system can auto-capture them:
- `result` / `result_xxx` — final or intermediate analysis results \
(e.g. `result`, `result_top10`, `result_by_region`)
- `output` / `output_xxx` — processed/transformed data ready for review \
(e.g. `output`, `output_cleaned`, `output_pivot`)
- `summary` / `summary_xxx` — aggregated summaries or statistics \
(e.g. `summary`, `summary_stats`, `summary_monthly`)

Examples:
```python
# ✅ Good — will be captured for user preview
result_top10 = df.nlargest(10, 'revenue')
summary_by_city = df.groupby('city').agg({'revenue': 'sum'}).reset_index()
output = df[df['status'] == 'active']

# ❌ Bad — generic names won't be captured
temp = df.nlargest(10, 'revenue')
x = df.groupby('city').agg({'revenue': 'sum'})
```\
"""