# backend/app/prompts/skills/extract_sop.py

"""Extract SOP Skill - 从任务历史中提取标准作业程序"""

import json

SKILL_NAME = "Extract SOP"
SLASH_COMMAND = "sop"
HANDLER_TYPE = "custom_handler"
HANDLER_CONFIG = {
    "handler_name": "extract_sop",
}

DESCRIPTION = "Extract a Standard Operating Procedure from the current task's analysis flow."

# ── prompt_markdown: custom handler 的 system prompt ──
PROMPT_MARKDOWN = """\
You are an **SOP Documentation Specialist**. Your task is to analyze a data analysis workflow \
and produce a clear, reusable Standard Operating Procedure (SOP) document.

## Output Format

You MUST return a JSON object with the following structure:

```json
{
  "name": "Sales Data Analysis SOP",
  "description": "A reusable SOP for analyzing monthly sales data and generating summary outputs.",
  "content_markdown": "# Sales Data Analysis - Standard Operating Procedure\\n\\n## 1. Objective\\n..."
}
```

## Requirements

The `content_markdown` field must contain a Markdown document with the following structure:

```markdown
# [Task Name] - Standard Operating Procedure

## 1. Objective
Brief description of what this procedure accomplishes and when to use it.

## 2. Prerequisites
- Data sources required
- Tools/libraries needed
- Domain knowledge required

## 3. Procedure

### Step 1: [Step Name]
- Action 1
- Action 2
- Expected result

### Step 2: [Step Name]
- Action 1
- Action 2
- Expected result

## 4. Expected Outputs
- Output 1
- Output 2

## 5. Common Issues & Solutions

### Issue: [Error description]
**Solution:** [How to fix]

## 6. Notes
- Additional tips or context
- Limitations or assumptions
```

## Guidelines

1. **Return JSON only** — no markdown fences outside the JSON
2. **Be Specific**: Include exact column names, function calls, and parameter values when useful
3. **Be Reusable**: Abstract away task-specific filenames and use generalized names
4. **Include Context**: Explain WHY certain steps are needed, not just WHAT to do
5. **Add Troubleshooting**: Anticipate common errors based on the task history
6. **Keep It Concise**: Focus on the essential steps, avoid redundant explanations
7. **Set a clear name** in `name`
8. **Write a short summary** in `description`
"""

# ── reference_markdown: 详细示例（可选） ──
REFERENCE_MARKDOWN = """\
# Extract SOP - Technical Reference

## Example SOP

```markdown
# Sales Data Analysis - Standard Operating Procedure

## 1. Objective
Analyze monthly sales data to identify top-performing products and revenue trends.

## 2. Prerequisites
- Sales data CSV with columns: `date`, `product_id`, `quantity`, `price`, `category`
- Product information CSV with columns: `product_id`, `product_name`, `category`
- Python libraries: pandas, matplotlib

## 3. Procedure

### Step 1: Data Loading
- Load sales data: `df_sales = pd.read_csv('sales.csv')`
- Load product info: `df_products = pd.read_csv('products.csv')`
- Verify column names match expected schema

### Step 2: Data Cleaning
- Remove rows with missing critical fields: `df_sales.dropna(subset=['price', 'quantity'])`
- Convert date column to datetime: `df_sales['date'] = pd.to_datetime(df_sales['date'])`
- Handle outliers: Remove prices > 99th percentile

### Step 3: Data Merging
- Join sales with product info: `df_merged = df_sales.merge(df_products, on='product_id', how='left')`
- Verify no unmatched products

### Step 4: Metric Calculation
- Calculate revenue: `df_merged['revenue'] = df_merged['price'] * df_merged['quantity']`
- Group by product: `df_summary = df_merged.groupby('product_name').agg({'revenue': 'sum', 'quantity': 'sum'})`

### Step 5: Visualization
- Create bar chart of top 10 products by revenue
- Create line chart of monthly revenue trend

## 4. Expected Outputs
- Cleaned dataset with ~10,000 rows (after removing outliers)
- Summary table with revenue and quantity per product
- Bar chart: "Top 10 Products by Revenue"
- Line chart: "Monthly Revenue Trend"

## 5. Common Issues & Solutions

### Issue: "Column 'date' not found"
**Solution:** Check if the date column is named differently (e.g., 'order_date', 'transaction_date')

### Issue: "Memory error when loading large CSV"
**Solution:** Use `pd.read_csv(file, chunksize=10000)` to process in batches

### Issue: "Merge results in duplicate rows"
**Solution:** Check for duplicate product_ids in the product info file

## 6. Notes
- This procedure assumes data is in CSV format
- For datasets > 1GB, consider using DuckDB for processing
- Revenue calculation assumes price is per unit
```

## Tips for Writing Good SOPs

1. **Use Active Voice**: "Load the data" instead of "The data should be loaded"
2. **Number Steps Clearly**: Makes it easy to reference specific steps
3. **Include Code Snippets**: Show exact commands when helpful
4. **Explain Assumptions**: "This assumes price is in USD"
5. **Link to Resources**: Reference documentation or related SOPs
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