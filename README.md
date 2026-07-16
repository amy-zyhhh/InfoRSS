# InfoRSS 使用与维护说明

InfoRSS 用于抓取清华大学信息门户 RSS，将通知保存到本地数据库，再通过 AI 整理成 Markdown，并用 Jekyll 构建为可搜索、可筛选的静态网页。

当前流程：

```text
RSS 订阅
  -> 本地 SQLite 去重保存
  -> 原始 Markdown 留档
  -> 公开原文页面生成
  -> AI 增量整理
  -> 搜索索引生成
  -> Jekyll 静态网页
```

## 目录结构

```text
.
├─ scripts/
│  ├─ run_all.py              # 一键运行完整流程
│  ├─ fetch_rss.py            # 抓取 RSS 并写入数据库
│  ├─ list_items.py           # 查看数据库中的通知
│  ├─ export_md.py            # 导出原始 Markdown
│  ├─ export_public_raw.py    # 导出公开展示的已抓取原文页面
│  ├─ export_brief_json.py    # 从摘要 Markdown 导出结构化 JSON
│  ├─ process_ai.py           # AI 增量整理
│  ├─ build_search_index.py   # 生成网页搜索索引
│  └─ check_site.py           # 检查公开页面数据一致性
├─ data/
│  ├─ rss.sqlite3             # 本地 SQLite 数据库
│  └─ raw/                    # RSS 原始 XML 快照
├─ content/
│  ├─ daily/                  # 原始 Markdown 留档
│  ├─ briefs/                 # AI 整理后的 Markdown
│  └─ raw/                    # 公开展示的已抓取原文页面
├─ assets/
│  ├─ css/main.css            # 网页样式
│  ├─ js/search.js            # 前端搜索与筛选
│  ├─ js/brief-raw-links.js   # 首页和摘要详情页的已抓取原文入口
│  ├─ js/toc.js               # 首页分类目录
│  ├─ search-index.json       # 轻量搜索索引
│  └─ raw-search-index.json   # 已抓取原文全文索引
├─ _layouts/                  # Jekyll 页面模板
├─ .github/workflows/
│  └─ daily.yml               # GitHub Actions 每日自动更新
├─ _config.yml                # Jekyll 配置
├─ Gemfile                    # Jekyll 依赖
├─ .env                       # 本地私密配置，不提交
└─ .gitignore
```

## 环境配置

需要：

- Python 3.10 或更新版本
- Ruby
- Bundler
- Jekyll 依赖，通过 `bundle install` 安装

安装 Jekyll 依赖：

```powershell
bundle install
```

如果 Windows 上遇到 `tzinfo` 报错，项目的 `Gemfile` 已经包含：

```ruby
gem "tzinfo", "~> 2.0"
gem "tzinfo-data", "~> 1.2026"
```

重新运行 `bundle install` 即可。

## `.env` 配置

`.env` 保存 RSS 地址和 AI 接口配置，已经被 `.gitignore` 忽略，不应提交到 GitHub。

示例：

```env
INFORS_RSS_URL=https://inforss.aajax.top:3443/rss?token=你的token
OPENAI_API_KEY=你的API密钥
OPENAI_BASE_URL=https://llmapi.paratera.com/v1
OPENAI_MODEL=DeepSeek-V3.2-Thinking
```

注意：

- 不要把 `.env` 上传到公开仓库。
- RSS URL 中的 `token` 属于敏感信息。
- GitHub Actions 中应改用 Repository Secrets。
- 本地运行时，RSS 地址固定从 `.env` 的 `INFORS_RSS_URL` 读取；命令行仍可用 `--url` 临时覆盖。

## 时间格式

所有主要脚本统一使用紧凑日期格式：

```text
YYYYMMDD
```

处理一天：

```powershell
python scripts/run_all.py 20260713
```

处理日期范围：

```powershell
python scripts/run_all.py 20260712-20260713
```

不输入日期时，`run_all.py` 和 `fetch_rss.py` 默认处理“前一天”。

例如在 `2026-07-14` 运行：

```powershell
python scripts/run_all.py
```

等价于：

```powershell
python scripts/run_all.py 20260713
```

## 一键运行完整流程

日常最常用命令：

```powershell
python scripts/run_all.py 20260713
```

它会依次执行：

