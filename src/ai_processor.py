"""AI analysis generator using OpenAI JSON Mode."""

import json
import os

from openai import OpenAI

SYSTEM_PROMPT = """你是一位顶级宏观经济与数据可视化分析师。请根据输入的英文表格和文本，输出专业的中文研报。

你的输出必须是一个严格的 JSON 对象，包含以下键：
- "core_insight": 一句话核心洞察，直击要害（30字以内）
- "data_highlights": 关键数据亮点数组（2-5个字符串），每条一句话概括，便于扫读
- "data_tables": 数组。若原文中有排名表、多列表格或类似「Rank / Country / Value」结构，必须抽取为完整表格，不得省略行。每个元素为对象：
  - "caption": 可选，表格短标题（中文）
  - "headers": 字符串数组，表头（建议保留英文列名如 Rank、Country，若原文为英文）
  - "rows": 二维字符串数组，每一行对应原文一行，行数与原文表格一致
  若原文无表格或无法结构化，传空数组 []
- "deep_dive": 深度解读，使用 Markdown，**必须有层次**：至少包含两个二级标题（以 ## 开头），下面可有短段落与要点列表（- ）。总篇幅约 400-800 字，覆盖机制、对比、启示或局限，避免一段到底。
- "glossary": 专业术语数组，每个元素包含 "term" 和 "explanation" 键（1-5个术语）

注意：
- 除表头与必要时保留的英文专名外，解读性文字用中文
- data_tables 中的数字、国名、排名必须与输入表格一致，不要编造行
- 深度解读要有观点、有逻辑、有分层
- 术语解释要简洁准确"""

USER_PROMPT_TEMPLATE = """请分析以下内容：

标题：{title}

内容：
{content}

请按照要求输出 JSON 格式的分析报告。"""


def generate_analysis(title: str, content_md: str) -> dict | None:
    """Call OpenAI API to generate structured analysis."""
    client = OpenAI(
        api_key=os.environ["OPENAI_API_KEY"],
        base_url=os.environ.get("OPENAI_BASE_URL", "https://api.openai.com/v1"),
    )

    user_msg = USER_PROMPT_TEMPLATE.format(title=title, content=content_md)

    try:
        response = client.chat.completions.create(
            model=os.environ.get("OPENAI_MODEL", "gpt-4o"),
            temperature=0.2,
            response_format={"type": "json_object"},
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user_msg},
            ],
        )
        result = json.loads(response.choices[0].message.content)

        required_keys = {"core_insight", "data_highlights", "data_tables", "deep_dive", "glossary"}
        if not required_keys.issubset(result.keys()):
            print(f"[ai] Missing keys in response: {required_keys - result.keys()}")
            return None

        tables = result.get("data_tables")
        if not isinstance(tables, list):
            result["data_tables"] = []
        else:
            cleaned = []
            for t in tables:
                if not isinstance(t, dict):
                    continue
                headers = t.get("headers")
                rows = t.get("rows")
                if not isinstance(headers, list) or not isinstance(rows, list):
                    continue
                headers = [str(h) for h in headers]
                norm_rows = []
                for row in rows:
                    if isinstance(row, list):
                        norm_rows.append([str(c) for c in row])
                if headers and norm_rows:
                    cap = t.get("caption")
                    item = {"headers": headers, "rows": norm_rows}
                    if isinstance(cap, str) and cap.strip():
                        item["caption"] = cap.strip()
                    cleaned.append(item)
            result["data_tables"] = cleaned

        return result

    except Exception as e:
        print(f"[ai] Error generating analysis: {e}")
        return None
