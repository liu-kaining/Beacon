"""AI analysis generator using OpenAI JSON Mode."""

import json
import os

from openai import OpenAI

SYSTEM_PROMPT = """你是一位顶级宏观经济分析师。请根据输入的英文表格和文本，输出专业的中文研报。

你的输出必须是一个严格的 JSON 对象，包含以下四个键：
- "core_insight": 一句话核心洞察，直击要害（30字以内）
- "data_highlights": 关键数据亮点数组（2-4个字符串）
- "deep_dive": 深度解读文本（150-300字）
- "glossary": 专业术语数组，每个元素包含 "term" 和 "explanation" 键（1-3个术语）

注意：
- 全部使用中文
- 数据分析要具体、有数字支撑
- 深度解读要有观点、有逻辑
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

        # Validate keys
        required_keys = {"core_insight", "data_highlights", "deep_dive", "glossary"}
        if not required_keys.issubset(result.keys()):
            print(f"[ai] Missing keys in response: {required_keys - result.keys()}")
            return None

        return result

    except Exception as e:
        print(f"[ai] Error generating analysis: {e}")
        return None