1. 抓取 RSS
2. 保存新增通知到数据库
3. 导出原始 Markdown
4. 导出公开展示的已抓取原文页面
5. 调用 AI 生成整理版 Markdown
6. 导出结构化 JSON
7. 生成轻量搜索索引和全文索引
8. 检查生成结果一致性

输出文件：

```text
content/daily/20260713.md
content/raw/items/
content/raw/daily/20260713.md
content/briefs/20260713.md
content/briefs/20260713.json
assets/search-index.json
assets/raw-search-index.json
```

跳过某些步骤：

```powershell
python scripts/run_all.py 20260713 --skip-fetch
python scripts/run_all.py 20260713 --skip-ai
python scripts/run_all.py 20260713 --skip-public-raw
python scripts/run_all.py 20260713 --skip-json
python scripts/run_all.py 20260713 --skip-check
python scripts/run_all.py 20260713 --skip-fetch --skip-raw-md --skip-public-raw --skip-ai
```

## 单独运行各步骤

### 1. 抓取 RSS

```powershell
python scripts/fetch_rss.py 20260713
```

功能：

- 下载 RSS XML
- 保存原始快照到 `data/raw/`
- 解析 RSS 条目
- 按发布时间筛选
- 写入 `data/rss.sqlite3`
- 对重复内容跳过

RSS 快照路径按“抓取时间”保存，不是通知发布时间。例如：

```text
data/raw/2026/07/14/081706_xxxxxxxxxxxx.xml
```

### 2. 查看已抓取通知

```powershell
python scripts/list_items.py 20260713
```

显示：

- 标题
- 发布时间
- 原文链接
- 唯一标记
- 本地 ID

显示摘要：

```powershell
python scripts/list_items.py 20260713 --summary
```

### 3. 导出原始 Markdown

```powershell
python scripts/export_md.py 20260713
```

输出：

```text
content/daily/20260713.md
```

这是原始留档，尽量保留通知正文，不做 AI 改写。

### 4. 导出公开原文页面

```powershell
python scripts/export_public_raw.py 20260713
```

输出：

```text
content/raw/items/
content/raw/daily/20260713.md
```

这一步会把数据库中已经抓取到的原始正文导出成可被 Jekyll 展示的页面：

- `content/raw/items/`：每条通知一个原文页面，链接由原文 URL 哈希生成，重复运行不会重复创建。
- `content/raw/daily/`：按日期生成当天原文目录页，主要用于留档和直接查看。

这些页面展示的是“已抓取到的正文内容”，不是重新访问原网页。首页、搜索页和每日摘要详情页的每条通知会展示“已抓取的原文”入口；归档列表不直接展示该入口。

首页展示的是最新一个摘要文件的内容，但首页路径本身不是摘要文件路径。为保证首页也能匹配到正确的原文链接，`index.html` 会把当前展示的摘要地址写入 `window.INFO_RSS_CURRENT_BRIEF_URL`，再由 `assets/js/brief-raw-links.js` 根据搜索索引补上“已抓取的原文”入口。

GitHub Pages 项目站点 URL 中包含仓库名前缀，例如 `/InfoRSS/`。`brief-raw-links.js` 会在比较摘要路径前去掉这个前缀，避免线上把 `/InfoRSS/content/...` 和索引里的 `/content/...` 当成两个不同地址。

### 5. AI 整理

```powershell
python scripts/process_ai.py 20260713
```

输出：

```text
content/briefs/20260713.md
content/briefs/20260713.json
```

AI 会为每条通知生成：

- 类别
- 适用对象
- 关键词
- 摘要
- 标题原文链接

`process_ai.py` 会同时生成 Markdown 和结构化 JSON。Markdown 用于 Jekyll 页面展示，JSON 用于后续程序化维护、检查或扩展页面功能，避免所有逻辑都依赖 Markdown 文本解析。

如果某条通知无法被 AI 正常分析，脚本不会丢弃这条通知，也不会中断整批流程。该条会降级保留到整理版 Markdown 中：

- 分类显示为 `未分析`
- 适用对象、关键词显示为 `未分析`
- 摘要位置使用原始正文或原始摘要的前一段内容
- 标题仍然链接到原文

失败详情会写入：

```text
data/ai_failures/
```

如果想限制每条通知传给 AI 的最大字符数：

```powershell
python scripts/process_ai.py 20260713 --max-chars 6000
```

强制重新处理已缓存的 AI 结果：

