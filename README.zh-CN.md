# llmsrt

[English](README.md) | **简体中文**

用于 Linux 的 Python 视频字幕提取与大模型翻译脚本。支持指定视频文件或目录，默认扫描当前目录；默认生成**一份简体中文在上、英文在下的 SRT**，不按语言拆成多个文件。

## 字幕获取方式与成本

| 视频中的字幕情况 | 处理方式 | 成本与限制 |
| --- | --- | --- |
| MKV 内嵌 SRT、ASS、SSA 等文本字幕 | FFprobe 找到轨道，FFmpeg 转为 SRT | 无需识别模型，通常最快；ASS 样式、定位和字体不会保留 |
| 无法提取文本字幕，但已有同名外挂字幕 | 读取同目录 SRT、ASS、SSA、VTT | 无需语音识别，外挂字幕需与视频版本匹配 |
| 只有 PGS、VobSub 等图片字幕 | 默认提示提供文本字幕；可先用外部 OCR 转成 SRT，或显式开启语音识别 | FFmpeg 可导出图片字幕流，不能直接把图片转成文字；项目未集成 OCR |
| 无字幕轨，或字幕烧录在画面中 | 默认提示提供文本字幕；安装可选依赖并加 `--asr` 后才使用 faster-whisper | 无语音识别 API 费用，消耗本机 CPU/GPU；只能识别对白，不能还原画面上的文字 |

