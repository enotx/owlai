# backend/app/tools/definitions.py

"""
所有 Tool 的 OpenAI Function Calling JSON Schema 定义。
单一来源：Agent 层统一从这里导入，不再各自定义。
"""

EXECUTE_PYTHON_CODE_TOOL = {
    "type": "function",
    "function": {
        "name": "execute_python_code",
        "description": (
            "Execute Python code in a sandboxed environment with pandas, numpy, "
            "sklearn, scipy pre-installed. All uploaded datasets are pre-loaded as DataFrames. "
            "Use print() to output results. "
            "Use this tool to explore data, compute statistics, verify hypotheses, etc. "
            "If you want to create a chart, call create_chart(title, chart_type, option) "
            "inside this code block."
            "If you want to create a map with geographic data (lat/lng), call "
            "create_map(title, map_config) inside this code block."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "code": {
                    "type": "string",
                    "description": "Python code to execute. Use print() for output.",
                },
                "purpose": {
                    "type": "string",
                    "description": "Brief description of what this code does (1 sentence).",
                },
            },
            "required": ["code", "purpose"],
        },
    },
}

CREATE_VISUALIZATION_TOOL = {
    "type": "function",
    "function": {
        "name": "create_visualization",
        "description": (
            "Create an interactive ECharts chart. "
            "Only use this AFTER you have computed final results and the user "
            "would benefit from a visual representation. "
            "PREFER using create_chart() inside execute_python_code instead, "
            "as it lets you use Python variables directly. "
            "You MUST provide a complete ECharts option with embedded data."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "title": {
                    "type": "string",
                    "description": "Chart title (concise, descriptive)",
                },
                "chart_type": {
                    "type": "string",
                    "enum": [
                        "bar", "line", "pie", "scatter",
                        "radar", "heatmap", "boxplot", "funnel",
                    ],
                    "description": "Chart type",
                },
                "option": {
                    "type": "object",
                    "description": (
                        "Complete ECharts option JSON with data embedded. "
                        "Must contain at least: title, tooltip, series."
                    ),
                },
            },
            "required": ["title", "chart_type", "option"],
            "additionalProperties": False,
        },
    },
}

GET_SKILL_REFERENCE_TOOL = {
    "type": "function",
    "function": {
        "name": "get_skill_reference",
        "description": (
            "Retrieve the detailed reference documentation for a specific skill. "
            "Use this when you need exact API signatures, parameter details, "
            "advanced usage patterns, or error handling guidance for a skill. "
            "The skill's basic description and usage prompt are already in your context — "
            "only call this when you need the full reference."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "skill_name": {
                    "type": "string",
                    "description": "Exact name of the skill (as shown in 'Available Skills' section).",
                },
            },
            "required": ["skill_name"],
        },
    },
}

REQUEST_HUMAN_INPUT_TOOL = {
    "type": "function",
    "function": {
        "name": "request_human_input",
        "description": (
            "Pause execution and ask the user to choose from predefined options. "
            "Use this when you encounter a situation that requires human judgment, such as:\n"
            "- Multiple valid data cleaning strategies (e.g., fill missing values with mean vs. median vs. drop)\n"
            "- Ambiguous join keys when merging datasets\n"
            "- Data quality issues that need user decision\n"
            "- Multiple valid analysis directions\n\n"
            "DO NOT use this for simple clarification questions — just ask in text.\n"
            "Only use when there are concrete, enumerable options to present.\n"
            "After the user responds, you will see their choice in the conversation and should proceed accordingly."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "title": {
                    "type": "string",
                    "description": "Short title for the decision card, e.g. 'Missing Value Strategy'",
                },
                "description": {
                    "type": "string",
                    "description": "Context explaining why you need the user's input (1-2 sentences).",
                },
                "options": {
                    "type": "array",
                    "description": "2-5 concrete options for the user to choose from. Each option should be actionable.",
                    "items": {
                        "type": "object",
                        "properties": {
                            "label": {
                                "type": "string",
                                "description": "Human-readable option label, e.g. 'Fill with Mean (Average value)'",
                            },
                            "value": {
                                "type": "string",
                                "description": "Machine-readable option identifier, e.g. 'fill_mean'",
                            },
                            "badge": {
                                "type": "string",
                                "description": "Optional short badge text shown on the right, e.g. '74.2' or '-14 rows'",
                            },
                        },
                        "required": ["label", "value"],
                    },
                    "minItems": 2,
                    "maxItems": 5,
                },
            },
            "required": ["title", "description", "options"],
        },
    },
}

