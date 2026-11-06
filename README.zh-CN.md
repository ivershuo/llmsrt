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
llmsrt movie.mkv --targets en,zh-cn     # 调整字幕顺序：英文在上，简体中文在下
llmsrt movie.mkv --source ja            # 指定字幕源语言为日语
llmsrt movie.mkv --list-streams         # 查看视频中的轨道信息，无需 API 密钥
llmsrt movie.mkv --subtitle sub.en.srt --source en    # 指定外挂字幕，也支持 OCR 生成的文本字幕
llmsrt movie.mkv --subtitle sub.srt --source zh-cn --subtitle-encoding GB18030
llmsrt movie.mkv -o result.srt          # 指定输出文件
llmsrt movie.mkv --overwrite            # 替换已有输出
```

- 未指定 `--source` 时，优先使用内嵌英文字幕；若不可用，则尝试第一条可提取的内嵌文本字幕，再查找视频所在目录中的外挂字幕。
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
| `glm` | `glm-5.3-flash` | `https://open.bigmodel.cn/api/paas/v4` | `GLM_API_KEY` |
| `deepseek` | `deepseek-flash` | `https://api.deepseek.com` | `DEEPSEEK_API_KEY` |

```bash
export GLM_API_KEY='your-key'
llmsrt movie.mkv --provider glm

# 使用兼容 OpenAI 的 API 网关或自建服务
export MY_LLM_KEY='your-key'
llmsrt movie.mkv --base-url https://your-gateway.example/v1 \
  --api-key-env MY_LLM_KEY --model your-model
```

内置预设使用固定的模型名称，不会自动切换到服务商的最新模型。如需使用其他模型，可通过 `--model` 指定。

### 配置文件

常用的服务商、模型和翻译参数可以保存在 `~/.config/llmsrt/config.json` 中，避免每次运行时重复输入。如果设置了 `XDG_CONFIG_HOME`，则从 `$XDG_CONFIG_HOME/llmsrt/config.json` 读取。配置示例：

```json
{
  "provider": "glm",
  "model": "glm-5.3-flash",
  "api_key_env": "GLM_API_KEY",
  "batch_size": 20
}
```

配置优先级为：**命令行参数 > 配置文件 > `LLMSRT_*` 环境变量 > 内置预设**。通过 `--config path` 或 `LLMSRT_CONFIG` 可指定其他配置文件。每次只加载一个配置文件，不会合并多个文件的内容。

支持的配置项：`provider`、`model`、`base_url`、`api_key_env`、`batch_size`、`batch_chars`、`context_cues`、`temperature`、`max_tokens`、`timeout`、`retries`、`request_interval`、`json_mode`、`extra_body`、`title`、`media_type`、`year`、`season`、`episode`、`media_context`、`media_context_file`、`characters`、`progress`、`progress_interval`、`metadata`、`metadata_sources`、`imdb`、`douban`、`metadata_timeout`、`metadata_cache_days`、`metadata_refresh`。

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

- 默认每批翻译最多 20 条字幕，一次请求包含全部目标语言。可用 `--batch-size` 调整每批条数，用 `--batch-chars` 设置划分批次时参考的字符数上限。每批还会附带前后各 2 条字幕作为上下文，可用 `--context-cues` 调整。
- 程序会检查字幕编号、目标语言是否齐全，以及译文是否为空。模型输出被截断时，会拆分批次重新请求；结果不符合要求时，会按 `--retries` 设置重试。如果拆分到单条字幕后仍然失败，则报错，不生成存在错位或缺失条目的最终字幕文件。
- 如果模型不支持 `response_format`，可添加 `--no-json-mode`。模型专用参数可通过 `--extra-body` 传入，例如 `--extra-body '{"thinking":{"type":"disabled"}}'`，具体取决于模型支持的参数。`--max-tokens` 默认为 8192；使用推理模型时，如果输出频繁被截断，可适当调高。
- 译文默认缓存在 `~/.cache/llmsrt/translations.sqlite3`，可通过 `--cache-dir` 更改缓存目录。运行中断后，已完成的译文可在下次运行时复用。`--offline` 仅使用已有缓存和已下载的语音识别模型，不发起网络请求；缺少所需译文缓存时会报错。
- 遇到限流或服务器错误时，会等待一段时间后自动重试；鉴权失败或参数错误则直接报错。重试次数、请求超时和请求间隔可分别通过 `--retries`、`--timeout`、`--request-interval` 设置。

### 进度显示

在交互式终端中，使用 Rich 原地刷新 spinner 和进度条，显示当前阶段、已处理字幕数、耗时、预计剩余时间和累计 token 用量。警告和错误保留在进度区上方，每个文件结束后显示完成、跳过或失败摘要。可用 `--verbose` 查看每次请求的 token 日志和调试信息，或用 `--no-progress` 关闭进度显示。

重定向或通过管道输出时（例如 `| tee run.log`），自动切换为不带动画和 ANSI 颜色的普通文本日志。默认每 5 秒输出一次进度，阶段变化时立即输出；`--progress-interval` 用于调整普通文本的输出间隔。日志仍写入标准输出。

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

如需安装指定版本，可在 Git 地址末尾添加版本标签，例如 `@v0.1.1`。

**翻译准确性如何？**

语音识别可能出现遗漏或识别错误，大模型也可能误译人名、俚语或上下文。程序会校验字幕结构及条目对应关系，但无法保证译文完全准确。

---
请仅处理您有权使用的内容，勿将本工具用于侵权或其他违法用途。用户应自行承担使用本工具及其输出结果的相关责任。本项目作者及贡献者不对由此产生的损失或纠纷承担责任。

## 许可证

[MIT](LICENSE)
