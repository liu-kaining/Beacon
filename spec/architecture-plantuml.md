# Beacon 架构与流程（PlantUML）

本文与 [blueprint.md](./blueprint.md) 互补：侧重**代码级**模块关系、流水线顺序、数据门禁与前端动线。图均基于当前仓库实现（`src/`、`templates/`、`.github/workflows/`、`Dockerfile`）。

**Mermaid 同构版**：[architecture-mermaid.md](./architecture-mermaid.md)（便于 GitHub / VS Code 直接预览）。

**如何渲染**：将下列 ` ```plantuml ` 代码块复制到支持 PlantUML 的编辑器（如 VS Code + PlantUML 插件）、或 [plantuml.com](https://www.plantuml.com/plantuml)、本地 `plantuml.jar` 生成 PNG/SVG。

---

## 1. 系统上下文（C4 风格）

外部参与者与 Beacon 的数据出入口。

```plantuml
@startuml beacon-context
!theme plain
skinparam shadowing false
skinparam rectangleStyle roundCorner

title Beacon — 系统上下文

actor "读者" as Reader
actor "维护者" as Maintainer

rectangle "Beacon\n(本仓库流水线 +\nGitHub Pages 静态站)" as Beacon #E8F4FF {
  usecase "浏览画报 / RSS" as UC1
  usecase "定时或手动跑管线" as UC2
}

cloud "Visual Capitalist\nRSS + 文章页 HTML" as VC #F5F5F5
cloud "OpenAI API\n(JSON Mode)" as OAI #F5F5F5
cloud "Cloudflare R2\n(S3 兼容)" as R2 #F5F5F5
cloud "GitHub Actions\n(Docker 跑 Python)" as GHA #F5F5F5
cloud "GitHub Pages\n(docs/)" as Pages #F5F5F5

Reader --> Pages : HTTPS\nindex.html / feed.xml
Maintainer --> GHA : push / schedule /\nworkflow_dispatch