```powershell
python scripts/process_ai.py 20260713 --force
```

整理版 Markdown 中，每条通知的标题会直接链接到原文，例如：

```md
### [通知标题](https://info.tsinghua.edu.cn/...)
```

因此页面中不会再单独显示一行“原文链接”。搜索索引会从标题链接中提取原网页地址，并根据该地址匹配 `content/raw/items/` 中的已抓取原文页面。

### 6. 导出结构化 JSON

如果只修改了已有摘要 Markdown，或者需要为历史摘要补 JSON，可以运行：

```powershell
python scripts/export_brief_json.py
```

只处理某一天：

```powershell
python scripts/export_brief_json.py 20260713
```

输出：

```text
content/briefs/20260713.json
```

### 7. 生成搜索索引

```powershell
python scripts/build_search_index.py
```

输出：

```text
assets/search-index.json
assets/raw-search-index.json
```

搜索页的搜索和筛选依赖这两个文件：

- `assets/search-index.json`：轻量索引，包含标题、类别、适用对象、关键词、摘要、原网页地址、已抓取原文页地址等字段。
- `assets/raw-search-index.json`：全文索引，只保存已抓取原文全文，体积较大。

默认搜索只加载轻量索引；只有勾选“全文”后，浏览器才会额外加载 `raw-search-index.json`。这样数据增多后，普通搜索页面仍能较快打开。

### 8. 检查生成结果

```powershell
python scripts/check_site.py
```

检查内容包括：

- 搜索索引格式是否正确
- `raw_url` 指向的公开原文页面是否存在
- 全文索引是否包含对应条目
- 摘要 Markdown 的 `items_count` 是否等于实际通知数量
- 每个摘要 Markdown 是否有对应 JSON
- 是否误提交 `.env`、`data/`、`content/daily/` 或 SQLite 文件

## 增量保存与重复检测

项目已经按“增量保存”设计。

### RSS 抓取阶段

每条通知有唯一标记：

```text
规范化 URL -> guid -> 标题 + 发布时间
```

优先使用原文详情页 URL，例如：

```text
https://info.tsinghua.edu.cn/f/info/xxfb_fg/xnzx/template/detail?xxid=...
```

入库时：

- 新条目立即保存
- 已存在且内容没变则跳过
- 已存在但内容变化则更新
- 原始 RSS 快照按内容哈希去重

### AI 处理阶段

AI 结果存入数据库表：

```text
ai_item_briefs
```

判断是否重复的依据：

- 通知 ID
- 原文内容哈希
- AI 模型名称

如果三者都相同，则跳过 AI 调用。

这避免了重复消耗 API 额度。

如果 AI 返回空内容或非 JSON 内容，单条通知会被记录为失败，并在整理版 Markdown 中以 `未分析` 分类保留原文片段。默认情况下流程会继续处理后续通知；如果希望遇到单条失败就停止，可以使用：

```powershell
python scripts/process_ai.py 20260713 --stop-on-error
```

在默认模式下，单条 AI 失败属于降级处理，不会让每日自动任务整体失败。

### Markdown 与搜索索引阶段

导出文件前会和已有文件比较：

- 内容没变则跳过写入
- 生成时间变化不会导致重复覆盖
- 结构化 JSON 没变会跳过写入
- 轻量搜索索引和全文索引没变也会跳过写入

## 本地预览 Jekyll 网站

启动：

```powershell
bundle exec jekyll serve
```

打开：

```text
http://127.0.0.1:4000
```

构建静态文件：

```powershell
bundle exec jekyll build
```

生成目录：

```text
_site/
```

## 网页功能

首页只展示最新一天的当日信息，并在页面顶部提供固定分类目录。目录会根据当天实际出现的分类自动生成，例如：

```text
科研 / 教务 / 招聘 / 讲座活动
```

下滑页面时，分类目录会固定在顶部，点击分类可以跳转到对应内容。

如果当天通知数量超过阈值，首页会显示提示。阈值在 `_config.yml` 中配置：

```yaml
notice_alert_threshold: 90
```

当前阈值为 `90`，后续可以按需要改成其他数量。

右上角菜单包含：

```text
首页 / 搜索 / 归档
```

归档页支持按日期筛选：

- 只选择年份：查看某一年的所有归档
- 只选择月份：查看所有年份中某个月的归档
- 只选择日期：查看所有月份中某一天的归档
- 组合选择年、月、日：精确筛选某一天或某个月

