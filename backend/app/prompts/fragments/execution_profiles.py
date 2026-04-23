# backend/app/prompts/fragments/execution_profiles.py

"""执行环境相关的 Prompt Profile — 根据 backend 类型切换"""

from dataclasses import dataclass


@dataclass(frozen=True)
class PromptProfile:
    """执行环境相关的 prompt 片段集合"""
    name: str
    sandbox_rules: str          # 安全限制说明
    data_access_guide: str      # 数据读取方式
    env_var_guide: str          # 环境变量访问方式
    warehouse_guide: str        # DuckDB 可用性 & 用法
    persistence_guide: str      # 变量持久化说明
    viz_note: str               # 可视化相关补充


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Local Sandbox Profile
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

LOCAL_SANDBOX_RULES = """\
## ⛔ Sandbox Restrictions (CRITICAL — Read Before Writing ANY Code)
Your code runs in a **restricted local sandbox**. The following are **BLOCKED and will cause errors**:

**Blocked modules** — Do NOT import:
- `os`, `sys`, `subprocess`, `shutil`, `pathlib`, `glob`, `io` (file-related)
- `socket`, `http`, `urllib`, `asyncio` (network-related)
- `pickle`, `shelve`, `sqlite3` (serialization / raw DB access)

**Blocked built-in functions** — Do NOT use:
- `open()`, `eval()`, `exec()`, `compile()`, `__import__()`
- `input()`, `breakpoint()`, `exit()`, `quit()`
- `globals()`, `locals()`, `vars()`, `setattr()`, `delattr()`

**Correct alternatives**:
| ❌ DON'T do this | ✅ DO this instead |
|---|---|
| `import os; os.getenv('KEY')` | `getenv('KEY')` — it's a pre-injected built-in |
| `open('file.csv')` / `pd.read_csv('path')` | Use the **pre-loaded DataFrame variables** listed in "Available Datasets" |
| `os.listdir()` / `glob.glob()` | Ask the user to upload files, or check "Variable Reference" for available data |
| `eval(expression)` | Write the expression directly in Python code |
| `import sqlite3` | Use `import duckdb; con = duckdb.connect(getenv('WAREHOUSE_PATH'), read_only=True)` |

**Allowed modules**: `pandas`, `numpy`, `math`, `statistics`, `collections`, \
`itertools`, `functools`, `re`, `datetime`, `json`, `decimal`, `random`, \
`sklearn`, `scipy`, `duckdb`, `pyarrow`, `time`, `xgboost`, `lightgbm`, \
plus any modules declared by active Skills.

**Key principle**: All data is either **pre-loaded as variables** or accessible via \
**DuckDB warehouse queries**. You never need to read files from disk yourself.\
"""

LOCAL_DATA_ACCESS = """\
## Data Access (Local Sandbox)
- All datasets are **pre-loaded as DataFrame variables** (see "Available Datasets" section)
- CSV files → `df_name` (already loaded, columns stripped)
- Excel files → `df_name` (default sheet) + `df_name_sheets` (all sheets dict)
- **DO NOT** use `pd.read_csv()` or `pd.read_excel()` — data is already in memory
- Previous step results are available as persisted variables (see "Variable Reference")\
"""

LOCAL_ENV_VAR = """\
## Environment Variables (Local Sandbox)
- Use `getenv('KEY')` to access environment variables (pre-injected built-in)
- **DO NOT** use `os.getenv()` or `os.environ` (blocked)
- Available keys are listed in each Skill's documentation\
"""

