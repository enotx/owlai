# backend/app/prompts/skills/derive_data_source.py

import json

"""Derive Data Source Skill - 从任务历史中提取可复用的数据管道"""

SKILL_NAME = "Derive Data Source"
SLASH_COMMAND = "derive"
HANDLER_TYPE = "custom_handler"
HANDLER_CONFIG = {
    "handler_name": "derive_pipeline",
    "max_react_rounds": 3,
    "require_hitl_confirmation": True,
}

DESCRIPTION = (
    "Extract a reproducible data pipeline from task history and save to DuckDB warehouse. "
    "The system will analyze your successful code executions, generate a self-contained script, "
    "and present a confirmation card before saving."
)

# ── 简短的使用说明（给 LLM 看的） ──
PROMPT_MARKDOWN = """
When the user invokes `/derive [optional instructions]`, your task is to:

1. **Analyze the task history** — Review all successful code executions
2. **Generate a self-contained Python script** that:
   - Loads data from pre-loaded variables or DuckDB tables
   - Applies all transformations (cleaning, merging, aggregation)
   - Writes the result to DuckDB
   - Prints a `__DERIVE_OK__` JSON marker with metadata
3. **The script will be executed** — If it fails, you'll see the error and can retry (max 3 attempts)
4. **User confirms via HITL card** — After success, user decides whether to save

## Output Format

You MUST return a JSON object with these fields:

```json
{
  "table_name": "snake_case_table_name",
  "display_name": "Human Friendly Name",
  "description": "Brief description of the table",
  "source_type": "csv_upload" | "api" | "datasource" | "derived",
  "source_config": {"original_files": ["file1.csv"], ...},
  "transform_code": "# Complete Python script (see reference for template)",
  "transform_description": "Step-by-step explanation"
}
```

## Critical Rules for transform_code

1. Include ALL imports at the top
2. Use `getenv('WAREHOUSE_PATH')` for DuckDB connection (NEVER hardcode), and `getenv` is pre-imported for you, NEVER import os which is not allowed in the sandbox.
3. Check "Variable Reference" for exact pre-loaded variable names
4. Make code deterministic (same input → same output)
5. Close DuckDB connections after use
6. Print `__DERIVE_OK__` + JSON marker at the very end:

```python
print("__DERIVE_OK__" + json.dumps({
    "table_name": table_name,
    "schema": [{"name": col, "type": str(dtype)} for col, dtype in df.dtypes.items()],
    "row_count": len(df),
    "sample_rows": df.head(5).to_dict("records")
}, ensure_ascii=False))
```
"""

