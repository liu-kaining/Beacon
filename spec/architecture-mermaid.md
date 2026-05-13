# Beacon 架构与流程（Mermaid）

与 [blueprint.md](./blueprint.md) 及 [architecture-plantuml.md](./architecture-plantuml.md)（PlantUML 版）**同构**：模块关系、流水线顺序、数据门禁与读者动线均对齐当前代码。

**如何渲染**：GitHub 预览、VS Code（Markdown 预览 / Mermaid 插件）、Notion、MkDocs（mermaid 插件）等可直接渲染下列 ` ```mermaid ` 块。

---

## 1. 系统上下文

```mermaid
flowchart LR
  Reader["读者"] --> Pages["GitHub Pages\ndocs/"]
  Maintainer["维护者"] --> GHA["GitHub Actions"]
  GHA --> Pipe["Beacon 管线\nDocker + Python"]
  Pipe --> VC["Visual Capitalist\nRSS / HTML"]
  Pipe --> OAI["OpenAI API"]
  Pipe --> R2["Cloudflare R2"]
  Pipe --> Pages
```

---

## 2. 部署与 CI（Docker + 卷）

```mermaid
flowchart TB
  subgraph runner["GitHub Actions ubuntu-latest"]
    WS["workspace 检出"]
    Build["docker build → beacon-app"]
    RunMain["docker run\nCMD: src/main.py"]
    RunBackfill["docker run\nbackfill_images.py"]
    Commit["git-auto-commit-action"]
    N1["beacon.yml: cron 每 3h\n挂载 data/docs\ncommit 含 feed.xml"]
    N2["backfill-images.yml: 手动\n无 OPENAI\ncommit 常无 feed.xml"]
  end

  OAI["OpenAI"]
  R2["Cloudflare R2"]

  WS --> Build --> RunMain
  RunMain --> OAI
  RunMain --> R2
  RunMain -->|"写回卷"| WS
  RunMain -.-> N1

  WS --> RunBackfill
  RunBackfill --> R2
  RunBackfill --> WS
  RunBackfill -.-> N2

  WS --> Commit
```

---

## 3. Python 组件依赖

```mermaid
flowchart TB
  subgraph orch["编排"]
    Main["main.py"]
  end

  subgraph crawl["抓取与解析"]
    Scraper["scraper.py"]
    ImgPick["image_pick.py"]
  end

  subgraph media["媒体与存储"]
    Storage["storage.py"]
  end

  subgraph ai["AI"]
    AIProc["ai_processor.py"]
  end

  subgraph render["静态输出"]
    Renderer["renderer.py"]
  end

  subgraph ops["运维脚本"]
    Backfill["backfill_images.py"]
  end

  JSON[("data/posts.json")]
  Tpl["templates/index.jinja2"]
  Docs["docs/index.html\nfeed.xml"]

  Main --> Scraper
  Main --> Storage
  Main --> AIProc
  Main --> ImgPick
  Main --> Renderer
  Main --> JSON

  Scraper --> ImgPick

  Backfill --> ImgPick
  Backfill --> Storage
  Backfill --> JSON

  Renderer --> JSON
  Renderer --> Tpl
  Renderer --> Docs

  AIProc -.->|"OpenAI client"| AIProc
  Storage -.->|"下载 / 最小尺寸 / WebP / R2"| Storage

  Renderer -.->|"is_post_visible\n= 有效 AI + r2 非空"| Renderer
