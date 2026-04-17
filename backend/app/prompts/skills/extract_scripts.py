# backend/app/prompts/skills/extract_scripts.py

"""Extract Script Skill - 从任务历史中提取可复用的通用脚本"""

import json

SKILL_NAME = "Extract Script"
SLASH_COMMAND = "script"
HANDLER_TYPE = "custom_handler"
HANDLER_CONFIG = {
    "handler_name": "extract_script",
    "max_react_rounds": 3,
}

DESCRIPTION = (
    "Extract a reusable Python script from task history. "
    "The script will be self-contained and can be executed independently."
)

PROMPT_MARKDOWN = """
When the user invokes `/script [optional instructions]`, your task is to:

1. **Analyze the task history** — Review all successful code executions
2. **Generate a self-contained Python script** that:
   - Includes ALL necessary imports at the top
   - Uses `datetime.now()` for dynamic values (not external parameters)
   - Loads data from pre-loaded variables or DuckDB tables
   - Applies all transformations
   - Outputs results via print() or creates visualizations
3. **Environment variables** — Only for configuration (API keys, thresholds), not runtime data

## Output Format

You MUST return a JSON object with these fields:

```json
{
  "name": "Script Name",
  "description": "Brief description",
  "code": "# Complete Python script\\nimport pandas as pd\\n...",
  "script_type": "general",
  "env_vars": {"THRESHOLD": "0.8"},
  "allowed_modules": ["pandas", "numpy"]
}
```

## Critical Rules

1. **Self-contained code** — Include ALL imports, no external dependencies
2. **Dynamic values in code** — Use `datetime.now()`, not parameters
3. **Environment variables** — Only for configuration (API keys, endpoints, thresholds)
4. **Use pre-loaded variables** — Check "Variable Reference" for exact names
5. **DuckDB access** — Use `getenv('WAREHOUSE_PATH')` (never hardcode paths); You can use getenv() directly in the sandbox, without import os.
6. **Deterministic** — Same input → same output (unless intentionally random)

## Example

```python
import pandas as pd
import numpy as np
from datetime import datetime, timedelta

# Configuration from environment
THRESHOLD = float(getenv('THRESHOLD', '0.8'))

# Dynamic date range (last 30 days)
end_date = datetime.now()
start_date = end_date - timedelta(days=30)

# Load data
df = sales_data.copy()
df['date'] = pd.to_datetime(df['date'])
df = df[(df['date'] >= start_date) & (df['date'] <= end_date)]

# Analysis
high_performers = df[df['score'] > THRESHOLD]
print(f"Found {len(high_performers)} high performers")
print(high_performers.head())
```
"""

REFERENCE_MARKDOWN = """
# Extract Script - Technical Reference

## Script Template

```python
# ═══════════════════════════════════════════════════════
# IMPORTS (ALL at the top)
# ═══════════════════════════════════════════════════════
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
import json

# ═══════════════════════════════════════════════════════
# CONFIGURATION (from environment variables)
# ═══════════════════════════════════════════════════════
THRESHOLD = float(getenv('THRESHOLD', '0.8'))
API_ENDPOINT = getenv('API_ENDPOINT', 'https://default.api')

# ═══════════════════════════════════════════════════════
# DYNAMIC VALUES (computed in code)
# ═══════════════════════════════════════════════════════
today = datetime.now()
last_month = today - timedelta(days=30)

# ═══════════════════════════════════════════════════════
# DATA LOADING
# ═══════════════════════════════════════════════════════
# Option A: Use pre-loaded CSV variables
df = sales_data.copy()

# Option B: Query DuckDB
import duckdb
con = duckdb.connect(getenv('WAREHOUSE_PATH'), read_only=True)
df = con.execute("SELECT * FROM my_table WHERE date >= ?", [last_month]).fetchdf()
con.close()

# ═══════════════════════════════════════════════════════
# TRANSFORMATION & ANALYSIS
# ═══════════════════════════════════════════════════════
df_clean = df.dropna()
result = df_clean.groupby('category').agg({'revenue': 'sum'})

# ═══════════════════════════════════════════════════════
# OUTPUT
# ═══════════════════════════════════════════════════════
print("Analysis Results:")
print(result)

# Optional: Create visualization
create_chart(
    title="Revenue by Category",
    chart_type="bar",
    option={
        "xAxis": {"type": "category", "data": result.index.tolist()},
        "yAxis": {"type": "value"},
        "series": [{"type": "bar", "data": result['revenue'].tolist()}]
    }
)
```

## Common Patterns

### Pattern 1: Backtest Script
```python
import pandas as pd
from datetime import datetime

# Load historical data
df = stock_prices.copy()

# Strategy logic
df['signal'] = (df['ma_short'] > df['ma_long']).astype(int)
df['returns'] = df['close'].pct_change()
df['strategy_returns'] = df['signal'].shift(1) * df['returns']

# Performance metrics
total_return = (1 + df['strategy_returns']).prod() - 1
sharpe = df['strategy_returns'].mean() / df['strategy_returns'].std() * (252 ** 0.5)

print(f"Total Return: {total_return:.2%}")
print(f"Sharpe Ratio: {sharpe:.2f}")
```

### Pattern 2: Report Generation
```python
import pandas as pd
from datetime import datetime

# Generate report for current month
today = datetime.now()
month_start = today.replace(day=1)

df = transactions.copy()
df['date'] = pd.to_datetime(df['date'])
df_month = df[df['date'] >= month_start]

# Summary statistics
summary = {
    "total_transactions": len(df_month),
    "total_revenue": df_month['amount'].sum(),
    "avg_transaction": df_month['amount'].mean(),
}

print(f"Monthly Report - {today.strftime('%Y-%m')}")
for key, value in summary.items():
    print(f"  {key}: {value}")
```

## Troubleshooting

### Issue: "Variable not found"
**Solution:** Check the "Variable Reference" in your context for exact pre-loaded variable names.

### Issue: "Module not allowed"
**Solution:** Add the module to `allowed_modules` in your JSON output.

### Issue: "Path not found"
**Solution:** Use `getenv('WAREHOUSE_PATH')` for DuckDB, never hardcode paths.
"""


def get_skill_definition() -> dict:
    """返回完整的 Skill 定义"""
    return {
        "name": SKILL_NAME,
        "slash_command": SLASH_COMMAND,
        "handler_type": HANDLER_TYPE,
        "handler_config": json.dumps(HANDLER_CONFIG),
        "description": DESCRIPTION,
        "prompt_markdown": PROMPT_MARKDOWN,
        "reference_markdown": REFERENCE_MARKDOWN,
        "is_active": True,
        "is_system": True,
    }