搜索页支持：

- 关键词搜索
- 勾选“全文”后搜索已抓取原文全文
- 类别筛选
- 适用对象筛选
- 开始日期筛选
- 结束日期筛选
- 一键重置
- 每条结果打开“已抓取的原文”

默认情况下，搜索只匹配标题、类别、适用对象、关键词和摘要；勾选“全文”后，会把 `content/raw/items/` 中对应条目的全文也纳入检索。这个开关只显示一个小复选框，页面上不会再额外显示“搜索已抓取原文”文字。

如果某个关键词只出现在已抓取原文中，而没有出现在标题、关键词或摘要里，搜索结果会显示“命中：已抓取原文”，便于区分命中来源。

首页和每日摘要详情页都支持在每条通知后打开“已抓取的原文”。这个入口依赖 `assets/search-index.json` 中的 `raw_url` 字段；如果某天没有先生成 `content/raw/items/`，入口不会显示。摘要正文不再重复显示“清华大学信息门户通知整理”和“某日发布”这类标题；这些信息已经由页面顶部标题和日期承担。

搜索数据来自：

```text
assets/search-index.json
assets/raw-search-index.json
```

如果修改了 `content/briefs/*.md`，请重新运行：

```powershell
python scripts/export_brief_json.py
python scripts/build_search_index.py
python scripts/check_site.py
```

页面引用 CSS 和 JS 时会自动带上构建时间版本号，推送到 GitHub Pages 后可以减少浏览器继续使用旧样式或旧脚本的问题。

## GitHub Pages 发布建议

项目已经包含 GitHub Actions 工作流：

```text
.github/workflows/daily.yml
```

它会在每天北京时间凌晨 3 点自动运行一次。GitHub Actions 的 cron 使用 UTC，所以配置为：

```yaml
cron: "0 19 * * *"
```

也就是 UTC 19:00，对应北京时间次日 03:00。

推荐提交这些内容：

```text
.github/workflows/daily.yml
_config.yml
Gemfile
Gemfile.lock
index.html
archive.html
_layouts/
assets/
content/briefs/
README.md
scripts/
```

不建议提交：

```text
.env
data/
content/daily/
_site/
.jekyll-cache/
```

当前 `.gitignore` 已忽略 `.env`、`data/`、`_site/` 等本地文件。

如果 `content/daily/` 曾经被提交过，`.gitignore` 不会自动把它从仓库里移除。需要运行：

```powershell
git rm --cached -r content/daily
git add .gitignore _config.yml
git commit -m "Stop tracking raw daily exports"
git push
```

这个命令只会取消 Git 追踪，不会删除本地 `content/daily/` 文件。

如果希望 GitHub Pages 展示 AI 整理结果，需要提交：

```text
content/briefs/
content/raw/
assets/search-index.json
```

### 1. 在 GitHub 新建仓库

在 GitHub 创建一个新仓库，例如：

```text
InfoRSS
```

建议先创建空仓库，不要勾选自动生成 README，避免和本地文件冲突。

### 2. 本地初始化 Git

如果当前目录还不是 Git 仓库，在项目目录运行：

```powershell
git init
git add .
git commit -m "Initial InfoRSS site"
```

然后关联远程仓库。把下面的地址替换成你自己的仓库地址：

```powershell
git branch -M main
git remote add origin https://github.com/你的用户名/InfoRSS.git
git push -u origin main
```

### 3. 配置 GitHub Secrets

进入仓库页面：

```text
Settings -> Secrets and variables -> Actions -> New repository secret
```

添加这些 Secrets：

```text
INFORS_RSS_URL
OPENAI_API_KEY
OPENAI_BASE_URL
OPENAI_MODEL
```

这些值对应本地 `.env` 中的配置。不要把 `.env` 上传到 GitHub。

### 4. 启用 GitHub Pages

进入：

```text
Settings -> Pages
```

推荐选择：

```text
Build and deployment: Deploy from a branch
Branch: main
Folder: / (root)
```

保存后，GitHub Pages 会用仓库里的 Jekyll 文件构建网站。

注意：GitHub Pages 默认使用的 Jekyll 版本可能比较旧。项目已经避免使用容易触发旧版 Liquid 类型比较错误的写法：

