# llmsrt

[![PyPI](https://img.shields.io/pypi/v/llmsrt)](https://pypi.org/project/llmsrt/)

[English](README.md) | **简体中文**

llmsrt 是一个命令行字幕翻译工具，使用大语言模型将视频字幕翻译成多种语言，并合并输出为**一个 SRT 文件**。默认生成中英双语字幕，简体中文在上、英文在下。

支持读取视频内嵌的文本字幕或外挂字幕，通过兼容 OpenAI 的 API 进行翻译，输出文件默认保存在视频所在目录。字幕提取使用 FFmpeg，相关说明见 [FFmpeg 官方文档](https://ffmpeg.org/ffmpeg.html)和[编解码器文档](https://ffmpeg.org/ffmpeg-codecs.html)。

语音识别默认关闭。安装可选依赖并添加 `--asr` 后，程序才会在没有可用文本字幕时，使用 [faster-whisper](https://github.com/SYSTRAN/faster-whisper) 在本地运行 Whisper 模型，将音频转写为字幕后再翻译。默认使用 CPU、`base` 模型和 `int8` 精度，首次使用需要下载模型。视频和音频均在本地处理，不会上传。

## 快速开始

```bash
# 1. 安装 FFmpeg 和 Python 3.10 或更高版本
sudo apt-get install -y ffmpeg python3 python3-pip   # Debian / Ubuntu
brew install ffmpeg python                           # macOS

# 2. 安装 llmsrt
python3 -m pip install --user llmsrt

# 3. 设置 API 密钥（默认使用 OpenAI）
export OPENAI_API_KEY='your-key'

# 4. 翻译
llmsrt /data/movies/Interstellar.mkv
```

运行后，视频所在目录中会生成 `Interstellar.mkv.zh-cn.en.srt`。直接运行 `llmsrt` 即可处理当前目录下的所有视频；运行 `llmsrt --help` 可查看全部选项。

## 基本用法

```bash
llmsrt                                  # 给当前目录下的所有视频生成字幕文件
llmsrt movie.mkv                        # 给单个视频生成字幕文件；路径含空格时需加引号
llmsrt /data/videos --recursive         # 给指定目录及其子目录中的视频生成字幕文件
llmsrt /data/videos --concurrency 3     # 同时处理 3 个视频，默认 5 个
llmsrt movie.mkv --targets en,zh-cn     # 调整字幕顺序：英文在上，简体中文在下
llmsrt movie.mkv --source ja            # 指定字幕源语言为日语
llmsrt movie.mkv --list-streams         # 查看视频中的轨道信息，无需 API 密钥
llmsrt movie.mkv --subtitle sub.en.srt --source en    # 指定外挂字幕，也支持 OCR 生成的文本字幕
llmsrt movie.mkv --subtitle sub.srt --source zh-cn --subtitle-encoding GB18030
llmsrt movie.mkv -o result.srt          # 指定输出文件
llmsrt movie.mkv --overwrite            # 替换已有输出
llmsrt movie.mkv --full-translation     # 尝试一次翻译全部字幕
```

- 未指定 `--source` 时，优先使用内嵌英文字幕；若不可用，则尝试第一条可提取的内嵌文本字幕，再查找视频所在目录中的外挂字幕。
- 目录默认并发处理 5 个视频，可用 `--concurrency` 或配置 `"concurrency": 5` 调整；设为 `1` 则串行处理。每个视频独立显示进度、保留翻译上下文；语音识别复用一个模型并排队执行。
- 输出采用 UTF-8 编码，保留原字幕的时间轴，移除样式标签，并按 `--targets` 指定的语言顺序排列文本。例如，默认的中英双语字幕如下：

```srt
1
00:00:01,000 --> 00:00:03,000
你好，世界！
Hello, world!
```

- 如果输出文件已存在，默认跳过该视频；添加 `--overwrite` 可覆盖已有输出。源视频和源字幕不会被修改。结果会先完整写入临时文件，再一次性保存到目标路径，文件权限遵循系统默认设置。

## 配置

### 翻译服务商

API 密钥通过环境变量读取，不会保存到配置文件或缓存中。

| `--provider` | 默认模型 | 默认接口地址 | 密钥环境变量 |
| --- | --- | --- | --- |
| `openai`（默认） | `gpt-6-luna` | `https://api.openai.com/v1` | `OPENAI_API_KEY` |
| `deepseek` | `deepseek-flash` | `https://api.deepseek.com` | `DEEPSEEK_API_KEY` |

```bash
export DEEPSEEK_API_KEY='your-key'
llmsrt movie.mkv --provider deepseek

# 使用兼容 OpenAI 的 API 网关或自建服务
export MY_LLM_KEY='your-key'
llmsrt movie.mkv --provider custom --base-url https://your-gateway.example/v1 \
  --api-key-env MY_LLM_KEY --model your-model
```

仅 OpenAI 和 DeepSeek 提供内置预设。其他 `--provider` 名称均视为兼容 OpenAI 的自定义服务，必须指定 `--model`、`--base-url` 和 `--api-key-env`（也可通过对应配置项或环境变量提供）。内置预设使用固定模型名称，如需使用其他模型，可通过 `--model` 指定。

翻译和俏皮话均不声明工具，省略 `tools` 和 `tool_choice` 以兼容不同接口。`--extra-body` 不允许注入工具或联网搜索参数，工具调用响应会被拒绝；IMDb / 豆瓣资料仍由程序单独获取。

### 配置文件

常用的服务商、模型和翻译参数可以保存在 `~/.config/llmsrt/config.json` 中，避免每次运行时重复输入。如果设置了 `XDG_CONFIG_HOME`，则从 `$XDG_CONFIG_HOME/llmsrt/config.json` 读取。配置示例：

```json
{
  "provider": "deepseek",
  "model": "deepseek-flash",
  "api_key_env": "DEEPSEEK_API_KEY",
  "batch_size": 200
}
```

配置优先级为：**命令行参数 > 配置文件 > `LLMSRT_*` 环境变量 > 内置预设**。通过 `--config path` 或 `LLMSRT_CONFIG` 可指定其他配置文件。每次只加载一个配置文件，不会合并多个文件的内容。

支持的配置项：`concurrency`、`provider`、`model`、`base_url`、`api_key_env`、`batch_size`、`batch_chars`、`full_translation`、`context_cues`、`temperature`、`max_tokens`、`timeout`、`retries`、`request_interval`、`json_mode`、`stream`、`extra_body`、`title`、`media_type`、`year`、`season`、`episode`、`media_context`、`media_context_file`、`characters`、`progress`、`progress_interval`、`quips`、`model_quips`、`metadata`、`metadata_sources`、`imdb`、`douban`、`metadata_timeout`、`metadata_cache_days`、`metadata_refresh`。

**使用`llmsrt -h`查看具体使用帮助。**

### IMDb / 豆瓣作品资料

默认根据文件名搜索 IMDb 和豆瓣，搜索前会去除分辨率、编码等发行标记。获取到的剧情简介、作品类型和演职员资料会提供给模型，帮助理解对白；工具不会要求模型自行编写剧情简介。也可以手动指定作品名称或 ID，或关闭在线查询：

```bash
llmsrt movie.mkv --title 'Interstellar' --year 2014
llmsrt movie.mkv --imdb-id tt0816692                     # 或 --imdb-url
llmsrt movie.mkv --douban-id 1889243                     # 或 --douban-url
llmsrt Breaking.Bad.S01E01.mkv --title 'Breaking Bad' \
  --media-type tv --season 1 --episode 1
llmsrt movie.mkv --no-metadata                           # 跳过在线查询
```

搜索结果的标题或别名必须与查询名称一致，并根据已提供的年份、作品类型和季数进一步筛选。如果仍有多个无法区分的同名作品，程序会记录日志，并跳过该网站的资料。

资料默认缓存在 `~/.cache/llmsrt/media/`，有效期为 30 天。可用 `--metadata-cache-days` 调整有效期，或用 `--metadata-refresh` 重新获取。查询仅访问公开页面，无需 API 密钥；遇到 403、429 或页面结构变化等问题时，会输出警告并继续翻译。

### 作品背景与角色

```bash
llmsrt movie.mkv --title 'Show Title' \
  --media-context '犯罪题材，翻译时保留黑色幽默。' \
  --characters 'Walter White=沃尔特·怀特; Jesse Pinkman=杰西·平克曼'
llmsrt movie.mkv --media-context-file background.txt      # 从 UTF-8 文本文件读取较长的背景说明
```

背景资料仅用于辅助理解，翻译仍以实际对白为准。背景说明、角色说明和在线获取的资料都会影响翻译缓存；修改这些内容后，请加上 `--overwrite` 重新生成已有的字幕文件。

### 语音识别（可选）

本地语音识别通过 [faster-whisper](https://github.com/SYSTRAN/faster-whisper) 运行 Whisper 模型，默认关闭。需要先安装可选依赖，再添加 `--asr`；即使已开启，也仅在没有可用文本字幕时使用：

```bash
python3 -m pip install --user 'llmsrt[asr]'    # 或：pipx inject llmsrt 'faster-whisper>=1.1,<2'
llmsrt movie.mkv --asr                         # 仅在没有可用文本字幕时启用
llmsrt movie.mkv --asr --asr-model small --device cuda
```

默认使用 Whisper 的 `base` 模型，在 CPU 上以 `int8` 精度运行，使用 4 个线程。模型在首次使用时下载，并保存到 Hugging Face 缓存目录；如需离线使用，请提前下载模型。

语音识别处理的是音频中的对白。PGS、VobSub 等图像字幕，以及直接嵌入视频画面的硬字幕，需要另行使用 OCR 转为文本。可通过 `--audio-stream` 选择音轨，通过 `--compute-type` 和 `--cpu-threads` 调整计算精度与线程数。

### 批量翻译、缓存与离线模式

- 默认每批最多 200 条字幕（`--batch-size`），字符参考上限为 24,000（`--batch-chars`，按源文字符数乘以缺失目标语言数量累计），前后各附带 20 条上下文（`--context-cues`）。
- `--full-translation` 将全部缺失译文放入一次请求，以完整源文作为上下文，忽略分批限制并复用已有缓存。默认关闭，也可配置 `"full_translation": true`。请按模型能力设置 `--max-tokens` 和 `--timeout`；完整源文超过上下文限制时，应使用普通分批。
- 程序会检查字幕编号、目标语言和非空译文。输出截断时自动拆批，格式不合格时按 `--retries` 重试；单条字幕仍失败时会报错，避免生成错位或缺失的字幕。
- 每批附带前情摘要（最多 600 字）和人物、术语表，在当前视频的运行内存中更新，重启续跑时从空白开始。原文和用户说明优先；这些上下文不会写入字幕，也不传给俏皮话模型。
- 不支持 `response_format` 的模型可用 `--no-json-mode`。模型专用参数通过 `--extra-body` 传入，例如 `--extra-body '{"thinking":{"type":"disabled"}}'`，以模型支持情况为准。`--max-tokens` 默认为 32,768，包含思考 token；输出截断时可在模型允许的范围内调高，或减少每批条数。
- 译文默认缓存在系统临时目录下的用户专属目录，用于断点续跑。可通过 `--cache-dir` 指定缓存位置。`--offline` 在需要模型译文时依赖已有缓存。
- `llmsrt --clear-cache` 清理译文和作品资料缓存，包括旧默认译文库，并压缩数据库。加 `--cache-dir` 时只清理指定目录。
- 限流或服务器错误会退避重试（`--retries`、`--request-interval`），并发翻译共享请求间隔；鉴权或参数错误直接报错。请求超时默认为 600 秒（`--timeout`）。

### 进度显示

交互式终端为每个正在处理的视频显示 spinner 和一条进度条，包含当前阶段、字幕数量、耗时、预计剩余时间及 token 用量。默认流式接收，字幕条目到达后推进进度，整批校验成功后写入缓存；重试时回退未确认的进度。不支持流式的接口可用 `--no-stream` 或 `"stream": false`。可恢复的作品资料查询失败默认不显示，`--verbose` 查看完整诊断；`--no-progress` 关闭进度。

等待俏皮话默认关闭，`--quips` 开启后由当前模型在后台生成，失败时使用本地文案；添加 `--no-model-quips` 仅使用本地文案。文案只借用当前批次的氛围，不复述剧情，也不接收前情摘要。

重定向或管道输出时，改为每 5 秒输出普通文本状态（`--progress-interval`），可用 `| tee run.log` 保存日志。管道、离线模式和 `--no-progress` 均不调用俏皮话模型。

## 常见问题

**安装后提示 `llmsrt: command not found`**

在 Linux 下，使用 `pip install --user` 安装的命令通常位于 `~/.local/bin`，需要将该目录加入 `PATH`：

```bash
export PATH="$HOME/.local/bin:$PATH"   # 将这一行添加到 ~/.profile 或 ~/.zshrc，可在后续终端会话中生效
```

**pip 提示 `externally-managed-environment`**

当前 Python 环境由系统包管理器维护，限制了直接通过 pip 安装软件包。可以改用 pipx 安装：

```bash
sudo apt-get install -y pipx
pipx install llmsrt && pipx ensurepath
```

**提示 `No usable text subtitles`，或视频只有 PGS/VobSub 图像字幕**

可用 `--subtitle` 指定文本字幕文件。如果只有图像字幕，需先用其他 OCR 工具转换为文本；也可以安装语音识别依赖后，添加 `--asr` 从音频生成字幕。以下命令可导出 PGS 字幕，供后续 OCR 使用：

```bash
ffmpeg -nostdin -i movie.mkv -map 0:3 -c:s copy out.sup   # 此处假设 PGS 字幕的流索引为 3
```

**如何查看和选择字幕轨道？**

运行 `llmsrt movie.mkv --list-streams` 可查看轨道信息。默认优先使用内嵌英文字幕，其次是第一条可提取的内嵌文本字幕，最后查找视频所在目录中的外挂字幕，如 `movie.srt`、`movie.en.srt` 等。

可用 `--subtitle-stream N` 手动选择轨道，其中 `N` 是 `--list-streams` 显示的绝对流索引。例如，`#4 subtitle` 对应 `--subtitle-stream 4`，并非第四条字幕轨道。

指定 `--source` 后，程序只使用对应语言的字幕，不会自动切换为其他已标注的语言。未标注语言的文本字幕由 `langid` 推测语言。中文轨道的语言标签通常无法区分简繁，输出时会根据目标语言，通过 OpenCC 转换为简体或繁体。

**作品资料查询失败（403/429），或未能匹配到正确作品**

IMDb 和豆瓣的公开页面可能因访问限制或页面变化而无法获取。可通过 `--imdb-id` 或 `--douban-id` 直接指定作品，避免搜索歧义；也可以用 `--title` 和 `--year` 提高搜索匹配的准确性。即使无法获取资料，字幕翻译也会继续。

**修改背景说明后，字幕没有变化**

已有输出文件默认会被跳过。修改背景说明后，请加上 `--overwrite` 重新运行。背景说明也参与缓存匹配，不会直接复用旧背景下的译文。如果需要在相同设置下重新翻译，可同时指定一个新的 `--cache-dir`，避免复用已有译文。

**升级或安装开发版**

```bash
python3 -m pip install --user --upgrade llmsrt   # 或：pipx upgrade llmsrt
python3 -m pip install --user "llmsrt @ git+https://github.com/ivershuo/llmsrt.git"
```

如需安装指定版本，可在 Git 地址末尾添加版本标签，例如 `@v0.2.0`。

**翻译准确性如何？**

语音识别可能出现遗漏或识别错误，大模型也可能误译人名、俚语或上下文。程序会校验字幕结构及条目对应关系，但无法保证译文完全准确。

---
请仅处理您有权使用的内容，勿将本工具用于侵权或其他违法用途。用户应自行承担使用本工具及其输出结果的相关责任。本项目作者及贡献者不对由此产生的损失或纠纷承担责任。

## 许可证

[MIT](LICENSE)