GHA --> Beacon : checkout + docker run
Beacon --> VC : feedparser + requests\n抓取 RSS / 页面
Beacon --> OAI : ai_processor\ngenerate_analysis
Beacon --> R2 : boto3 put_object\n{article_id}.webp
Beacon --> Pages : commit data/*.json\ndocs/*.html docs/feed.xml

@enduml
```

---

## 2. 部署与仓库产物（CI / Docker）

与 `.github/workflows/beacon.yml`、`Dockerfile` 一致：默认镜像入口为 **`src/main.py`**；`data/`、`docs/` 通过卷挂载回仓库以便 `git-auto-commit`。

```plantuml
@startuml beacon-deploy
!theme plain
skinparam shadowing false

title Beacon — GitHub Actions 部署视图

node "GitHub Actions\nubuntu-latest" as Runner {
  artifact "repo workspace" as WS
  component "docker build\nbeacon-app" as Build
  component "docker run beacon-app\n(default: main.py)" as RunMain
  component "docker run …\nbackfill_images.py" as RunBackfill
  component "git-auto-commit-action" as Commit
}

database "Cloudflare R2" as R2
cloud "OpenAI" as OAI

WS --> Build
Build --> RunMain : env: OPENAI_*, R2_*\nvolume: data docs
RunMain --> OAI
RunMain --> R2
RunMain --> WS : 写回\nposts.json\nindex.html\nfeed.xml

WS --> RunBackfill : 仅 backfill workflow\n无 OPENAI
RunBackfill --> R2
RunBackfill --> WS

WS --> Commit : file_pattern\nbeacon: data + docs*

note right of RunMain
  **beacon.yml**
  cron: 每 3 小时
  CMD: uv run python src/main.py
end note

note right of RunBackfill
  **backfill-images.yml**
  手动触发
  可选再跑 render_site
  commit 不含 feed.xml（见 workflow）
end note

@enduml
```

---

## 3. Python 组件依赖（模块级）

`main.py` 为编排入口；`image_pick` 被 `scraper`、`main`（补图）、`backfill_images` 共用；`renderer` 提供 **`has_valid_ai_analysis` / `has_valid_hero_image` / `is_post_visible`** 供管线与渲染共用逻辑。

```plantuml
@startuml beacon-components
!theme plain
skinparam componentStyle rectangle
skinparam shadowing false

title Beacon — src 组件与依赖

package "编排" {
  [main.py] as Main
}

package "抓取与解析" {
  [scraper.py] as Scraper
  [image_pick.py] as ImgPick
}

package "媒体与存储" {
  [storage.py] as Storage
}

package "AI" {
  [ai_processor.py] as AI
}

package "静态输出" {
  [renderer.py] as Renderer
}

package "运维脚本" {
  [backfill_images.py] as Backfill
}

database "data/posts.json" as JSON
folder "templates/\nindex.jinja2" as Tpl
folder "docs/\nindex.html feed.xml" as Docs

Main --> Scraper
Main --> Storage
Main --> AI
Main --> ImgPick
Main --> Renderer
Main --> JSON

Scraper --> ImgPick
Scraper --> Scraper : feedparser\nBeautifulSoup

Backfill --> ImgPick
Backfill --> Storage
Backfill --> JSON

Renderer --> JSON
Renderer --> Tpl
Renderer --> Docs

AI --> AI : OpenAI client\njson_object

Storage --> Storage : requests 下载\nPillow 尺寸门槛\nWebP 上传 R2

note bottom of Renderer
  **可见性**
  is_post_visible =
  有效 AI 且非占位 core_insight
  且 r2_image_url 非空
end note

@enduml
```

---

## 4. 主管线时序（`main.main` 逐步）

严格对应代码顺序：**加载 JSON → 补主图 → 计算 existing_urls → RSS 分页拉新 → 逐条处理 → 去重 → 持久化门禁 → 渲染**。

```plantuml
@startuml beacon-main-sequence
!theme plain
autonumber

title Beacon — main.py 主流程（时序）

actor "CI / 本地" as Operator
participant "main.py" as Main
participant "posts.json" as JSON
participant "repair_missing\n_hero_images" as Repair
participant "Visual Capitalist\n(HTTP)" as VC
participant "image_pick" as Pick
participant "storage.process_image" as Img
participant "Cloudflare R2" as R2
participant "scraper.fetch_articles" as Fetch
participant "ai_processor.generate\n_analysis" as GenAI
participant "OpenAI API" as OAI
participant "renderer.render_site\nrender_rss" as Render

Operator -> Main : main()

Main -> JSON : load_existing_posts()
JSON --> Main : existing_posts[]

Main -> Repair : repair_missing_hero_images(existing_posts)
loop 每条 post：有效 AI 且无 r2_image_url
  Repair -> VC : GET original_url
  VC --> Repair : HTML
  Repair -> Pick : pick_best_image_url_from_html
  Pick --> Repair : best_image_url?
  Repair -> Img : process_image(url, id)
  Img -> VC : GET 图片
  Img -> Img : 宽高 >= 640×320?
  Img -> R2 : put {id}.webp
  Img --> Repair : r2_url, base64_blur
  note right of Repair : 就地修改 post 字典
end

Main -> Main : successful_posts = 非占位 AI\nfailed_urls = 占位 AI 的 URL\nexisting_urls = successful 的 URL 集合

Main -> Fetch : fetch_articles(existing_urls)
Fetch -> Fetch : feedparser 分页\nBEACON_MAX_PAGES
Fetch --> Main : articles[] (仅「新」或\n未在 existing_urls 的条目)

loop 每个 article
  Main -> Main : is_retry = url in failed_urls
  opt is_retry 且已有贴子
    Main -> Main : 复用已有 r2_image_url\n/base64_blur（若有）
  end
  opt 仍无图 且 article.image_url
    Main -> Img : process_image(image_url, id)
    Img --> Main : 或 None（过小/失败）
  end
  opt content_md 非空
    Main -> GenAI : generate_analysis(title, content_md)
    GenAI -> OAI : chat.completions\nresponse_format json_object
    OAI --> GenAI : JSON
    GenAI --> Main : ai_analysis 或 None
  end
  opt AI 失败
    Main -> Main : 写入占位 INVALID_AI_CORE_INSIGHT\n（仍进 new_posts；\nsave 时 publishable 剔除）
  end
  Main -> Main : new_posts.append(post)
end

Main -> Main : dedupe: new_posts + existing_posts\n按 original_url 保留首次

Main -> Main : publishable = 过滤 has_valid_ai_analysis

alt 有新帖 / 去重 / 磁盘曾有占位 / 本轮补过图
  Main -> JSON : save_posts(publishable)
end

Main -> Render : render_site()\nrender_rss()
Render -> JSON : 读取
Render -> Render : 仅 is_post_visible\n_enrich_post
Render --> Main : docs/index.html\nfeed.xml

Main --> Operator : Pipeline complete

@enduml
```

---

## 5. 文章级图片 URL 决策（`scraper._get_image_url`）

与 `scraper.py` 实现顺序一致。

```plantuml
@startuml beacon-image-url
!theme plain
title scraper._get_image_url — 决策顺序

start

:从 entry 取 content:encoded HTML;

if (pick_best_image_url_from_html(content)?) then (yes)
  :返回该 URL;
  stop
endif

:收集 media:content URLs;

if (pick_best_from_candidates(media_urls)?) then (yes)
  :返回;
  stop
endif

if (media_urls 非空?) then (yes)
  :返回第一个 media URL;
  stop
endif

:HTTP GET article 全文页;

if (pick_best_image_url_from_html(page HTML)?) then (yes)
  :返回;
  stop
endif

:返回 None;

stop

@enduml
```

---

## 6. `storage.process_image` 内部

```plantuml
@startuml beacon-process-image
!theme plain
title storage.process_image

start
:download_image(url)\n最多 3 次重试;

if (bytes?) then (no)
  :return None;
  stop
endif

:_decoded_image_meets_hero_minimum;
note right
  宽 >= 640 且 高 >= 320
  否则拒绝（防小图）
end note

if (通过?) then (no)
  :return None;
  stop
endif

:generate_blur_base64;
:upload_to_r2 → WebP\nkey = {article_id}.webp;

:return (public_url, blur_data_uri);

stop
@enduml
```

---

## 7. 帖子数据：持久化 vs 展示（两道门禁）

`posts.json` 可含「有 AI、暂无主图」的条目（补图或人工删字段后的状态）；**首页与 RSS** 仅展示 **`is_post_visible`**。占位分析 **`INVALID_AI_CORE_INSIGHT`** 不会写入 `publishable`。

```plantuml
@startuml beacon-gates
!theme plain
skinparam shadowing false

title 帖子：写入 posts.json vs 渲染可见

start

partition "持久化 save_posts" {
  :deduped_posts;
  if (has_valid_ai_analysis?) then (yes)
    :进入 publishable;
  else (no)
    :丢弃（占位 INVALID_AI_CORE_INSIGHT）;
  endif
}

partition "展示 render_site / render_rss" {
  :读取 posts.json;
  if (is_post_visible?\n有效 AI 且 r2 非空) then (yes)
    :_enrich_post\n模板与 RSS;
  else (no)
    :跳过该条;
  endif
}

stop

@enduml
```

---

## 8. 读者端动线（`templates/index.jinja2` + 内联 JS）

服务端已过滤 **`is_post_visible`**，嵌入的 `const posts = …` 仅含可见帖。动线为**纯前端**、无自有后端 API。

```plantuml
@startuml beacon-reader-journey
!theme plain
title 读者用户动线（静态页）

|读者|
start
:打开 GitHub Pages\n加载 index.html;

|浏览器|
:解析 Tailwind + 内联样式\nmasonry 多列布局;

:IntersectionObserver\n视口附近懒加载 R2 大图\n(base64_blur → data-src);

|读者|
:在搜索框输入关键字;

|浏览器|
:applyPostFilters()\n匹配 data-search\n(来自 search_text);

|读者|
:点击某张卡片;

|浏览器|
:openModal(index)\n从 posts[] 取同索引对象;

:侧滑抽屉：大图 + Core / Highlights /\nData tables / Deep dive /\nGlossary + 原文表折叠区;

|读者|
:点击抽屉内大图;

|浏览器|
:openLightbox 全屏;

|读者|
:按 Esc;

|浏览器|
:先关 lightbox\n再关 modal;

|读者|
:点击页头 RSS 链到 /feed.xml;

stop

@enduml
```

---

## 9. 数据流总览（端到端）

```plantuml
@startuml beacon-dataflow
!theme plain
skinparam rectangleStyle roundCorner
skinparam shadowing false

title Beacon — 端到端数据流（简化）

rectangle "Visual Capitalist\nRSS / HTML" as VC
rectangle "管线 Python" as Pipe {
  rectangle "tables_md 或 text\ncontent_md" as MD
  rectangle "image_url\n(启发式)" as IU
  rectangle "ai_analysis\nJSON" as AI
  rectangle "r2_image_url\nbase64_blur\nimage_version?" as IMG
}
database "data/posts.json" as JSON
cloud "R2 对象\n{id}.webp" as R2
folder "docs/index.html\n(+ posts JSON in JS)" as HTML
file "docs/feed.xml" as RSS

VC --> MD : scraper\nBeautifulSoup
VC --> IU : image_pick
VC --> IU : repair / page fetch

MD --> AI : ai_processor
IU --> IMG : storage\n下载 + 尺寸校验 + WebP

AI --> JSON
IMG --> JSON
IMG --> R2

JSON --> HTML : renderer +\njinja2 + enrich
JSON --> RSS : renderer\nmarkdown → description

HTML --> HTML : 客户端懒加载\n从 R2 拉图

@enduml
```

---

## 10. 独立工作流：批量换图（`backfill_images.py`）

与主管线分离：不写 OpenAI；可 `--dry-run`、`--limit`、`--no-feed`；成功时可能写入 `source_image_url`（主管线不依赖该字段）。

```plantuml
@startuml beacon-backfill
!theme plain
title backfill_images — 与 main 的差异

|backfill_images.py|
start
:load posts.json;

if (use_feed?) then (yes)
  :分页 RSS 建\noriginal_url → image_url 映射;
endif

repeat :下一篇 post;
  :解析 best_image_url\n(feed 或 GET 文章页 + pick);

  if (dry-run?) then (yes)
    :仅打印;
  else (no)
    if (_validate_image_url?) then (yes)
      :process_image → R2;
      :写回 post 字段\n+ image_version;
    endif
  endif
repeat while (还有帖子且未达 limit) is (yes)

:写回 posts.json;

|CI optional step|
:仅 render_site()\n（workflow 中）;

stop

@enduml
```

---

## 11. 单帖状态（概念模型）

非正式状态机，便于理解「为何 JSON 里有条但首页没有」。

```plantuml
@startuml beacon-post-state
!theme plain
hide empty description

title 单帖生命周期（概念）

[*] --> 管线处理中 : RSS 新条目

管线处理中 --> 有占位AI : generate_analysis 失败
有占位AI --> [*] : 不写入 posts.json\n下轮 RSS 再试

管线处理中 --> 已入库缺图 : save 成功但\n无 r2 / 或人工删图
已入库缺图 --> 已入库完整 : repair_missing_hero_images\n或主流程重跑成功 process_image

管线处理中 --> 已入库完整 : AI OK 且图 OK

已入库完整 --> 读者可见 : is_post_visible

已入库缺图 --> 读者不可见 : 渲染过滤

@enduml
```

---

## 维护说明

| 变更类型 | 请同步更新 |
|----------|------------|
| 新增模块 / 调整 import | 第 3、4 节 |
| 改管线顺序或门禁条件 | 第 4、7、11 节 |
| 改 CI / Docker CMD | 第 2 节 |
| 改前端交互 | 第 8 节 |
| 改抓取或 R2 逻辑 | 第 5、6、9、10 节 |

若 PlantUML 对中文参与者渲染异常，可在图首增加：`skinparam defaultFontName Microsoft YaHei`（或本机已装中文字体名）。