LOCAL_WAREHOUSE = """\
## DuckDB Warehouse (Local Sandbox)
The local DuckDB warehouse is a persistent data store shared across all tasks.

### Querying Existing Tables
- **List tables**: Use `list_duckdb_tables` tool to see available tables and their schemas
- **Query data**: Use `getenv('WAREHOUSE_PATH')` to connect
  ```python
  import duckdb
  con = duckdb.connect(getenv('WAREHOUSE_PATH'), read_only=True)
  df = con.execute("SELECT * FROM my_table LIMIT 100").fetchdf()
  con.close()
  ```

### Writing Data to DuckDB
When you need to save a DataFrame to the warehouse, write it directly in your code:

```python
import duckdb

# Connect to warehouse (read-write mode)
con = duckdb.connect(getenv('WAREHOUSE_PATH'))

# Strategy 1: Replace (drop and recreate) - RECOMMENDED for first-time writes
con.execute("DROP TABLE IF EXISTS my_table")
con.execute("CREATE TABLE my_table AS SELECT * FROM df_clean")

# Strategy 2: Append (add rows to existing table)
con.execute("INSERT INTO my_table SELECT * FROM df_clean")

# Strategy 3: Upsert (update existing rows, insert new ones)
# Requires a unique key column (e.g., 'id')
con.execute('''
    INSERT INTO my_table 
    SELECT * FROM df_clean
    ON CONFLICT (id) DO UPDATE SET
        column1 = EXCLUDED.column1,
        column2 = EXCLUDED.column2
''')

con.close()
print(f"✅ Saved {len(df_clean):,} rows to 'my_table'")
```

**Important guidelines:**
- Use descriptive table names (snake_case, lowercase, e.g., `stock_daily_prices`)
- Always close the connection after writing
- Print a confirmation message so the user knows the operation succeeded
- For first-time writes, consider using `request_human_input` to confirm the table name with the user
- The table will be automatically registered as a data asset and appear in the Data Sources panel
\
"""

### 下面是一段Warehouse的示例，先不注入了，观察效果
# **Common patterns:**
# ```python
# # Example 1: Save cleaned data
# con = duckdb.connect(getenv('WAREHOUSE_PATH'))
# con.execute("DROP TABLE IF EXISTS cleaned_sales")
# con.execute("CREATE TABLE cleaned_sales AS SELECT * FROM df_clean")
# con.close()
# print(f"✅ Saved {len(df_clean):,} rows to 'cleaned_sales'")

# # Example 2: Aggregate and save
# con = duckdb.connect(getenv('WAREHOUSE_PATH'))
# con.execute('''
#     CREATE OR REPLACE TABLE daily_summary AS
#     SELECT 
#         date,
#         SUM(amount) as total_amount,
#         COUNT(*) as transaction_count
#     FROM df_transactions
#     GROUP BY date
# ''')
# con.close()
# print("✅ Created daily_summary table")

# # Example 3: Join multiple DataFrames and save
# con = duckdb.connect(getenv('WAREHOUSE_PATH'))
# con.execute('''
#     CREATE OR REPLACE TABLE enriched_data AS
#     SELECT 
#         t.*,
#         u.user_name,
#         p.product_name
#     FROM df_transactions t
#     LEFT JOIN df_users u ON t.user_id = u.id
#     LEFT JOIN df_products p ON t.product_id = p.id
# ''')
# con.close()
# print("✅ Created enriched_data table")
# ```



LOCAL_PERSISTENCE = """\
## Variable Persistence (Local Sandbox)
- Variables persist **across code executions** within the same conversation
- If you created `df_cleaned` in a previous step, you can use it directly in the next call
- DataFrames are automatically saved to disk (Parquet format) and restored in subsequent steps
- Check "Variable Reference" section to see what's already available\
"""

LOCAL_VIZ_NOTE = """\
## Visualization (Local Sandbox)
- Use `create_chart(title, chart_type, option)` inside `execute_python_code` to create charts
- Use `create_map(title, config)` for geographic visualizations
- These are pre-injected built-ins — no import needed\
"""


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Jupyter Kernel Profile
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

JUPYTER_SANDBOX_RULES = """\
## 🌐 Remote Jupyter Environment
You are running in a **remote Jupyter kernel** with a standard Python environment.

**Key differences from local sandbox**:
- ✅ **No module restrictions** — you can import any installed package
- ✅ **Standard built-ins** — `open()`, `os.getenv()`, etc. work normally
- ⚠️ **File paths are remote** — uploaded files are on the Jupyter server, not your local machine
- ⚠️ **DuckDB is independent** — the remote kernel has its own DuckDB instance (if installed)

**Best practices**:
- Check if a module is available before using it: `try: import xxx except ImportError: ...`
- Use standard Python idioms — no need for workarounds like `getenv()` built-in
- Be mindful of file paths — they refer to the remote server's filesystem\
"""

