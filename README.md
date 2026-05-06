# Beacon

> Decoding Global Trends — 解构全球趋势

Beacon 是一个全自动化的宏观经济与数据可视化资讯站。它定时抓取 [Visual Capitalist](https://www.visualcapitalist.com/) 的 RSS 内容，通过 AI 生成中文深度研报，并以静态站点的形式发布。

**零后端、零数据库、全自动运行。**

## 工作原理

```
RSS Feed → 抓取解析 → 图片处理 → AI 分析 → 静态页面生成 → GitHub Pages 发布
```

1. **抓取** — 解析 RSS，提取标题、图片、表格/文本内容
2. **存储** — 图片压缩为模糊占位图（Base64），原图上传至 Cloudflare R2
3. **分析** — 调用 OpenAI API，生成包含核心洞察、关键数据、深度解读、术语表的中文研报
4. **渲染** — Jinja2 读取数据，生成 Tailwind CSS 深色主题静态页面
5. **部署** — GitHub Actions 每 8 小时自动运行，提交变更触发 Pages 部署

## 技术栈

| 层级 | 技术 |
|------|------|
| 包管理 | [uv](https://github.com/astral-sh/uv) (Python 3.11+) |
| RSS 解析 | feedparser + BeautifulSoup4 |
| 图片处理 | Pillow（模糊占位图）+ boto3（R2 上传） |
| AI 分析 | OpenAI API（JSON Mode，temperature=0.2） |
| 页面生成 | Jinja2 + Tailwind CSS (CDN) |
| 部署 | Docker + GitHub Actions + GitHub Pages |
| 图片托管 | Cloudflare R2 |

## 部署指南

### 前置准备

- GitHub 仓库
- Cloudflare R2 存储桶（已开启公开访问）
- OpenAI API Key

### 第一步：配置 GitHub Secrets

进入仓库 `Settings` → `Secrets and variables` → `Actions`，添加以下 Secrets：

| Secret 名称 | 说明 |
|-------------|------|
| `OPENAI_API_KEY` | OpenAI API 密钥 |
| `OPENAI_BASE_URL` | API 地址（默认 `https://api.openai.com/v1`，可替换为兼容服务） |
| `R2_ACCESS_KEY_ID` | Cloudflare R2 Access Key ID |
| `R2_SECRET_ACCESS_KEY` | Cloudflare R2 Secret Access Key |
| `R2_ENDPOINT_URL` | R2 端点，格式：`https://<account-id>.r2.cloudflarestorage.com` |
| `R2_BUCKET_NAME` | R2 存储桶名称 |
| `R2_PUBLIC_DOMAIN` | R2 公开访问域名，格式：`pub-<hash>.r2.dev` |

### 第二步：启用 GitHub Pages

进入仓库 `Settings` → `Pages`：

- **Source**: Deploy from a branch
- **Branch**: `main`
- **Folder**: `/docs`

### 第三步：推送代码

```bash
git add .
git commit -m "init: project beacon"
git push origin main
```

首次推送后，GitHub Actions 会自动运行。之后每 8 小时自动触发一次，也可在 `Actions` 页面手动触发 `workflow_dispatch`。

## 本地开发

```bash
# 克隆仓库
git clone https://github.com/<your-username>/Beacon.git
cd Beacon

# 安装依赖
uv sync

# 复制环境变量模板并填入真实值
cp .env.example .env
# 编辑 .env ...

# 运行
uv run python src/main.py
```

生成的静态页面会输出到 `docs/index.html`，可直接用浏览器打开预览。

## 项目结构

```
Beacon/
├── .github/workflows/
│   └── beacon.yml          # GitHub Actions 定时工作流
├── data/
│   └── posts.json          # 文章数据（Git 版本控制）
├── docs/
│   └── index.html          # 生成的静态站点（GitHub Pages 根目录）
├── src/
│   ├── main.py             # 调度引擎：串联 pipeline，幂等过滤，容错处理
│   ├── scraper.py          # RSS 抓取：表格转 Markdown，提取图片 URL
│   ├── storage.py          # 图片处理：模糊占位图 + R2 上传
│   ├── ai_processor.py     # AI 分析：OpenAI JSON Mode 生成中文研报
│   └── renderer.py         # 页面渲染：Jinja2 生成静态 HTML
├── templates/
│   └── index.jinja2        # 前端模板：Tailwind 深色主题 + 瀑布流 + Modal
├── Dockerfile              # 容器化配置
├── .dockerignore
├── .env.example            # 环境变量模板
├── pyproject.toml          # Python 依赖
└── uv.lock
```

## 前端特性

- **深色模式** — 深蓝背景 `#0F172A`，琥珀黄点缀 `#F59E0B`
- **瀑布流布局** — 1/2/4 列自适应（移动端/平板/桌面）
- **渐进式图片加载** — 超小模糊图作为占位符，IntersectionObserver 触发加载后淡入
- **抽屉式详情页** — 点击卡片弹出右侧滑出面板，展示高清图和 AI 研报
- **键盘支持** — Escape 关闭 Modal

## 数据结构

每篇文章存储为 `data/posts.json` 中的一个对象：

```json
{
  "id": "199081",
  "title": "The $126T Global Economy in One Giant Chart",
  "original_url": "https://www.visualcapitalist.com/...",
  "r2_image_url": "https://pub-xxx.r2.dev/199081.webp",
  "base64_blur": "data:image/jpeg;base64,/9j/4AAQ...",
  "pub_date": "2026-05-06T11:44:35+0000",
  "ai_analysis": {
    "core_insight": "全球经济规模达126万亿美元...",
    "data_highlights": ["美国GDP占全球25.6%", "..."],
    "deep_dive": "尽管美欧占据主导，但亚洲正在成为引擎...",
    "glossary": [{ "term": "名义GDP", "explanation": "..." }]
  }
}
```

## 许可证

[MIT](LICENSE)
