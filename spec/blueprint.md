# 🚢 Project Beacon (信标) - 核心蓝图与技术设计文档 (PRD & TDD)

## 第一部分：产品需求文档 (PRD)

### 1. 项目愿景与定位
* **产品名称**：Beacon (信标)
* **Slogan**：Decoding Global Trends. (解构全球趋势)
* **核心定位**：一个全自动化、高信噪比的宏观经济与数据可视化资讯站。
* **解决痛点**：降低 Visual Capitalist 原站高昂的英文阅读门槛与复杂的图表认知成本，过滤广告，通过 AI 提供直指核心的中文数据洞察。

### 2. 核心功能需求
* **全自动化内容抓取**：定时监控指定 RSS，发现新内容自动处理，无需人工干预。
* **AI 深度研报**：不只是“翻译”，而是基于图表和结构化表格，由 AI 扮演投行分析师，提炼：[核心洞察]、[关键数据]、[深度解读]、[术语解释]。
* **沉浸式画报体验 (Frontend UX)**：
  * **瀑布流布局 (Masonry Grid)**：自适应设备（手机双列，PC四列），突出高清长图的视觉冲击力。
  * **深色模式 (Dark Mode)**：纯黑/深灰背景，配以“琥珀黄”或“霓虹绿”作为点缀色（Accent Color），呼应“灯塔/信标”的品牌概念。
  * **抽屉式详情页 (Slide-over/Modal)**：点击首页图片不跳转新页面，直接从底部/侧边弹出全屏高清大图与 AI 解析面板。
  * **极速加载 (Progressive Image)**：使用超小尺寸的 Base64 模糊图作为占位符，实现渐进式优雅加载。

### 3. 非功能需求
* **极简运维 (Serverless)**：绝对不使用服务端（如 FastAPI/Flask/数据库）。完全基于静态生成（Static Site Generation）。
* **零成本/极低成本**：利用 GitHub Actions (计算)、GitHub Pages (托管)、Cloudflare R2 (图床)。

---

## 第二部分：技术设计文档 (TDD)

### 1. 技术栈选型
* **包管理**：`uv` (Python 3.11+)
* **依赖库**：
  * 解析：`feedparser`, `beautifulsoup4`
  * 图床交互：`boto3`
  * 图像处理：`Pillow` (用于生成模糊 Base64 占位图)
  * AI 调用：`openai` (使用 JSON Mode 保证结构化输出)
  * 页面生成：`Jinja2`
* **前端栈**：HTML5 + Tailwind CSS (通过 CDN 引入或独立编译) + 原生 JavaScript (Vanilla JS)。

### 2. 系统架构与数据流 (Data Pipeline)
整个系统由 GitHub Actions 通过 Cron 定时任务（每 8 小时）触发，执行以下流水线：

1. **Scraper (抓取层)**：读取 RSS，提取 `title`, `link`, `guid`，深度解析 `<content:encoded>` 提取 `<table>` (转为 Markdown)，抓取 `<media:content>` 获取原图 URL。
2. **Storage (存储层)**：将原图下载至内存 -> 使用 `Pillow` 压缩成 20px 宽并应用高斯模糊，转为 Base64 字符串 -> 将原图上传至 Cloudflare R2，获取公开 URL。
3. **AI Processor (分析层)**：将提取的 Markdown 表格和文本喂给多模态/大语言模型，强制返回 JSON 格式的分析结果。
4. **Data Layer (持久化)**：将处理后的完整对象追加（Prepend）到本地的 `data/posts.json` 的头部。
5. **Renderer (渲染层)**：`Jinja2` 读取 `posts.json`，注入 Tailwind 模板，生成 `docs/index.html`。
6. **Deploy (部署)**：Action 自动 Commit 新的 JSON 和 HTML，触发 GitHub Pages 发布。

### 3. 数据结构定义 (`data/posts.json`)
```json
[
  {
    "id": "199081",
    "title": "The $126T Global Economy in One Giant Chart",
    "original_url": "https://www.visualcapitalist.com/...",
    "r2_image_url": "https://pub-yourdomain.r2.dev/199081.webp",
    "base64_blur": "data:image/jpeg;base64,/9j/4AAQSkZJ...",
    "pub_date": "2026-05-06T11:44:35+0000",
    "ai_analysis": {
      "core_insight": "全球经济规模达126万亿美元，但高度集中，中美德日四国占据半壁江山。",
      "data_highlights": [
        "美国GDP占全球25.6%，位居榜首。",
        "中国GDP预计2026年实际增长4.4%。"
      ],
      "deep_dive": "尽管美欧占据主导，但亚洲正在成为全球经济增长的引擎...",
      "glossary": [
        { "term": "名义GDP", "explanation": "未剔除通货膨胀影响的国内生产总值..." }
      ]
    }
  }
]
```

### 4. 目录结构
```text
beacon/
├── .github/
│   └── workflows/
│       └── beacon_pipeline.yml  # 自动化工作流
├── data/
│   └── posts.json               # 核心数据库（Git 版本控制）
├── docs/                        # GitHub Pages 托管目录
│   └── index.html               # 最终生成的静态站点
├── src/
│   ├── main.py                  # 统筹调度主入口
│   ├── scraper.py               # RSS与HTML解析
│   ├── storage.py               # R2上传与图片Base64处理
│   ├── ai_processor.py          # AI Prompt 构建与 API 调用
│   └── renderer.py              # Jinja2 静态渲染
├── templates/
│   └── index.jinja2             # 前端 HTML+Tailwind 模板
├── pyproject.toml               # uv 依赖管理
└── .env.example                 # 环境变量说明
```

---