- `date_range` 在 Markdown front matter 中写成字符串，例如 `date_range: "20260715"`
- 首页和归档页按文件路径排序，不直接按 `date_range` 排序
- `_config.yml` 排除了 `content/daily`

如果 GitHub Pages 构建日志出现 `comparison of Array with Array failed`，通常是旧文件或原始留档仍被构建。优先检查：

```powershell
git ls-files content/daily
```

如果有输出，运行：

```powershell
git rm --cached -r content/daily
git commit -m "Remove raw daily exports from Pages build"
git push
```

### 5. 验证自动运行

进入：

```text
Actions -> Daily InfoRSS Update
```

可以手动点击：

```text
Run workflow
```

手动运行一次，确认流程能成功：

```text
抓取 RSS -> 导出公开原文页 -> AI 整理 -> 导出结构化 JSON -> 生成搜索索引 -> 检查站点数据 -> 构建 Jekyll -> 自动 commit
```

工作流会在提交生成内容前运行：

```text
python scripts/check_site.py
bundle exec jekyll build
```

如果生成的数据互相不一致，或者 Jekyll 无法构建，自动任务会失败并保留错误日志，避免把明显损坏的内容继续提交。

以后它会每天北京时间凌晨 3 点自动运行。

### 6. 推送后的页面检查

推送到 GitHub 后，等待 `Actions -> pages-build-deployment` 成功，再检查线上页面：

- 首页每条通知下方应显示“已抓取的原文”
- 搜索页每条结果应显示“已抓取的原文”，标题仍然跳转原网页
- 搜索页“全文”复选框应是小方框，旁边不显示“搜索已抓取原文”
- 搜索页日期筛选应是“开始日期”和“结束日期”两个独立选项
- 每日摘要详情页不应再显示正文里的“清华大学信息门户通知整理 / 某日发布”

页面引用 CSS 和 JS 时会带上构建时间版本号。如果线上看起来还是旧样式，通常是 GitHub Pages 还没完成构建，或浏览器页面没有刷新到新 HTML。

### 7. 自动提交内容

工作流只会提交公开展示需要的内容：

```text
content/briefs/
content/raw/
assets/search-index.json
assets/raw-search-index.json
```

不会提交：

```text
.env
data/
content/daily/
```

这样可以避免把 RSS token、本地数据库和原始抓取快照暴露到公开仓库。

## 日常维护流程

建议每天运行：

```powershell
python scripts/run_all.py
```

然后本地预览：

```powershell
bundle exec jekyll serve
```

确认没有问题后提交：

```powershell
git add .
git commit -m "Update daily info brief"
git push
```

如果某一天已经有 AI 摘要，但后来才重新抓取到这一天的原文，可以只补公开原文页和搜索索引：

```powershell
python scripts/export_public_raw.py 20260715
python scripts/export_brief_json.py 20260715
python scripts/build_search_index.py
python scripts/check_site.py
```

这样会让首页、搜索页和每日摘要详情页重新获得“已抓取的原文”入口，并让“全文”搜索可以检索到新增的原文内容。

## 常见问题

### RSS 只返回 100 条

如果运行结果显示：

```text
Parsed items: 100
```

说明当前 RSS 源只返回最近 100 条。更早内容如果没有提前抓取，可能无法仅靠 RSS 补回。

解决方式：

- 定时运行脚本，持续积累本地数据库
- 如果服务端支持分页或时间参数，再扩展抓取脚本
- 另写网页历史补档脚本

### PowerShell 显示中文乱码

文件本身是 UTF-8。PowerShell 预览时请使用：

```powershell
Get-Content content/briefs/20260713.md -Encoding UTF8
```

### Jekyll 报 `tzinfo`

重新安装依赖：

```powershell
bundle install
```

然后：

```powershell
bundle exec jekyll serve
```

### AI 结果没有更新

默认会跳过重复内容。如果想强制重跑：

```powershell
python scripts/process_ai.py 20260713 --force
```

### 搜索页没有新内容

重新生成索引：

```powershell
python scripts/build_search_index.py
```

## 后续开发建议

可以继续增强：

- GitHub Actions 自动定时运行
- 更细粒度的分类体系
- 关键词页
- RSS 历史补档
- 增加失败重试和日志文件

当前项目的核心原则：

- 原始数据先保存
- 每条通知独立去重
- AI 处理增量执行
- 可重复运行
- 私密 token 不入仓库