```

---

## 4. 主管线时序（`main.main`）

```mermaid
sequenceDiagram
  autonumber
  actor Op as CI / 本地
  participant Main as main.py
  participant JSON as posts.json
  participant Repair as repair_missing_hero_images
  participant VC as Visual Capitalist
  participant Pick as image_pick
  participant Img as storage.process_image
  participant R2 as Cloudflare R2
  participant Fetch as scraper.fetch_articles
  participant Gen as ai_processor
  participant OAI as OpenAI API
  participant Rend as renderer

  Op->>Main: main()
  Main->>JSON: load_existing_posts()
  JSON-->>Main: existing_posts

  Main->>Repair: repair_missing_hero_images(posts)
  loop 有效 AI 且无 r2_image_url
    Repair->>VC: GET original_url
    VC-->>Repair: HTML
    Repair->>Pick: pick_best_image_url_from_html
    Pick-->>Repair: URL?
    Repair->>Img: process_image(url, id)
    Img->>VC: GET 图片字节
    Img->>Img: 宽高 ≥ 640×320
    Img->>R2: put id.webp
    Img-->>Repair: r2_url, base64_blur
    Note over Repair: 就地修改 post 字典
  end

  Main->>Main: existing_urls = 非占位 AI 的 URL 集
  Main->>Fetch: fetch_articles(existing_urls)
  Fetch-->>Main: articles（新 URL）

  loop 每条 article
    Main->>Main: is_retry / 复用旧图?
    opt 需新图且 image_url 有值
      Main->>Img: process_image
      Img-->>Main: 或 None
    end
    opt content_md 非空
      Main->>Gen: generate_analysis
      Gen->>OAI: chat + json_object
      OAI-->>Gen: JSON
      Gen-->>Main: ai_analysis / None
    end
    opt AI 失败
      Main->>Main: 占位 INVALID…\n仍 append new_posts
    end
    Main->>Main: new_posts.append
  end

  Main->>Main: dedupe + publishable\n= has_valid_ai_analysis
  Main->>JSON: save_posts（条件满足时）
  Main->>Rend: render_site + render_rss
  Rend->>JSON: 读
  Rend->>Rend: 仅 is_post_visible + enrich
  Rend-->>Main: docs/*
```

---

## 5. `scraper._get_image_url` 决策

```mermaid
flowchart TD
  A[从 entry 取 content:encoded] --> B{pick_best\nfrom HTML?}
  B -->|是| Z[返回 URL]
  B -->|否| C[收集 media:content]
  C --> D{pick_best_from\ncandidates?}
  D -->|是| Z
  D -->|否| E{media_urls\n非空?}
  E -->|是| F[返回首个 media URL]
  E -->|否| G[GET 文章全文页]
  G --> H{pick_best\nfrom page HTML?}
  H -->|是| Z
  H -->|否| N[返回 None]
```

---

## 6. `storage.process_image`

```mermaid
flowchart TD
  S([开始]) --> D[download_image 最多 3 次]
  D --> Q{bytes?}
  Q -->|否| X([return None])
  Q -->|是| M[_decoded_image_meets_hero_minimum\n宽≥640 高≥320]
  M --> R{通过?}
  R -->|否| X
  R -->|是| B[generate_blur_base64]
  B --> U[upload_to_r2 WebP\nkey = id.webp]
  U --> OK([return r2_url, blur])
```

---

## 7. 持久化 vs 展示（两道门禁）

```mermaid
flowchart LR
  subgraph save["save_posts"]
    D1[deduped_posts] --> G1{"has_valid_ai_analysis?"}
    G1 -->|是| P[publishable 写入 JSON]
    G1 -->|否| DROP[丢弃占位分析]
  end

  subgraph view["render_site / render_rss"]
    R1[读 posts.json] --> G2{"is_post_visible?<br/>AI 有效且 r2 非空"}
    G2 -->|是| E[_enrich_post → HTML/RSS]
    G2 -->|否| SKIP[跳过]
  end
```

---

## 8. 读者端动线（静态页 + 内联 JS）

```mermaid
flowchart TD
  L[打开 Pages / index.html] --> T[Tailwind + Masonry 布局]
  T --> IO[IntersectionObserver\n懒加载 R2 大图]
  L --> S[搜索框输入]
  S --> F[applyPostFilters\ndata-search / search_text]
  L --> C[点击卡片]
  C --> M[openModal index\nposts 数组同序]
  M --> D[侧滑抽屉\n图 + AI 各块 + 原文表折叠]
  D --> LB[点击大图]
  LB --> LB2[openLightbox 全屏]
  LB2 --> ESC[Esc：先关 lightbox\n再关 modal]
  L --> RSS[页头 feed.xml]
```

---

## 9. 端到端数据流

```mermaid
flowchart LR
  VC["Visual Capitalist"]

  subgraph pipe["管线 Python"]
    MD["content_md\n表格或文本"]
    IU["image_url\n启发式"]
    AIX["ai_analysis JSON"]
    IMG["r2 / blur /\nimage_version"]
  end

  JSON[("posts.json")]
  R2["R2 id.webp"]
  HTML["index.html\n+ posts JSON"]
  RSS["feed.xml"]

  VC --> MD
  VC --> IU
  MD --> AIX
  IU --> IMG
  AIX --> JSON
  IMG --> JSON
  IMG --> R2
  JSON --> HTML
  JSON --> RSS
  HTML -->|"浏览器"| R2
```

---

## 10. `backfill_images.py` 工作流

```mermaid
flowchart TD
  L[load posts.json] --> UF{use_feed?}
  UF -->|是| MAP[分页 RSS 建映射]
  UF -->|否| LOOP
  MAP --> LOOP[遍历每篇 post]

  LOOP --> RESOLVE[解析 best_image_url]
  RESOLVE --> DRY{dry_run?}
  DRY -->|是| PRINT[仅打印]
  DRY -->|否| VAL{_validate_image_url?}
  VAL -->|是| PI[process_image → R2]
  PI --> W[写 post + image_version]
  VAL -->|否| NEXT
  PRINT --> NEXT{还有且未达 limit?}
  W --> NEXT
  NEXT -->|是| LOOP
  NEXT -->|否| SAVE[写回 posts.json]
  SAVE --> CI[CI 可选: render_site]
```

---

## 11. 单帖概念状态

```mermaid
stateDiagram-v2
  [*] --> Processing: RSS 新条目

  Processing --> PlaceholderAI: generate_analysis 失败
  PlaceholderAI --> [*]: 不进入 publishable\n下轮 RSS 再试

  Processing --> StoredNoImage: save 成功但无 r2\n或人工删图字段
  Processing --> StoredComplete: AI OK 且图 OK

  StoredNoImage --> StoredComplete: repair 或主流程\nprocess_image 成功

  StoredComplete --> Visible: is_post_visible
  StoredNoImage --> Hidden: 渲染过滤

  Visible --> [*]
  Hidden --> [*]
```

---

## 维护说明

| 变更类型 | 同步更新章节 |
|----------|----------------|
| 新模块 / import | 3、4 |
| 管线顺序或门禁 | 4、7、11 |
| CI / Docker | 2 |
| 前端交互 | 8 |
| 抓取 / R2 / 补图 | 5、6、9、10 |

与 PlantUML 版**择一维护**时，请保持两文档语义一致；或只维护一份并在另一份顶部注明「以 ×× 为准」。