# ── 详细的技术文档（按需加载） ──
REFERENCE_MARKDOWN = """
# Derive Pipeline Extraction - Technical Reference

## Transform Code Template

Your `transform_code` MUST follow this structure:

```python
import pandas as pd
import duckdb
import json

# ═══════════════════════════════════════════════════════
# 1. DATA LOADING
# ═══════════════════════════════════════════════════════
# Option A: Use pre-loaded CSV variables (already in namespace)
# Example: df = sales_data.copy()

# Option B: Query existing DuckDB tables
# con = duckdb.connect(getenv('WAREHOUSE_PATH'), read_only=True)
# df = con.execute("SELECT * FROM existing_table WHERE date >= '2024-01-01'").fetchdf()
# con.close()

df = ...  # Your data loading logic here

# ═══════════════════════════════════════════════════════
# 2. TRANSFORMATION
# ═══════════════════════════════════════════════════════
# Apply all cleaning, merging, aggregation steps
df_clean = df.copy()

# Example transformations:
# - Drop missing values: df_clean = df_clean.dropna(subset=['important_col'])
# - Merge datasets: df_clean = df_clean.merge(other_df, on='key')
# - Aggregate: df_clean = df_clean.groupby('category').agg({'sales': 'sum'})
# - Add computed columns: df_clean['profit'] = df_clean['revenue'] - df_clean['cost']

# ... your transformation logic ...

# ═══════════════════════════════════════════════════════
# 3. WRITE TO DUCKDB (REQUIRED)
# ═══════════════════════════════════════════════════════
table_name = "your_table_name"  # Must match the table_name in JSON output

con = duckdb.connect(getenv('WAREHOUSE_PATH'))
con.execute(f"CREATE OR REPLACE TABLE {table_name} AS SELECT * FROM df_clean")
con.close()

# ═══════════════════════════════════════════════════════
# 4. OUTPUT MARKER (REQUIRED)
# ═══════════════════════════════════════════════════════
schema = [
    {"name": col, "type": str(dtype)} 
    for col, dtype in df_clean.dtypes.items()
]
sample_rows = df_clean.head(5).to_dict('records')

print("__DERIVE_OK__" + json.dumps({
    "table_name": table_name,
    "schema": schema,
    "row_count": len(df_clean),
    "sample_rows": sample_rows
}, ensure_ascii=False))
```

## Critical Rules

### ✅ DO
- Include ALL necessary imports at the top
- Use `getenv('WAREHOUSE_PATH')` for DuckDB connection (NEVER hardcode paths)
- Make the code deterministic (same input → same output)
- Use descriptive variable names
- Add comments explaining complex transformations
- Close DuckDB connections after use
- Print the `__DERIVE_OK__` marker at the very end

### ❌ DON'T
- Use interactive functions (input(), plt.show(), etc.)
- Hardcode file paths or credentials
- Rely on global state or external files
- Use random operations without setting seed
- Forget to print the success marker
- Use undefined variables (check the "Variable Reference" in context)

## Common Failure Patterns & Fixes

### 1. Missing Imports
**Error:** `NameError: name 'pd' is not defined`  
**Fix:** Add `import pandas as pd` at the top

### 2. Wrong Variable Names
**Error:** `NameError: name 'sales_data' is not defined`  
**Fix:** Check the "Variable Reference" section in your context for exact variable names. CSV files are pre-loaded with sanitized names (e.g., "Sales Data.csv" → `sales_data`)

### 3. DuckDB Connection Issues
**Error:** `duckdb.IOException: Cannot open file '/path/to/warehouse.duckdb'`  
**Fix:** Always use `getenv('WAREHOUSE_PATH')`, never hardcode paths

### 4. Missing Success Marker
**Error:** "Code executed successfully but did not print the __DERIVE_OK__ marker"  
**Fix:** Ensure the print statement is at the very end and uses the exact format shown in the template

### 5. Schema Mismatch
**Error:** `KeyError: 'column_name'`  
**Fix:** Verify that all columns referenced in transformations actually exist in the DataFrame

### 6. Memory Issues
**Error:** `MemoryError` or timeout  
**Fix:** 
- Use `df.head(10000)` to limit rows during development
- Avoid loading entire large tables if you only need recent data
- Use SQL filters in DuckDB queries: `WHERE date >= '2024-01-01'`

## ReACT Retry Strategy

If your generated code fails:
1. **Read the error message carefully** — It will tell you exactly what went wrong
2. **Check the error type**:
   - `NameError` → Missing import or wrong variable name
   - `KeyError` → Column doesn't exist
   - `TypeError` → Wrong data type in operation
   - `duckdb.IOException` → Path or connection issue
3. **Fix the specific issue** — Don't rewrite the entire script, just fix the bug
4. **Verify your fix** — Make sure the corrected code addresses the root cause

You have **3 attempts** to get it right. After 3 failures, the user will be prompted to fix manually.

## Complete Example

```python
import pandas as pd
import duckdb
import json

# Load pre-loaded CSV
df_sales = sales_data.copy()
df_products = product_info.copy()

# Merge datasets
df_merged = df_sales.merge(df_products, on='product_id', how='left')

# Clean data
df_clean = df_merged.dropna(subset=['price', 'quantity'])
df_clean['revenue'] = df_clean['price'] * df_clean['quantity']

# Aggregate by category
df_result = df_clean.groupby('category').agg({
    'revenue': 'sum',
    'quantity': 'sum'
}).reset_index()

# Write to DuckDB
table_name = "sales_by_category"
con = duckdb.connect(getenv('WAREHOUSE_PATH'))
con.execute(f"CREATE OR REPLACE TABLE {table_name} AS SELECT * FROM df_result")
con.close()

# Output marker
schema = [{"name": col, "type": str(dtype)} for col, dtype in df_result.dtypes.items()]
sample_rows = df_result.head(5).to_dict('records')

print("__DERIVE_OK__" + json.dumps({
    "table_name": table_name,
    "schema": schema,
    "row_count": len(df_result),
    "sample_rows": sample_rows
}, ensure_ascii=False))
```

## Troubleshooting Checklist

Before submitting your code, verify:
- [ ] All imports are at the top
- [ ] Variable names match the "Variable Reference" in context
- [ ] DuckDB connection uses `getenv('WAREHOUSE_PATH')`
- [ ] Connection is closed after use
- [ ] `__DERIVE_OK__` marker is printed at the end
- [ ] Code is self-contained (no external dependencies)
- [ ] Transformations are deterministic

## Input Context You'll Receive

1. **Code History** — List of successful code executions from the task:
   ```python
   [
     {
       "code": "df = sales_data.copy()\\ndf.head()",
       "output": "   product_id  quantity  price\\n0  A001       10      5.0",
       "purpose": "Load and inspect sales data"
     },
     ...
   ]
   ```

2. **User Instructions** — Optional guidance (e.g., "focus on the cleaned sales data")

3. **Available Data** — Summary of uploaded CSV files and existing DuckDB tables

4. **Previous Error** (if retry) — Error message from the last failed attempt
"""


def get_skill_definition() -> dict:
    """返回完整的 Skill 定义（用于数据库 seed）"""
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
