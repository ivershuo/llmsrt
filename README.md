# llmsrt

[![PyPI](https://img.shields.io/pypi/v/llmsrt)](https://pypi.org/project/llmsrt/)

**English** | [简体中文](README.zh-CN.md)

A command-line tool that translates video subtitles with a large language model into **one multilingual SRT** — by default Simplified Chinese on top, English below. It reads embedded or sidecar text subtitles, translates via an OpenAI-compatible API, and writes the result next to the video. Subtitle extraction uses FFmpeg; see the [FFmpeg documentation](https://ffmpeg.org/ffmpeg.html) and [codec documentation](https://ffmpeg.org/ffmpeg-codecs.html).

Speech recognition is disabled by default. After installing the optional dependencies and explicitly enabling `--asr`, the tool uses [faster-whisper](https://github.com/SYSTRAN/faster-whisper) to run Whisper locally as a fallback when no usable text subtitles are available. The defaults are CPU, the `base` model and `int8` precision; the model is downloaded on first use. Video and audio are processed on your machine and never uploaded.

## Quick start

```bash
# 1. FFmpeg and Python 3.10+
sudo apt-get install -y ffmpeg python3 python3-pip   # Debian / Ubuntu
brew install ffmpeg python                           # macOS

# 2. Install llmsrt
python3 -m pip install --user llmsrt

# 3. Set an API key (OpenAI is the default provider)
export OPENAI_API_KEY='your-key'

# 4. Translate
llmsrt /data/movies/Interstellar.mkv
```

The output appears next to the video: `Interstellar.mkv.zh-cn.en.srt`. Run `llmsrt` with no path to process every video in the current directory. `llmsrt --help` lists all options.

## Basic usage

```bash
llmsrt                                  # every video in the current directory
llmsrt movie.mkv                        # one video; quote paths with spaces
llmsrt /data/videos --recursive         # include subdirectories
llmsrt movie.mkv --targets en,zh-cn     # English on top, Chinese below
llmsrt movie.mkv --source ja            # use the Japanese subtitle/audio
llmsrt movie.mkv --list-streams         # show streams; no API key needed
llmsrt movie.mkv --subtitle sub.en.srt --source en    # use a sidecar/OCR'd file
llmsrt movie.mkv --subtitle sub.srt --source zh-cn --subtitle-encoding GB18030
llmsrt movie.mkv -o result.srt          # explicit output file
llmsrt movie.mkv --overwrite            # replace an existing output
```

- Without `--source`, embedded English subtitles are preferred; if unavailable, the first extractable embedded text track is tried, then sidecar files next to the video.
- Output is UTF-8, keeps the source timing, removes styling tags, and lays out one line per target language in the order given by `--targets`. The default bilingual output looks like:

```srt
1
00:00:01,000 --> 00:00:03,000
你好，世界！
Hello, world!
```

- Existing output files are skipped unless `--overwrite` is given; source videos and source subtitles are never modified. Results are written completely to a temporary file first and moved into place in one step; file permissions follow the system default (umask).

## Configuration

### Translation provider

API keys come from environment variables and are never stored in the config or cache.

| `--provider` | Default model | Default base URL | Key variable |
| --- | --- | --- | --- |
| `openai` (default) | `gpt-6-luna` | `https://api.openai.com/v1` | `OPENAI_API_KEY` |
| `glm` | `glm-5.3-flash` | `https://open.bigmodel.cn/api/paas/v4` | `GLM_API_KEY` |
| `deepseek` | `deepseek-flash` | `https://api.deepseek.com` | `DEEPSEEK_API_KEY` |

```bash
export GLM_API_KEY='your-key'
llmsrt movie.mkv --provider glm

# Any OpenAI-compatible gateway or self-hosted endpoint
export MY_LLM_KEY='your-key'
llmsrt movie.mkv --base-url https://your-gateway.example/v1 \
  --api-key-env MY_LLM_KEY --model your-model
```

Presets do not track each provider's newest models — pass `--model` for anything else.

### Config file

`~/.config/llmsrt/config.json` (or `$XDG_CONFIG_HOME/llmsrt/config.json`) is read automatically, so provider and tuning options need no repetition. A minimal example:

```json
{
  "provider": "glm",
  "model": "glm-5.3-flash",
  "api_key_env": "GLM_API_KEY",
  "batch_size": 20
}
```

Precedence: **command line > config file > `LLMSRT_*` environment variables > presets**. Use `--config path` or `LLMSRT_CONFIG` to point elsewhere; only one file is loaded, never merged. Accepted keys: `provider`, `model`, `base_url`, `api_key_env`, `batch_size`, `batch_chars`, `context_cues`, `temperature`, `max_tokens`, `timeout`, `retries`, `request_interval`, `json_mode`, `extra_body`, `title`, `media_type`, `year`, `season`, `episode`, `media_context`, `media_context_file`, `characters`, `progress`, `progress_interval`, `model_quips`, `metadata`, `metadata_sources`, `imdb`, `douban`, `metadata_timeout`, `metadata_cache_days`, `metadata_refresh`.

**Use `llmsrt -h` for detailed usage help.**

### Works metadata from IMDb and Douban

By default the filename is searched on IMDb and Douban, after release markers such as resolution and codec tags are stripped. The fetched synopsis, genres and cast are given to the model to help interpret the dialogue — the tool never asks the model to write its own synopsis. You can also pin the work by name or ID, or disable the online lookup:

```bash
llmsrt movie.mkv --title 'Interstellar' --year 2014
llmsrt movie.mkv --imdb-id tt0816692                     # or --imdb-url
llmsrt movie.mkv --douban-id 1889243                     # or --douban-url
llmsrt Breaking.Bad.S01E01.mkv --title 'Breaking Bad' \
  --media-type tv --season 1 --episode 1
llmsrt movie.mkv --no-metadata                           # skip online lookups
```

Matching is exact — a candidate must match the title or alias, filtered by year, media type and season. Ambiguous same-named candidates are logged and skipped, never guessed. Results are cached for 30 days under `~/.cache/llmsrt/media/` (`--metadata-cache-days`, `--metadata-refresh`). Requests go to public pages only, no API keys; failures (403/429, layout changes) warn and translation continues without that source.

### Show background and characters

```bash
llmsrt movie.mkv --title 'Show Title' \
  --media-context 'Crime drama; keep the dark humor.' \
  --characters 'Walter White=沃尔特·怀特; Jesse Pinkman=杰西·平克曼'
llmsrt movie.mkv --media-context-file background.txt      # longer UTF-8 notes
```

The prompt treats background as context only — the actual dialogue always wins. Background, character notes and fetched metadata are part of the translation cache key; after changing them, re-run with `--overwrite`.

### Speech recognition (optional)

Local speech recognition runs Whisper through [faster-whisper](https://github.com/SYSTRAN/faster-whisper) and is disabled by default. Install the optional dependencies and pass `--asr` to enable it as a fallback only when no usable text subtitles are available:

```bash
python3 -m pip install --user 'llmsrt[asr]'    # or: pipx inject llmsrt 'faster-whisper>=1.1,<2'
llmsrt movie.mkv --asr                         # used only when no text subtitle exists
llmsrt movie.mkv --asr --asr-model small --device cuda
```

Defaults: Whisper `base` model, CPU `int8`, 4 threads; the model downloads on first use (Hugging Face cache — pre-provision for offline use). Recognizes spoken dialogue only; image subtitles and hardsubs need OCR instead. `--audio-stream`, `--compute-type` and `--cpu-threads` allow manual control.

### Batching, caching and offline mode

- Batches: at most 20 entries (`--batch-size`) with a soft character cap (`--batch-chars`), 2 context entries each side (`--context-cues`); all target languages are requested in one call.
- Results are validated (IDs, languages, non-empty text); truncated output splits into smaller batches, invalid results retry per `--retries`; a still-failing entry errors out rather than producing a misaligned subtitle.
- `--no-json-mode` for models without `response_format`. Model-specific parameters go through `--extra-body`, e.g. `--extra-body '{"thinking":{"type":"disabled"}}'`, depending on what the model supports. `--max-tokens` defaults to 8192; raise it if a reasoning model's output is frequently truncated.
- Translations are cached in `~/.cache/llmsrt/translations.sqlite3`; change the directory with `--cache-dir`. Completed translations are reused on the next run after an interruption. `--offline` uses only existing caches and downloaded speech-recognition models, making no network requests; missing cached translations are an error.
- Rate limits and server errors back off and retry (`--retries`, `--timeout`, `--request-interval`); auth and parameter errors fail immediately.

### Progress

In an interactive terminal, Rich displays an in-place spinner and progress bar with the current stage, subtitle count, elapsed time, estimated time remaining and cumulative token usage. Warnings and errors remain visible above the progress display; each file ends with a completion, skip or failure summary. Use `--verbose` for per-request token logs and debug details, or `--no-progress` to disable the progress display.

After 3 seconds of waiting, a short Chinese quip appears and rotates every 8 seconds. By default, a background request to the configured translation model generates mood-inspired quips from a small excerpt of the current batch. Translation continues in parallel; local quips fill the gap and remain the fallback on errors or rejected output. Requests are limited to one at a time and at most one per minute (or the longer `--request-interval`), with a maximum 15-second timeout, a 1024-token output budget and no retries. Received quip token usage is included in the file's token totals; a request already in flight may finish after the file ends.

The quip model receives no title, synopsis, character notes or later subtitles. Its instructions restrict the humor to translation and broad atmosphere, without names, events, relationships, reveals or dialogue. A conservative output filter rejects story markers, copied Chinese text, names from the excerpt and terminal control characters; rejected or stale results are discarded. Quips only appear in the live terminal display and are cleared when the wait ends.

Use `--no-model-quips` (or `"model_quips": false` in the config) to keep local quips without extra model calls. `--model-quips` re-enables generation. Offline mode, redirected/piped output and `--no-progress` also skip all quip model calls. Extraction and speech recognition use local quips until a translation batch is available.

When redirected or piped (e.g. `| tee run.log`), output automatically switches to plain-text status lines without animations or ANSI colors. These print every 5 seconds and on stage changes; `--progress-interval` adjusts this plain-text interval. Logs continue to go to stdout.

## FAQ

**`llmsrt: command not found` after installing** — Linux puts the command in `~/.local/bin`; add it to PATH:

```bash
export PATH="$HOME/.local/bin:$PATH"   # add to ~/.profile (or ~/.zshrc) once
```

**pip reports `externally-managed-environment`** — the distribution restricts system Python; use pipx instead:

```bash
sudo apt-get install -y pipx
pipx install llmsrt && pipx ensurepath
```

**"No usable text subtitles" or only PGS/VobSub image tracks** — provide a text subtitle with `--subtitle`, OCR the image track externally first, or install the ASR extras and pass `--asr`:

```bash
ffmpeg -nostdin -i movie.mkv -map 0:3 -c:s copy out.sup   # exports the PGS track (assumed to be stream #3) for OCR
```

**How do I inspect and pick subtitle tracks?** Run `llmsrt movie.mkv --list-streams` to see the tracks. The default priority is embedded English subtitles, then the first extractable embedded text track, then sidecar files next to the video such as `movie.srt`, `movie.en.srt`, …

`--subtitle-stream N` selects a track manually, where `N` is the absolute stream index shown by `--list-streams` — for example, the line `#4 subtitle` corresponds to `--subtitle-stream 4`, not the fourth subtitle track.

With `--source` given, only subtitles in that language are used; the program never silently switches to another tagged language. Untagged text tracks are guessed with `langid`. Chinese track tags cannot distinguish Simplified from Traditional — output is converted via OpenCC according to the target language.

**Metadata lookup fails (403/429) or matches the wrong show** — IMDb and Douban public pages may be unreachable due to access limits or layout changes. Pass `--imdb-id`/`--douban-id` to pin the work and avoid search ambiguity, or `--title` + `--year` to sharpen matching. Subtitle translation always continues without metadata.

**Translations did not change after editing the background** — existing output files are skipped by default; after editing the background, re-run with `--overwrite`. The background is part of the cache key, so translations made under an old background are not silently reused. To retranslate under the same settings, point `--cache-dir` at a new directory.

**Upgrading or running a development version**

```bash
python3 -m pip install --user --upgrade llmsrt   # or: pipx upgrade llmsrt
python3 -m pip install --user "llmsrt @ git+https://github.com/ivershuo/llmsrt.git"
```

Append `@v0.1.1` to the git URL to pin a release tag.

**How accurate is the translation?** — speech recognition can miss or mishear dialogue, and LLMs can mistranslate names, slang or context. The tool validates subtitle structure and entry correspondence, but cannot guarantee the translations are fully accurate.

---

Only process content you have the right to use; do not use this tool for infringement or other unlawful purposes. Users bear responsibility for their use of this tool and its output. The project's authors and contributors are not liable for losses or disputes arising from it.

## License

[MIT](LICENSE)