字幕获取依据 [FFmpeg 官方文档](https://ffmpeg.org/ffmpeg.html) 和 [编解码器文档](https://ffmpeg.org/ffmpeg-codecs.html)。语音识别默认关闭。显式开启后的后备识别使用 [faster-whisper](https://github.com/SYSTRAN/faster-whisper)，预设为 CPU、`base` 模型、`int8` 精度，首次需要下载模型。

**翻译使用配置的大模型 API**，支持 OpenAI、智谱 GLM、DeepSeek，也支持通过 `--base-url` 指向兼容的网关或自建服务。字幕文本、作品背景和少量上下文会发送给所选 API；视频和音频由本机处理，不发送给翻译 API。翻译费用、可用模型和限速以服务商及账户配置为准。默认先从 IMDb、豆瓣公开资料获取作品信息；IMDb 直接读取搜索页和作品详情页，无需影片 API 或 AWS 凭证。资料查询不到时，再把文件名交给翻译模型作为作品线索。

## Linux 用户级安装与 PATH

需要 Python 3.10 或更新版本，以及 PATH 中的 `ffmpeg`、`ffprobe`。以下命令在目标 Debian / Ubuntu 环境执行：

```bash
sudo apt-get update
sudo apt-get install -y ffmpeg python3 python3-pip

cd /path/to/llmsrt
python3 -m pip install --user .
```

也可以不克隆源码，pip 和 pipx 直接从 GitHub 仓库安装：

```bash
python3 -m pip install --user "llmsrt @ git+https://github.com/ivershuo/llmsrt.git"
# 带语音识别可选依赖：
python3 -m pip install --user "llmsrt[asr] @ git+https://github.com/ivershuo/llmsrt.git"
# 或用 pipx 安装为独立工具：
pipx install git+https://github.com/ivershuo/llmsrt.git
```

从 Git 安装需要 PATH 中有 `git`，包在本机现场构建；依赖仍从 PyPI 下载。在 URL 后加 `@v0.1.0` 可固定某个发布标签；升级时同一命令加 `--upgrade` 重新执行即可。

pip 将程序和依赖装到当前用户的 Python 安装目录，自动生成 `llmsrt` 命令。**不创建运行用的虚拟环境，不需要每次 SSH 后执行 `source activate`。** Python 依赖会与这个用户的其他 Python 项目共享。如果当前仍激活着旧 `.venv`，先执行一次 `deactivate`；也可以通过 `/usr/bin/python3 -m pip install --user .` 指定解释器。

Linux 的默认命令目录通常是 `~/.local/bin`。若它不在 PATH 中，在当前终端执行：

```bash
export PATH="$HOME/.local/bin:$PATH"
```

并把这行加入 SSH 登录时加载的 shell 配置，只需设置一次。Bash 登录通常读取 `~/.profile`；如果存在 `~/.bash_profile`，放入该文件。Zsh 可放入 `~/.zshrc`。自定义了 `PYTHONUSERBASE` 时，将其中的 `bin` 目录加入 PATH。

之后在任意影视目录使用：

```bash
cd /data/movies/Interstellar
llmsrt                         # 默认处理当前目录中的视频
llmsrt 'Interstellar.mkv'      # 只处理这个视频
llmsrt --recursive            # 包括子目录
llmsrt --targets en,zh-cn      # 合并输出，英文在上
```

命令始终以调用时的当前目录寻找视频、解析相对路径和写入默认输出，不会切回项目源码目录。程序安装完成后不依赖源码目录的位置；修改源码后，回到项目目录执行 `python3 -m pip install --user --upgrade .` 更新已安装的命令。可用 `python3 -m pip uninstall llmsrt` 卸载用户级安装。

如果 pip 报 `externally-managed-environment`，说明发行版限制了系统 Python 的安装，`--user` 也可能受限。此时可用下面的 pipx 方式；pipx 内部维护独立环境，但日常运行同样只需 `llmsrt`，不需要创建、激活或管理 `.venv`。参见 [Python 安装规范](https://packaging.python.org/en/latest/specifications/externally-managed-environments/) 和 [pipx 安装说明](https://pipx.pypa.io/stable/how-to/install-pipx.html)。

```bash
sudo apt-get install -y pipx
cd /path/to/llmsrt
pipx install .
pipx ensurepath
# 按 ensurepath 的提示重新登录 SSH，让 PATH 生效；然后直接运行 llmsrt
```

使用 pipx 安装后，源码更新可执行 `pipx install --force /path/to/llmsrt`；卸载用 `pipx uninstall llmsrt`。选择用户级 pip 或 pipx 中的一种安装方式即可。

大模型请求使用 Python 标准库 `urllib`，不用安装三个不同的 SDK。默认只处理内嵌和外挂文本字幕，不需要 GPU、faster-whisper 或识别模型，也不会自动下载识别模型。没有可用文本字幕时，该视频报告错误；目录批处理继续处理其他视频。

需要语音识别后备方案时，在目标 Linux 环境安装可选依赖，再显式开启：

```bash
# 回到源码目录，用户级安装额外依赖
python3 -m pip install --user '.[asr]'
# 如果使用 pipx 安装，改用：pipx inject llmsrt 'faster-whisper>=1.1,<2'
llmsrt /data/movie.mkv --asr
```

`--asr` 仅在找不到可用文本字幕时使用语音识别。`--asr-model`、`--audio-stream` 等识别参数不会自动开启识别；`--no-asr` 仍可显式关闭。

按需求，开发期间**没有在当前环境执行脚本、安装依赖、发起 API 请求或运行测试验证**；实际运行情况需在目标 Linux 环境确认。

### 在不同目录共用配置

程序自动读取 `~/.config/llmsrt/config.json`。如果设置了 `XDG_CONFIG_HOME`，则读取 `$XDG_CONFIG_HOME/llmsrt/config.json`。可以在源码目录执行一次：

```bash
mkdir -p "${XDG_CONFIG_HOME:-$HOME/.config}/llmsrt"
# 仅在尚未创建自己的配置时复制，避免覆盖现有设置
cp -n config.example.json "${XDG_CONFIG_HOME:-$HOME/.config}/llmsrt/config.json"
```

编辑该配置，选择翻译服务与模型；示例预设 OpenAI（默认），也可改为 GLM 或 DeepSeek。密钥继续从配置中的 `api_key_env` 对应环境变量读取，可以在 SSH 登录时加载的 shell 配置中设置 `export OPENAI_API_KEY='你的密钥'` 等。之后在不同影视目录直接运行 `llmsrt`，无需反复传 `--config` 或服务商参数。共用配置适合保存服务商、模型和批次参数；混合影视目录不要在其中固定某一作品的名称或 ID。

配置文件选择顺序为 `--config 路径` → `LLMSRT_CONFIG` 环境变量指定的路径 → 用户配置目录。只加载选中的一份文件，不合并多份配置；显式指定的配置不存在或无效时会报错。命令行参数仍优先于文件中的设置。

仍然可以从源码目录使用 `python3 llmsrt.py`，无需安装命令；这种方式需要先用同一个 Python 安装 `requirements.txt` 中的依赖。

## 配置翻译服务

密钥从环境变量读取，不保存在项目代码、示例配置或翻译缓存中。

| `--provider` | 默认模型 | 默认 API 基础地址 | 默认密钥环境变量 |
| --- | --- | --- | --- |
| `openai`（默认） | `gpt-6-luna` | `https://api.openai.com/v1` | `OPENAI_API_KEY` |
| `glm` | `glm-5.3-flash` | `https://open.bigmodel.cn/api/paas/v4` | `GLM_API_KEY` |
| `deepseek` | `deepseek-flash` | `https://api.deepseek.com` | `DEEPSEEK_API_KEY` |

这些是脚本的预设值，不会自动追踪服务商最新模型；可用 `--model` 替换为账户支持的模型。接口依据 [OpenAI 官方文档](https://developers.openai.com/api/docs/guides/structured-outputs)、[GLM 的 OpenAI 兼容文档](https://docs.bigmodel.cn/cn/guide/develop/openai/introduction) 和 [DeepSeek 官方文档](https://api-docs.deepseek.com/)。

```bash
# OpenAI；默认服务商，也可显式指定 --provider openai
export OPENAI_API_KEY='替换为你的密钥'
python llmsrt.py /data/movie.mkv --model gpt-6-luna

# GLM；这里使用智谱通用 API 端点
export GLM_API_KEY='替换为你的密钥'
python llmsrt.py /data/movie.mkv --provider glm --model glm-5.3-flash

# DeepSeek
export DEEPSEEK_API_KEY='替换为你的密钥'
python llmsrt.py /data/movie.mkv --provider deepseek --model deepseek-flash

# 自定义 API 基础地址和密钥变量名；地址不含 /chat/completions
export MY_LLM_KEY='替换为你的密钥'
python llmsrt.py /data/movie.mkv --provider openai \
  --base-url https://your-gateway.example/v1 \
  --api-key-env MY_LLM_KEY --model your-model
```

服务商预设使用通用推理 API。GLM 编码套餐的端点及使用范围与通用 API 有区别，配置时按所用服务的官方说明选择地址；不要直接假设套餐支持该字幕翻译用途。

也可使用 JSON 配置文件，示例见 `config.example.json`：

```bash
cp config.example.json config.local.json
# 按需要修改 config.local.json，然后运行
python llmsrt.py /data/movie.mkv --config config.local.json

# 命令行可以覆盖配置中的模型或批次大小
python llmsrt.py /data/movie.mkv --config config.local.json \
  --model deepseek-v4-pro --batch-size 10
```

配置优先级：**命令行 > 选中的配置文件 > LLMSRT 环境变量 > 脚本预设**。环境变量支持 `LLMSRT_PROVIDER`、`LLMSRT_MODEL`、`LLMSRT_BASE_URL`、`LLMSRT_API_KEY_ENV`；`LLMSRT_CONFIG` 用于指定配置文件路径。未显式指定配置文件时，自动读取用户配置目录的 `llmsrt/config.json`。`config.local.json` 已加入 Git 忽略；示例中只有密钥环境变量名称，不含实际密钥。

配置文件接受这些翻译选项：`provider`、`model`、`base_url`、`api_key_env`、`batch_size`、`batch_chars`、`context_cues`、`temperature`、`max_tokens`、`timeout`、`retries`、`request_interval`、`json_mode`、`extra_body`。也可配置作品背景和进度：`title`、`media_type`、`year`、`season`、`episode`、`media_context`、`media_context_file`、`characters`、`progress`、`progress_interval`，以及影片信息获取：`metadata`、`metadata_sources`、`imdb`、`douban`、`metadata_timeout`、`metadata_cache_days`、`metadata_refresh`。视频路径、源语言、目标语言及识别选项使用命令行配置。

## 从 IMDb、豆瓣获取影片资料

默认开启影片资料获取，名称搜索默认按 `imdb,douban` 的顺序进行。未指定作品名时，根据视频文件名清理出的名称、年份和季集搜索这两个来源；指定 ID 或链接的来源会优先处理。豆瓣详情中包含 IMDb ID 时，可以直接查询对应 IMDb 作品，减少同名误匹配。获取到的资料每批都作为 `catalog_metadata` 随翻译请求发送，并保留来源 URL；两站都没找到可信资料时，才让模型根据原始视频文件名理解作品，不额外调用大模型生成一份可能失实的剧情。

IMDb 统一直接读取公开网页，无需申请 API 或安装 AWS SDK。指定 IMDb ID/链接时直接读取作品详情页；没有 ID 时先读取 IMDb 搜索页、筛选作品，再读取详情页。豆瓣使用公开搜索建议和详情页。请求之间至少间隔 1 秒，配合资料缓存，目录内同一作品不需要逐集重复抓取。

旧版本配置中的 `imdb_backend`、`omdb_api_key_env`、`imdb_api_key_env`、`imdb_data_set_id`、`imdb_revision_id`、`imdb_asset_id`、`imdb_region` 已移除，使用旧配置时请删除这些字段。运行命令也不再需要 `--imdb-backend web`，可直接使用默认行为。IMDb ID 和作品链接参数继续支持。

```bash
# 根据明确的名称和年份自动查找
python llmsrt.py /data/Interstellar.2014.1080p.mkv \
  --title 'Interstellar' --year 2014

# 直接指定 IMDb ID（也支持 --imdb、--imdb-url）
python llmsrt.py /data/movie.mkv --imdb-id tt0816692

# 直接指定豆瓣作品链接（也支持 --douban、--douban-id）
python llmsrt.py /data/movie.mkv \
  --douban-url 'https://movie.douban.com/subject/1889243/'

# 两个 ID 指向同一作品，读取中英文资料
python llmsrt.py /data/movie.mkv \
  --imdb-id tt0816692 --douban-id 1889243

# 电视剧：明确季数以区分豆瓣中的各季条目
python llmsrt.py /data/Breaking.Bad.S01E01.mkv \
  --title 'Breaking Bad' --media-type tv --season 1 --episode 1

# 默认使用 IMDb 网页和豆瓣公开资料，无需影片 API 密钥
python llmsrt.py /data/movie.mkv

# 只查询 IMDb；使用 10 秒请求超时
python llmsrt.py /data/movie.mkv --metadata-sources imdb --metadata-timeout 10

# 重新获取资料；替换已有字幕需要同时加 --overwrite
python llmsrt.py /data/movie.mkv --metadata-refresh --overwrite

# 禁用外部资料查询，保留手动背景
python llmsrt.py /data/movie.mkv --no-metadata --title '作品名称'
```

可获取的内容包括作品名、年份、简介、类型、导演、演员；页面提供时也读取创作者、别名、国家、语言和演员对应的角色名。**演员名单不等于人物性格或完整角色档案**，页面没有提供的人物关系、语气和角色对应关系不会编造；可继续用 `--characters` 或背景文本补充这些信息。只提取作品资料，不读取评论、影评或自动下载海报。

未指定名称时，会从文件名去掉常见年份、季集、分辨率和编码等发行标记作为搜索名称，并提取可辨认的年份或 `SxxExx`。文件名含 IMDb `tt...` ID 时优先使用该 ID。无法清理的文件名仍可用 `--title` 指定；系列剧文件中的年份不自动当作整部剧的首播年。

名称自动匹配要求搜索结果的标题或别名一致，并结合可用的年份、作品类型、季数筛选；不将模糊相似名称自动当成同一作品。同名候选无法区分时会在日志里列出候选，提示提供年份、季数或链接；该来源的背景会跳过，继续其他来源或手动背景。两站都提供 IMDb ID 且 ID 冲突时，不合并冲突来源的剧情。

影片资料和搜索候选缓存位于 `~/.cache/llmsrt/media/`，跟随 `--cache-dir`，默认有效 30 天。`--metadata-cache-days` 调整有效期，`--metadata-refresh` 忽略已有磁盘缓存；同一次批量运行会复用搜索和详情结果，单次运行已失败的同一查询也不会反复请求。`--offline` 只读取影片缓存，可以使用过期缓存，不访问任何影片网站；缺少资料时降级为手动背景或文件名线索。

公开页面和搜索建议接口可能因 403、429、登录、访问验证、网络超时或页面结构变化而不可用。这是尽力获取，不是稳定的官方 API；不尝试绕过访问验证，失败会警告并继续字幕翻译。已指定 ID 可以避免搜索歧义，但不能保证页面一定可访问。IMDb 的公开资料和豆瓣详情页示例见 [IMDb](https://www.imdb.com/title/tt0816692/) 与 [豆瓣](https://movie.douban.com/subject/1889243/)；抓取与解析模块为 `media_metadata.py`。当前环境没有执行这些查询代码或验证真实抓取效果。


目录批处理的显式 IMDb/豆瓣 ID 会用于该目录里的所有视频，适合同一作品或同一电视剧的分集。混合电影目录应按文件名自动查询，或按作品分开运行，避免全目录使用同一个 ID。

## 电影、电视剧及人物背景

每个翻译批次都会包含作品背景，让模型结合剧情类型、时代、人物关系和说话风格理解对白，并保持人名译法一致。

```bash
# 明确作品身份；年份可以帮助区分同名电影
python llmsrt.py /data/movie.mkv --title '电影名称' --media-type movie --year 2024

# 电视剧的季集与人物风格说明
python llmsrt.py /data/Breaking.Bad.S01E01.mkv \
  --title 'Breaking Bad' --media-type tv --season 1 --episode 1 \
  --media-context '犯罪题材，保留黑色幽默、紧张感和人物口语差异。' \
  --characters 'Walter White=沃尔特·怀特；Jesse Pinkman=杰西·平克曼。语气以当前对白为准。'

# 将较长的背景、人物关系、口头禅与名称译法放入 UTF-8 文本文件
python llmsrt.py /data/movie.mkv --title '作品名称' \
  --media-context-file /data/background.txt
```

- `--title`（也可写 `--media-title`）指定作品名；未指定时以文件名作为搜索线索，优先使用 IMDb/豆瓣匹配到的资料；`--no-metadata` 可关闭联网查询。
- `--media-type movie|tv|auto` 指定电影或电视剧，`auto` 表示未明确指定；`--year`、`--season`、`--episode` 都是可选字段，季数 `0` 可用于特别篇。
- `--media-context`（别名 `--background`）描述剧情、题材、时代或翻译风格；`--characters` 描述人物、关系、语气和名称译法。
- `--media-context-file` 读取 UTF-8 背景文本，与命令行背景合并。配置文件中的相对背景路径相对于配置文件所在目录；直接在命令行指定的相对路径相对于当前工作目录。
- 提示词要求背景辅助理解，实际对白优先，不允许因为模型记忆中的剧情而改写或补充原对白；文件名中的发行标签也只作为线索。
- 作品名、年份、季集、人物说明、背景文本以及 IMDb/豆瓣取得的资料都会纳入翻译缓存键。更改背景后如需替换已有 SRT，请加 `--overwrite`，否则已有输出仍会跳过。

目录批处理时，显式指定的作品名和背景用于目录中的所有视频，适合处理同一电视剧；混合电影目录可以不指定统一作品名，让每个文件使用自己的文件名查找资料，或分开运行并指定各自的背景。不要给不同剧集统一指定错误的 `--episode`。背景和网站简介会随每批重复发送并占用输入 token，适合提供精简、准确的说明。

## 实时进度

默认每 **5 秒**输出一行进度，切换阶段、开始 API 请求、批次完成及文件结束时立即输出。即使影片信息获取、FFmpeg、识别模型加载或大模型响应尚未结束，也会持续显示当前阶段和耗时。

格式示例（不是实际运行结果）：

```text
INFO: [file 1/3] movie.mkv | translating subtitles | 100/500 entries (20.0%) | ETA 00:05:00 | stage elapsed 00:01:00 | cached/original 20, model-completed 80
INFO: [file 1/3] movie.mkv | translating subtitles | 100/500 entries (20.0%) | ETA 00:05:00 | stage elapsed 00:01:00 | waiting for gpt-6-luna, subtitles #101-#120, 20 entries, attempt 1/3
```

进度包含当前文件及文件总数、处理阶段、百分比、阶段耗时和预计剩余时间。翻译以**全部目标语言已完成的字幕条数**计数，分别显示缓存/原文条数与模型完成条数；结果通过编号和结构校验后才增加完成数，等待响应、重试和拆分不会把未完成字幕计入。

语音识别按已处理的音频时间显示进度，同时显示产生的字幕数；探测、提取及模型加载没有可靠总量时只显示阶段和耗时。剩余时间根据当前阶段的处理速度粗略估算，翻译估算排除开始前已命中的缓存/原文，首次批次结束前显示 estimating；不同批次、限速、重试及静音会影响估算。它不是整部视频或整个目录的总完成时间。

```bash
# 更频繁地显示进度
python llmsrt.py /data/movie.mkv --progress-interval 2

# 关闭定时进度，仍保留错误、API 用量与文件结果日志
python llmsrt.py /data/movie.mkv --no-progress

# 保存输出并实时观察；日志写入 stdout，每行立即 flush
python llmsrt.py /data/movie.mkv --config config.local.json | tee translation.log
```

## 使用示例

从项目目录运行下列命令；默认扫描调用命令时的当前工作目录。

```bash
# 处理当前目录，默认输出 zh-cn,en
python llmsrt.py

# 指定文件，包含空格的路径需要引号
python llmsrt.py '/data/videos/My Movie.mkv'

# 指定目录，包括子目录；输出目录保留原有子目录结构
python llmsrt.py /data/videos --recursive --output-dir /data/subtitles

# 日文源字幕，英文在上、简体中文在下
python llmsrt.py /data/movie.mkv --source ja --targets en,zh-cn

# 三种语言仍合并到一份 SRT 中
python llmsrt.py /data/movie.mkv --targets zh-cn,en,ja

# 默认关闭语音识别，也可显式关闭
python llmsrt.py /data/movie.mkv --no-asr

# 只查看轨道，不调用翻译 API，也不需要 API 密钥
python llmsrt.py /data/movie.mkv --list-streams

# 手动选择 ffprobe 显示的字幕流 #4
python llmsrt.py /data/movie.mkv --subtitle-stream 4

# 使用经过 OCR 或其他方式取得的字幕
python llmsrt.py /data/movie.mkv --subtitle /data/movie.en.srt --source en

# 非 UTF-8 外挂字幕
python llmsrt.py /data/movie.mkv --subtitle /data/movie.zh.srt \
  --source zh-cn --subtitle-encoding GB18030

# 显式开启后备识别，使用音轨 #2 和更大的识别模型（需可选依赖）
python llmsrt.py /data/movie.mkv --asr --audio-stream 2 --asr-model small

# 指定单个输出文件，已有输出默认跳过
python llmsrt.py /data/movie.mkv --output /data/result.srt

# 明确替换已有输出；源视频和源字幕不会被覆盖
python llmsrt.py /data/movie.mkv --overwrite

# 只用已有资料和译文缓存；缓存缺失时报错，默认不使用识别模型
python llmsrt.py /data/movie.mkv --offline

# 全部参数
python llmsrt.py --help
```

`--subtitle-stream` 和 `--audio-stream` 使用 FFprobe 的**绝对流索引**。例如 `#4 subtitle` 应指定 `4`，不是“第四条字幕”的序号。显式指定的字幕文件或字幕流不可用时直接报错，以便发现指定错误。

## 源语言选择

1. 指定 `--source` 时，只尝试对应语言的字幕；没有可用字幕时默认报错，开启 `--asr` 后才寻找对应音轨做语音识别。不会静默改用其他已标注语言。通过 `--subtitle` 手动提供字幕时，`--source` 是该文件的语言声明。
2. 不指定源语言时优先尝试内嵌英文字幕。英文不可提取时，使用视频中按绝对流索引排列的第一条可提取文本字幕。图片字幕、空轨和损坏字幕会跳过。
3. 没有可用内嵌文本字幕时寻找同目录的外挂字幕，如 `movie.srt`、`movie.en.srt`、`movie.eng.ass`、`movie.zh-cn.srt`。外挂字幕也优先英文，其余按文件名排序。
4. 仍没有可用字幕时，默认报错并提示提供文本字幕。仅在开启 `--asr` 后，才优先英文音轨、其次第一条音轨，使用 faster-whisper 的 `transcribe` 模式生成源语言字幕，再交给大模型翻译。没有显式源语言时自动判断对白语言，不强制把非英文音轨当成英文。

MKV 常用的 `eng`、`jpn`、`chi`、`zho` 等标签会转换为 `en`、`ja`、`zh` 等代码。缺少语言标签的文本字幕使用 `langid` 推测，英文推测结果也参与优先选择。推测不准确时可用 `--subtitle-stream N --source xx` 明确声明该无标签轨道的源语言，或通过 `--subtitle` 提供源字幕。无标签音轨在指定 `--source` 时按该语言识别。

轨道标签为 `chi`/`zho` 时不能据此区分简繁，选择时按中文匹配。大模型提示词明确区分简繁，输出再通过 OpenCC 转换为 `zh-cn` 简体或 `zh-tw` 繁体。`en-US` 等其他地区标签按基础语言处理。

## 输出格式

输入 `/data/movie.mkv` 默认输出 `/data/movie.mkv.zh-cn.en.srt`。保留视频扩展名避免同目录 `movie.mkv` 与 `movie.mp4` 的输出冲突，单视频可通过 `--output` 自定义文件名。

```srt
1
00:00:01,000 --> 00:00:03,000
你好，世界！
Hello, world!

2
00:00:04,500 --> 00:00:06,000
我们出发吧。
Let's go.
```

`--targets en,zh-cn` 把英文放前面、中文放后面，不生成两个文件。重复指定目标语言时保留第一次出现的位置；目标语言与源语言相同时保留原文，不发送给大模型，中文按指定简繁转换。

各语言共用源字幕的开始和结束时间。输出为 UTF-8，移除样式标签；每种语言可能包含多行，所以双语字幕不保证始终只有两行。这里只生成外挂 SRT，不封装回视频，也不烧录进画面。

## 批量翻译、缓存与模型兼容

- 默认每批最多 20 条字幕，同时请求该批所需的全部目标语言，不会把每种语言都单独请求一次。
- 每批额外提供前后各 2 条字幕作为上下文。用 `--context-cues` 调整，`--batch-size` 调整条目数，`--batch-chars` 控制源文本字符数乘目标语言数的软上限；上下文和 JSON 格式也会占用 token，因此字符数不是精确 token 预算。
- 字幕带固定编号，模型只能返回编号及译文。脚本检查编号是否完整、是否重复、目标语言是否齐全、译文是否为空；乱序结果按编号归位，时间戳由脚本保留。
- 默认发送 `response_format={"type":"json_object"}`，同时在提示词中要求 JSON；JSON 模式不保证字段一定正确，所以脚本仍会校验。模型不支持该参数时可加 `--no-json-mode`，仍要求并解析 JSON，不会自动改成未校验的纯文本。
- 输出截断时立即拆小批次；无效结果按 `--retries` 重试后拆分，单条仍失败则报告错误，不生成错位或漏条目的最终字幕。重试及拆分会增加 API 调用和费用。
- 请求遇到限速、超时或可恢复的服务错误时退避重试；鉴权或参数错误直接报错。`--retries` 默认 2 次，`--timeout` 默认 120 秒，`--request-interval` 可设置请求间隔。
- `--max-tokens` 默认 8192。OpenAI 使用 `max_completion_tokens`，GLM / DeepSeek 使用 `max_tokens`。推理模型可能将思考 token 计入预算；如果不断出现单条截断，请增大上限或选用非思考配置。
- 默认不发送 `temperature`，兼容不接受采样温度的推理模型。需要时可显式设置；具体范围由服务商和模型决定。
- `--extra-body` 或配置文件的 `extra_body` 可添加模型参数，如 `{"thinking":{"type":"disabled"}}` 或 `{"reasoning_effort":"low"}`。请只使用所选模型支持的参数；它不能覆盖模型、消息、流式开关、格式、温度或 token 上限。示例配置不含服务商专属参数；为 DeepSeek 关闭思考模式可自行添加 `{"thinking":{"type":"disabled"}}`。

缓存默认位于 `~/.cache/llmsrt/translations.sqlite3`，用 `--cache-dir` 修改。键包含服务商、API 地址、模型、提示词、翻译参数、作品身份与背景、源/目标语言、原文和邻近上下文，缓存内容为译文；同名模型在服务商内部更新后不会自动失效，如需重新翻译请换缓存目录并加 `--overwrite`。缓存逐条持久化，中断后已完成的批次可复用。新增背景提示词后会使用新缓存键，先前版本的译文不会被自动当作这次的背景翻译结果。

`--offline` 不调用翻译 API，也不下载识别模型，只读取完整缓存；它不能让云端大模型在本机离线翻译。缺少译文缓存时报告错误。源语言与全部目标语言相同时无需大模型，也不需要密钥。

## 语音识别与文件处理

- 语音识别默认关闭，需要安装 `requirements-asr.txt` 并添加 `--asr`。开启后预设为 `base` 模型、CPU `int8`、4 个线程。`--asr-model` 可改成 `tiny`、`small` 或本地 CTranslate2 格式模型目录；准确率和耗时取决于视频与硬件。
- `--device cuda` 默认使用 `float16`，GPU 依赖按 [faster-whisper 安装说明](https://github.com/SYSTRAN/faster-whisper#gpu) 配置。`--cpu-threads` 和 `--compute-type` 可手动设置。
- Whisper 模型使用 Hugging Face 缓存；离线部署需先完整准备对应模型。
- 临时字幕和 16kHz 单声道 PCM 音频存放在系统临时目录，处理结束自动清理。WAV 大约每小时 115MB；长视频还会消耗识别内存。
- 翻译会缓存，语音识别结果不会持久化。中断后重跑会重新提取或识别，但可复用已完成的译文。
- 完整结果先写到临时文件，再原子写入最终路径。默认跳过已有输出，需 `--overwrite` 才替换；源视频及源外挂字幕不会被覆盖。
- 批量处理中单个视频失败不影响其他文件，最后报告完成、跳过与失败数量。退出码：成功或跳过为 `0`，有失败为 `1`，参数用法错误为 `2`，用户中断为 `130`。排查可加 `--verbose`。

语音识别可能漏听或识别错，大模型也可能误译人名、俚语或上下文。脚本校验的是条目结构和对应关系，不能保证译文语义完全准确。

## 手动提取与 OCR

以下命令可在目标 Linux 环境查看或提取字幕轨：

```bash
ffprobe -v error -show_streams -of json /data/movie.mkv

# 将绝对流 #3 转为文本 SRT，仅适用于可解码的文本字幕
ffmpeg -nostdin -i /data/movie.mkv -map 0:3 -c:s srt /data/source.srt

# PGS 原样导出为 SUP；SUP 仍是图片，需另外 OCR
ffmpeg -nostdin -i /data/movie.mkv -map 0:3 -c:s copy /data/source.sup
```

如果有准确的图片字幕，外部 OCR 得到的 SRT 通常更接近原字幕文本；OCR 工具、语言识别包或硬字幕的画面裁剪需要另行配置。本脚本支持通过 `--subtitle` 输入 OCR 结果，但不自动执行图片字幕或硬字幕 OCR。

## 许可证

[MIT](LICENSE)