JUPYTER_DATA_ACCESS = """\
## Data Access (Jupyter Kernel)
- Uploaded files are available at **remote file paths** (provided in context)
- You need to **explicitly load data** using standard pandas methods:
  ```python
  df = pd.read_csv('/path/to/uploaded/file.csv', encoding='utf-8-sig')
  df.columns = df.columns.str.strip()
  ```
- Excel files:
  ```python
  df = pd.read_excel('/path/to/file.xlsx')  # default sheet
  df_sheets = pd.read_excel('/path/to/file.xlsx', sheet_name=None)  # all sheets
  ```
- **Variables persist in kernel memory** — once loaded, you can reuse them across cells\
"""

JUPYTER_ENV_VAR = """\
## Environment Variables (Jupyter Kernel)
- Use standard Python: `os.getenv('KEY')` or `os.environ['KEY']`
- Environment variables are injected into the kernel at setup time
- Available keys are listed in each Skill's documentation\
"""

JUPYTER_WAREHOUSE = """\
## DuckDB Warehouse (Jupyter Kernel)

**Important**: The remote Jupyter kernel and local app have **completely separate environments**.

### Local App Warehouse (NOT accessible)
- The local app has a DuckDB warehouse for persistent data storage
- **You CANNOT access or write to it from the remote kernel**
- Any DuckDB operations you perform exist only in the remote kernel's memory

### Remote Kernel DuckDB (optional)
If DuckDB is installed in the remote kernel, you can use it for temporary analysis:

```python
try:
    import duckdb
    con = duckdb.connect(':memory:')  # in-memory database
    con.execute("CREATE TABLE temp AS SELECT * FROM df")
    result = con.execute("SELECT * FROM temp WHERE ...").fetchdf()
    con.close()
except ImportError:
    print("DuckDB not available - use pandas operations instead")
```

**Key limitations:**
- Any tables you create exist only in the remote kernel's memory
- They are NOT persisted and NOT accessible to other tasks
- They will be lost when the kernel restarts

### Data Persistence Strategy
If you need to save results for future use:
1. **Export to CSV/Parquet**: Save results as files in the remote environment
2. **Ask user to download**: Instruct the user to download the file from Jupyter
3. **Re-upload to local app**: User can upload the file as a new dataset in a future task

**Bottom line**: Treat the remote kernel as a temporary workspace. For persistent storage, \
coordinate with the user to transfer data back to the local app.\
"""

JUPYTER_PERSISTENCE = """\
## Variable Persistence (Jupyter Kernel)
- Variables persist **in kernel memory** across code executions
- Once you create `df_cleaned`, it remains available until the kernel restarts
- No automatic disk serialization — variables live in RAM
- Large DataFrames may consume significant memory — consider using `del` to free space\
"""

JUPYTER_VIZ_NOTE = """\
## Visualization (Jupyter Kernel)
- Use `create_chart(title, chart_type, option)` to create charts (injected at kernel startup)
- Use `create_map(title, config)` for geographic visualizations
- These functions are available after the initial setup code runs\
"""

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Profile Instances
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

LOCAL_PROFILE = PromptProfile(
    name="local_sandbox",
    sandbox_rules=LOCAL_SANDBOX_RULES,
    data_access_guide=LOCAL_DATA_ACCESS,
    env_var_guide=LOCAL_ENV_VAR,
    warehouse_guide=LOCAL_WAREHOUSE,
    persistence_guide=LOCAL_PERSISTENCE,
    viz_note=LOCAL_VIZ_NOTE,
)

JUPYTER_PROFILE = PromptProfile(
    name="jupyter_kernel",
    sandbox_rules=JUPYTER_SANDBOX_RULES,
    data_access_guide=JUPYTER_DATA_ACCESS,
    env_var_guide=JUPYTER_ENV_VAR,
    warehouse_guide=JUPYTER_WAREHOUSE,
    persistence_guide=JUPYTER_PERSISTENCE,
    viz_note=JUPYTER_VIZ_NOTE,
)


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Resolver
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def resolve_prompt_profile(backend_type: str) -> PromptProfile:
    """根据 backend 类型返回对应 profile
    
    Args:
        backend_type: "local" | "jupyter:{config_id}"
    """
    if backend_type.startswith("jupyter:") or backend_type == "jupyter":
        return JUPYTER_PROFILE
    return LOCAL_PROFILE