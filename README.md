# llmsrt

**English** | [简体中文](README.zh-CN.md)

A command-line tool that extracts subtitles from video files and translates them with a large language model into **a single multilingual SRT** — by default Simplified Chinese on top, English below — instead of one file per language. Accepts a video file or a directory; by default it scans the current directory.

## How subtitles are obtained, and what it costs

| Subtitle situation in the video | How it is handled | Cost & limits |
| --- | --- | --- |
| Embedded text subtitles in MKV (SRT, ASS, SSA…) | FFprobe finds the track, FFmpeg converts it to SRT | No recognition model required, usually the fastest path; ASS styling, positioning and fonts are not preserved |
| No extractable text track, but a sidecar subtitle exists | Reads SRT / ASS / SSA / VTT files next to the video | No speech recognition required; the sidecar file must match the video release |
| Only image subtitles (PGS, VobSub…) | By default you are prompted to provide a text subtitle; OCR them externally to SRT first, or explicitly enable ASR | FFmpeg can export the image subtitle stream but cannot turn images into text; no OCR is integrated |
| No subtitle track, or subtitles burned into the picture | By default you are prompted to provide a text subtitle; with the optional dependencies installed and `--asr`, faster-whisper is used | No ASR API fees, uses local CPU/GPU; recognizes spoken dialogue only, cannot restore text overlaid on the picture |

Subtitle handling follows the [FFmpeg documentation](https://ffmpeg.org/ffmpeg.html) and the [codec documentation](https://ffmpeg.org/ffmpeg-codecs.html). Speech recognition is off by default. When explicitly enabled, the fallback uses [faster-whisper](https://github.com/SYSTRAN/faster-whisper), preset to CPU, the `base` model and `int8` compute; the model downloads on first use.

**Translation uses an LLM API you configure** — OpenAI (the default), Zhipu GLM, DeepSeek — or any OpenAI-compatible gateway or self-hosted endpoint via `--base-url`. Subtitle text, show background and a small amount of surrounding context are sent to the chosen API; video and audio are processed on your machine and never sent to the translation API. Translation cost, available models and rate limits depend on the provider and your account. Works information is fetched first from public IMDb and Douban pages — IMDb is read directly from its search and title pages, with no movie API key or AWS credentials. If nothing can be found, the raw video filename is handed to the translation model as the only clue.

## Installation and PATH

Requires Python 3.10 or newer, plus `ffmpeg` and `ffprobe` in PATH. Developed and used on Linux (Debian/Ubuntu examples below) and macOS; Windows is untested.

```bash
# Debian / Ubuntu
sudo apt-get update
sudo apt-get install -y ffmpeg python3 python3-pip

# macOS
brew install ffmpeg python
```

Then install the package from [PyPI](https://pypi.org/project/llmsrt/) — no clone is needed:

```bash
python3 -m pip install --user llmsrt
# With the optional speech-recognition extras:
python3 -m pip install --user 'llmsrt[asr]'
# Or as an isolated pipx tool:
pipx install llmsrt
```

To run development state newer than the latest PyPI release, pip and pipx can install straight from this GitHub repository:

```bash
python3 -m pip install --user "llmsrt @ git+https://github.com/ivershuo/llmsrt.git"
# With the optional speech-recognition extras:
python3 -m pip install --user "llmsrt[asr] @ git+https://github.com/ivershuo/llmsrt.git"
# Or as an isolated pipx tool:
pipx install git+https://github.com/ivershuo/llmsrt.git
```

Git-based installs need `git` in PATH and build the package locally; dependencies still come from PyPI. Append `@v0.1.1` to the URL to pin a release tag, and re-run the same command with `--upgrade` to move to a newer revision. From a clone, `cd /path/to/llmsrt && python3 -m pip install --user .` works as before.

pip installs the program and its dependencies into the current user's Python directory and generates the `llmsrt` command. **No virtual environment is created for running it, and no `source activate` is needed after every SSH login.** Python dependencies are shared with the user's other Python projects. If an old `.venv` is still active, run `deactivate` once; `/usr/bin/python3 -m pip install --user llmsrt` selects a specific interpreter.

On Linux the default command directory is `~/.local/bin`. If it is not in PATH, run in the current shell:

```bash
export PATH="$HOME/.local/bin:$PATH"
```

Add this line to the shell configuration loaded at login — only once. Bash logins usually read `~/.profile`; if `~/.bash_profile` exists, put it there instead. Zsh users can use `~/.zshrc`. If `PYTHONUSERBASE` is customized, add its `bin` directory to PATH.

Then use it from any media directory:

```bash
cd /data/movies/Interstellar
llmsrt                         # process the videos in the current directory by default
llmsrt 'Interstellar.mkv'      # process just this video
llmsrt --recursive            # include subdirectories
llmsrt --targets en,zh-cn      # merged output, English on top
```

The command always resolves videos, relative paths and default outputs against the working directory at invocation time; it never changes back to the source directory. Once installed, the command does not depend on where the source lives; after editing the source, run `python3 -m pip install --user --upgrade .` from the project directory to refresh it. Uninstall with `python3 -m pip uninstall llmsrt`.

If pip reports `externally-managed-environment`, your distribution restricts the system Python and even `--user` may be blocked. Use pipx instead; pipx maintains an isolated environment internally, but day-to-day you still just run `llmsrt`, without creating, activating or managing a `.venv`. See the [Python installation specification](https://packaging.python.org/en/latest/specifications/externally-managed-environments/) and the [pipx installation guide](https://pipx.pypa.io/stable/how-to/install-pipx.html).

```bash
sudo apt-get install -y pipx
pipx install llmsrt
pipx ensurepath
# Re-login as ensurepath suggests so PATH takes effect, then just run llmsrt
```

With pipx, upgrades use `pipx upgrade llmsrt` (or `pipx install --force /path/to/llmsrt` from a clone); uninstall with `pipx uninstall llmsrt`. Pick either the user-level pip install or pipx, not both.

LLM requests use the Python standard library `urllib`, so no per-provider SDKs are installed. By default only embedded and sidecar text subtitles are processed — no GPU, faster-whisper or recognition models are needed, and nothing is downloaded automatically. A video without usable text subtitles reports an error; batch processing continues with the other videos.

For the speech-recognition fallback, install the optional dependencies on the target machine, then enable it explicitly:

```bash
# Install the optional extra dependencies at user level
python3 -m pip install --user 'llmsrt[asr]'
# If installed with pipx, use: pipx inject llmsrt 'faster-whisper>=1.1,<2'
llmsrt /data/movie.mkv --asr
```

`--asr` only invokes speech recognition when no usable text subtitle is found. Options like `--asr-model` and `--audio-stream` never enable recognition implicitly; `--no-asr` still disables it explicitly.

Per the development workflow, **the script was not executed, dependencies were not installed, no API requests were made and no tests were run in the development environment**; verify behavior on your target machine.

### Sharing one config across directories

The program automatically reads `~/.config/llmsrt/config.json`, or `$XDG_CONFIG_HOME/llmsrt/config.json` when `XDG_CONFIG_HOME` is set. From the source directory, run once:

```bash
mkdir -p "${XDG_CONFIG_HOME:-$HOME/.config}/llmsrt"
# Copy only if you have not created your own config yet, to avoid overwriting it
cp -n config.example.json "${XDG_CONFIG_HOME:-$HOME/.config}/llmsrt/config.json"
```

Edit that config to choose the provider and model; the example presets OpenAI (the default), and can be switched to GLM or DeepSeek. Keys are still read from the environment variable named by `api_key_env` in the config — e.g. `export OPENAI_API_KEY='your-key'` in the shell configuration loaded at login. Afterwards run `llmsrt` in any media directory without repeating `--config` or provider options. A shared config suits provider, model and batching settings; do not pin a single show's title or IDs in it for mixed media directories.

Config resolution order is `--config path` → the path in the `LLMSRT_CONFIG` environment variable → the user config directory. Only the selected file is loaded, configs are never merged; a missing or invalid explicitly-specified config is an error. Command-line arguments still take precedence over file settings.

You can also keep running it from the source directory with `python3 llmsrt.py`, without installing the command; in that case first install the dependencies from `requirements.txt` with the same Python.

## Configuring the translation provider

Keys are read from environment variables and never stored in the project code, the example config or the translation cache.

| `--provider` | Default model | Default API base URL | Default key environment variable |
| --- | --- | --- | --- |
| `openai` (default) | `gpt-6-luna` | `https://api.openai.com/v1` | `OPENAI_API_KEY` |
| `glm` | `glm-5.3-flash` | `https://open.bigmodel.cn/api/paas/v4` | `GLM_API_KEY` |
| `deepseek` | `deepseek-flash` | `https://api.deepseek.com` | `DEEPSEEK_API_KEY` |

These are presets baked into the script; they do not automatically track each provider's newest models — pass `--model` to use any model your account supports. Interfaces follow the [OpenAI documentation](https://developers.openai.com/api/docs/guides/structured-outputs), the [OpenAI-compatible GLM documentation](https://docs.bigmodel.cn/cn/guide/develop/openai/introduction) and the [DeepSeek API documentation](https://api-docs.deepseek.com/).

```bash
# OpenAI, the default provider; --provider openai can also be given explicitly
export OPENAI_API_KEY='replace-with-your-key'
python llmsrt.py /data/movie.mkv --model gpt-6-luna

# GLM, using Zhipu's general API endpoint
export GLM_API_KEY='replace-with-your-key'
python llmsrt.py /data/movie.mkv --provider glm --model glm-5.3-flash

# DeepSeek
export DEEPSEEK_API_KEY='replace-with-your-key'
python llmsrt.py /data/movie.mkv --provider deepseek --model deepseek-flash

# Custom API base URL and key variable name; the URL must not include /chat/completions
export MY_LLM_KEY='replace-with-your-key'
python llmsrt.py /data/movie.mkv --provider openai \
  --base-url https://your-gateway.example/v1 \
  --api-key-env MY_LLM_KEY --model your-model
```

The provider presets use the general-purpose inference APIs. GLM coding-plan endpoints differ from the general API in scope and usage; pick the base URL per your plan's official instructions, and do not assume a coding plan covers subtitle translation.

A JSON config file also works — see `config.example.json`:

```bash
cp config.example.json config.local.json
# Edit config.local.json as needed, then run
python llmsrt.py /data/movie.mkv --config config.local.json

# Command-line options can override the model or batch size from the config
python llmsrt.py /data/movie.mkv --config config.local.json \
  --model gpt-6-luna --batch-size 10
```

Config precedence: **command line > the selected config file > LLMSRT environment variables > script presets**. Environment variables include `LLMSRT_PROVIDER`, `LLMSRT_MODEL`, `LLMSRT_BASE_URL`, `LLMSRT_API_KEY_ENV`; `LLMSRT_CONFIG` points to a config file. Without an explicit config file, the user config directory's `llmsrt/config.json` is read. `config.local.json` is Git-ignored; the example contains only the key variable names, never actual keys.

The config file accepts these translation options: `provider`, `model`, `base_url`, `api_key_env`, `batch_size`, `batch_chars`, `context_cues`, `temperature`, `max_tokens`, `timeout`, `retries`, `request_interval`, `json_mode`, `extra_body`. It also accepts show background and progress: `title`, `media_type`, `year`, `season`, `episode`, `media_context`, `media_context_file`, `characters`, `progress`, `progress_interval`, and metadata fetching: `metadata`, `metadata_sources`, `imdb`, `douban`, `metadata_timeout`, `metadata_cache_days`, `metadata_refresh`. Video paths, source/target languages and ASR options are configured on the command line.

## Works metadata from IMDb and Douban

Metadata fetching is on by default; name searches go through `imdb,douban` in that order. Without an explicit title, the cleaned filename (name, year, season/episode) is searched against both sources; sources given an ID or link are processed first. When a Douban detail page includes an IMDb ID, the matching IMDb title is fetched directly, reducing false matches between same-named works. The metadata is sent with every batch as `catalog_metadata`, keeping source URLs; only when neither site yields trusted metadata does the model fall back to the raw filename for context — the tool never asks an LLM to invent a synopsis.

IMDb is always read from public web pages — no API application and no AWS SDK. With an IMDb ID/link the title page is read directly; otherwise the IMDb search page is fetched and filtered first, then the title page. Douban uses its public search suggestions and detail pages. Requests are spaced at least 1 second apart, and combined with the metadata cache, multiple episodes of one show in a directory do not re-scrape.

The legacy config keys `imdb_backend`, `omdb_api_key_env`, `imdb_api_key_env`, `imdb_data_set_id`, `imdb_revision_id`, `imdb_asset_id`, `imdb_region` have been removed; delete them from old configs. `--imdb-backend web` is no longer needed — the default behavior applies. IMDb ID and show-link parameters are still supported.

```bash
# Look up by explicit title and year
python llmsrt.py /data/Interstellar.2014.1080p.mkv \
  --title 'Interstellar' --year 2014

# Specify an IMDb ID directly (--imdb and --imdb-url also work)
python llmsrt.py /data/movie.mkv --imdb-id tt0816692

# Specify a Douban subject link directly (--douban and --douban-id also work)
python llmsrt.py /data/movie.mkv \
  --douban-url 'https://movie.douban.com/subject/1889243/'

# Both IDs point to the same work; Chinese and English metadata are both read
python llmsrt.py /data/movie.mkv \
  --imdb-id tt0816692 --douban-id 1889243

# TV: state the season to disambiguate Douban's per-season entries
python llmsrt.py /data/Breaking.Bad.S01E01.mkv \
  --title 'Breaking Bad' --media-type tv --season 1 --episode 1

# IMDb pages and Douban public data by default; no movie API key needed
python llmsrt.py /data/movie.mkv

# Query IMDb only, with a 10-second request timeout
python llmsrt.py /data/movie.mkv --metadata-sources imdb --metadata-timeout 10

# Re-fetch metadata; replacing an existing subtitle also needs --overwrite
python llmsrt.py /data/movie.mkv --metadata-refresh --overwrite

# Disable external lookups, keep the manual background
python llmsrt.py /data/movie.mkv --no-metadata --title 'Show Title'
```

What gets extracted: title, year, synopsis, genres, director and cast; when the pages provide them, also creators, aliases, country, languages and the roles attached to cast members. **A cast list is not a personality profile or a complete character sheet** — relationships, tone and character mapping absent from the pages are never fabricated; keep supplying those via `--characters` or background text. Only work metadata is extracted — no reviews, no posters are downloaded.

Without an explicit title, common release markers (years, season/episode tags, resolution, codec) are stripped from the filename to build the search name, and a recognizable year or `SxxExx` is extracted. An IMDb `tt...` ID inside the filename takes precedence. Filenames that resist cleaning can still be named with `--title`; a year inside a series filename is not assumed to be the show's first-air year.

Automatic name matching requires the search result's title or alias to match exactly, filtered by whatever year, media type and season are available; fuzzily similar names are never silently treated as the same work. When same-named candidates cannot be distinguished, the log lists them and asks for a year, season or link; that source's background is skipped and the others (or the manual background) continue. When both sites return IMDb IDs that conflict, the conflicting synopses are not merged.

Work metadata and search candidates are cached in `~/.cache/llmsrt/media/`, following `--cache-dir`, valid for 30 days by default. `--metadata-cache-days` changes the validity window; `--metadata-refresh` ignores the on-disk cache. Within one batch run, search and detail results are reused, and a query that already failed in the same run is not repeated. `--offline` reads only the local metadata cache (expired entries allowed) and never touches the sites; missing metadata degrades to the manual background or filename hints.

Public pages and search-suggestion endpoints may become unavailable through 403, 429, login walls, bot checks, network timeouts or layout changes. This is best-effort scraping, not a stable official API; the tool does not attempt to bypass access checks — failures warn and translation continues. Specifying IDs avoids search ambiguity but cannot guarantee a page is reachable. Example pages: [IMDb](https://www.imdb.com/title/tt0816692/) and [Douban](https://movie.douban.com/subject/1889243/); scraping and parsing live in `media_metadata.py`. This scraping code was not executed or verified against the live sites during development.

For directory batches, an explicit IMDb/Douban ID applies to every video in the directory — right for one show or one TV series. Mixed movie directories should rely on per-file lookups, or be split per work, instead of forcing one ID onto everything.

## Movies, TV shows and character background

Every translation batch carries the show's background so the model reads the dialogue with its genre, era, relationships and speech styles in mind, and keeps name translations consistent.

```bash
# Pin the show's identity; the year separates same-named movies
python llmsrt.py /data/movie.mkv --title 'Movie Title' --media-type movie --year 2024

# Season/episode plus character style notes for a TV show
python llmsrt.py /data/Breaking.Bad.S01E01.mkv \
  --title 'Breaking Bad' --media-type tv --season 1 --episode 1 \
  --media-context 'Crime drama; keep the dark humor, the tension, and the differences in how each character speaks.' \
  --characters 'Walter White=沃尔特·怀特; Jesse Pinkman=杰西·平克曼. Follow the current dialogue for tone.'

# Put longer background, relationships, catchphrases and name mappings in a UTF-8 text file
python llmsrt.py /data/movie.mkv --title 'Show Title' \
  --media-context-file /data/background.txt
```

- `--title` (alias `--media-title`) names the work; without it the filename is the search clue and IMDb/Douban matches take precedence; `--no-metadata` disables the online lookup.
- `--media-type movie|tv|auto` picks movie or TV, with `auto` meaning unspecified; `--year`, `--season`, `--episode` are all optional, and season `0` works for specials.
- `--media-context` (alias `--background`) describes plot, genre, era or translation style; `--characters` describes people, relationships, tone and name translations.
- `--media-context-file` reads UTF-8 background text and merges with the command-line background. Relative background paths inside a config file resolve against the config file's directory; relative paths given directly on the command line resolve against the current working directory.
- The prompt instructs the model to use background only as context: the actual dialogue wins, and the model must never rewrite or extend it based on its memory of the plot; release tags in filenames are hints only.
- Title, year, season/episode, character notes, background text and everything fetched from IMDb/Douban all feed into the translation cache key. After changing the background, add `--overwrite` to replace an existing SRT; otherwise existing outputs are skipped.

In directory batches, an explicit title and background apply to every video in the directory — right for one TV series; mixed movie directories can omit a shared title so each file looks itself up, or be run separately with per-work backgrounds. Do not pin one wrong `--episode` onto different episodes. Background and site synopses are re-sent with every batch and consume input tokens, so keep them concise and accurate.

## Live progress

By default one progress line prints every **5 seconds**, and immediately on stage changes, API request starts, batch completions and file finishes. Even while metadata fetching, FFmpeg, model loading or an LLM response is still running, the current stage and elapsed time keep updating.

Sample format (not from a real run):

```text
INFO: [file 1/3] movie.mkv | translating subtitles | 100/500 entries (20.0%) | ETA 00:05:00 | stage elapsed 00:01:00 | cached/original 20, model-completed 80
INFO: [file 1/3] movie.mkv | translating subtitles | 100/500 entries (20.0%) | ETA 00:05:00 | stage elapsed 00:01:00 | waiting for gpt-6-luna, subtitles #101-#120, 20 entries, attempt 1/3
```

Progress covers the current file and file count, processing stage, percentage, stage elapsed time and estimated time remaining. Translation counts **entries completed in all target languages**, splitting cached/original entries from model-completed ones; the completed count only grows after entries pass numbering and structure validation — waiting, retrying and splitting never count unfinished entries.

Speech recognition reports progress by processed audio duration alongside the subtitle count; probing, extraction and model loading show only stage and elapsed time when no reliable total exists. Remaining time is a rough estimate from the current stage's speed; the translation estimate excludes cache/original hits present before the start and shows "estimating" before the first batch finishes. Batches, rate limits, retries and silence all affect the estimate — it is not the total time for the whole video or directory.

```bash
# Show progress more frequently
python llmsrt.py /data/movie.mkv --progress-interval 2

# Disable timed progress; errors, API usage and per-file results still log
python llmsrt.py /data/movie.mkv --no-progress

# Save output and watch it live; logs go to stdout and every line is flushed
python llmsrt.py /data/movie.mkv --config config.local.json | tee translation.log
```

## Usage examples

Run these from the project directory; by default the current working directory at invocation is scanned.

```bash
# Process the current directory; default output zh-cn,en
python llmsrt.py

# A specific file; quote paths containing spaces
python llmsrt.py '/data/videos/My Movie.mkv'

# A directory including subdirectories; output preserves the subdirectory layout
python llmsrt.py /data/videos --recursive --output-dir /data/subtitles

# Japanese source subtitles, English on top, Simplified Chinese below
python llmsrt.py /data/movie.mkv --source ja --targets en,zh-cn

# Three languages still merged into one SRT
python llmsrt.py /data/movie.mkv --targets zh-cn,en,ja

# Speech recognition is off by default; it can also be disabled explicitly
python llmsrt.py /data/movie.mkv --no-asr

# List streams only — no translation API, no API key needed
python llmsrt.py /data/movie.mkv --list-streams

# Manually pick subtitle stream #4 as shown by ffprobe
python llmsrt.py /data/movie.mkv --subtitle-stream 4

# Use a subtitle obtained via OCR or any other means
python llmsrt.py /data/movie.mkv --subtitle /data/movie.en.srt --source en

# A non-UTF-8 sidecar subtitle
python llmsrt.py /data/movie.mkv --subtitle /data/movie.zh.srt \
  --source zh-cn --subtitle-encoding GB18030

# Explicitly enable the ASR fallback with audio stream #2 and a larger model (optional deps required)
python llmsrt.py /data/movie.mkv --asr --audio-stream 2 --asr-model small

# A single output file; existing outputs are skipped by default
python llmsrt.py /data/movie.mkv --output /data/result.srt

# Replace existing outputs explicitly; source videos and subtitles are never overwritten
python llmsrt.py /data/movie.mkv --overwrite

# Use only existing metadata and translation caches; missing cache is an error, no ASR by default
python llmsrt.py /data/movie.mkv --offline

# All options
python llmsrt.py --help
```

`--subtitle-stream` and `--audio-stream` take FFprobe's **absolute stream index**. For a line like `#4 subtitle`, pass `4` — not "the fourth subtitle track". Explicitly requested subtitle files or streams that turn out unavailable fail loudly, so misconfigurations surface.

## Source language selection

1. With `--source`, only subtitles in that language are tried; when none exist it errors by default — only after `--asr` will matching audio streams be recognized. It never silently falls back to another tagged language. When the subtitle is provided manually via `--subtitle`, `--source` declares that file's language.
2. Without a source language, embedded English subtitles are tried first. When English is not extractable, the first extractable text subtitle by absolute stream index is used. Image subtitles, empty tracks and broken subtitles are skipped.
3. Without usable embedded text subtitles, sidecar files are considered: `movie.srt`, `movie.en.srt`, `movie.eng.ass`, `movie.zh-cn.srt`. English sidecars win, the rest follow filename order.
4. Still nothing? By default it errors and asks for a text subtitle. Only with `--asr` does it fall back to the English audio track first, otherwise the first audio track, transcribing with faster-whisper's `transcribe` mode before handing the result to the LLM. Without an explicit source language, the spoken language is detected rather than assumed to be English.

Common MKV tags such as `eng`, `jpn`, `chi` and `zho` map to `en`, `ja`, `zh` and so on. Text subtitles without a language tag are guessed with `langid`, and a guessed-English result joins the priority selection. When guessing misses, declare the language explicitly with `--subtitle-stream N --source xx`, or provide the subtitle via `--subtitle`. Untagged audio tracks are treated as `--source`'s language when it is given.

`chi`/`zho` track tags cannot distinguish Simplified from Traditional Chinese; selection matches Chinese generally. The LLM prompt distinguishes them explicitly, and the output is converted via OpenCC to `zh-cn` (Simplified) or `zh-tw` (Traditional). Regional tags like `en-US` are treated as the base language.

## Output format

Input `/data/movie.mkv` produces `/data/movie.mkv.zh-cn.en.srt` by default. The video extension is kept so `movie.mkv` and `movie.mp4` in one directory never collide; a single video can name its output via `--output`.

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

`--targets en,zh-cn` puts English first and Chinese second — still one file. Duplicate target languages keep their first position; a target equal to the source language keeps the original text (never sent to the LLM), converted per the requested Chinese variant.

Every language shares the source subtitle's start and end times. Output is UTF-8 with styling tags removed; each language may span multiple lines, so a bilingual block is not guaranteed to be exactly two lines. Only sidecar SRT files are produced — nothing is remuxed into the video or burned into the picture.

## Batching, caching and model compatibility

- Batches default to at most 20 entries, requesting every target language for the batch in one call — never one request per language.
- Each batch carries 2 entries of surrounding context before and after. Tune with `--context-cues`; entry count with `--batch-size`; `--batch-chars` caps source characters × target languages as a soft limit. Context and JSON framing also consume tokens, so character counts are not an exact token budget.
- Entries carry fixed IDs and the model may only return IDs and translations. The script checks for missing or duplicate IDs, complete target languages and empty translations; out-of-order results are placed by ID, and timestamps come from the script.
- `response_format={"type":"json_object"}` is sent by default, with JSON also demanded in the prompt; JSON mode does not guarantee well-formed fields, so the script still validates. Add `--no-json-mode` for models without this parameter — JSON is still required and parsed; it never silently degrades to unvalidated free text.
- Truncated output splits into smaller batches immediately; invalid results retry per `--retries` and then split; a still-failing single entry is reported as an error rather than producing a misaligned or gapped subtitle. Retries and splits increase API calls and cost.
- Rate limits, timeouts and recoverable server errors back off and retry; auth and parameter errors fail immediately. `--retries` defaults to 2, `--timeout` to 120 seconds, and `--request-interval` spaces requests.
- `--max-tokens` defaults to 8192. OpenAI uses `max_completion_tokens`; GLM / DeepSeek use `max_tokens`. Reasoning models may count thinking tokens against the budget; if single entries keep truncating, raise the limit or pick a non-thinking configuration.
- `temperature` is not sent by default, for compatibility with reasoning models that reject sampling temperatures. Set it explicitly when wanted; the supported range depends on provider and model.
- `--extra-body` or the config's `extra_body` adds model parameters such as `{"thinking":{"type":"disabled"}}` or `{"reasoning_effort":"low"}`. Use only parameters your model supports; they cannot override the model, messages, streaming, response format, temperature or token limits. The example config carries no provider-specific parameters.

The cache lives at `~/.cache/llmsrt/translations.sqlite3` by default; change it with `--cache-dir`. The key covers provider, API base URL, model, prompt, translation parameters, show identity and background, source/target languages, the original text and neighboring context; the value is the translation. A model updated server-side under the same name does not auto-invalidate the cache — to retranslate, switch the cache directory and add `--overwrite`. The cache persists entry by entry, so completed batches are reusable after an interruption. New background prompts produce new cache keys; older translations are never silently reused as the new background's output.

`--offline` makes no translation API calls and downloads no recognition models; it reads the full cache only — it cannot run a cloud LLM locally. Missing translations are errors. When the source equals all target languages, no LLM (and no key) is needed at all.

## Speech recognition and file handling

- Speech recognition is off by default; install `requirements-asr.txt` and pass `--asr`. Defaults are the `base` model, CPU `int8` and 4 threads. `--asr-model` accepts `tiny`, `small`, or a local CTranslate2 model directory; accuracy and runtime depend on the video and hardware.
- `--device cuda` defaults to `float16`; set up GPU dependencies per the [faster-whisper install guide](https://github.com/SYSTRAN/faster-whisper#gpu). `--cpu-threads` and `--compute-type` allow manual control.
- Whisper models use the Hugging Face cache; fully provision the models beforehand for offline deployment.
- Temporary subtitles and 16 kHz mono PCM audio live in the system temp directory and are cleaned up afterwards. The WAV alone is roughly 115 MB per hour; long videos also add recognition memory.
- Translations are cached; speech recognition results are not persisted. Re-running after an interruption re-extracts or re-recognizes, but reuses finished translations.
- Complete results are written to a temporary file first, then atomically moved into place. Existing outputs are skipped unless `--overwrite` is given; source videos and source sidecar subtitles are never overwritten.
- In batch processing one failed video never blocks the rest, and the run ends with counts of completed, skipped and failed files. Exit codes: `0` for success or all-skipped, `1` when anything failed, `2` for usage errors, `130` on user interrupt. Add `--verbose` when debugging.

Speech recognition can mishear, and LLMs can mistranslate names, slang or context. The script validates structure and entry correspondence — it cannot guarantee semantic accuracy of every translation.

## Manual extraction and OCR

These commands inspect or extract subtitle tracks on the target machine:

```bash
ffprobe -v error -show_streams -of json /data/movie.mkv

# Convert absolute stream #3 to text SRT; decodable text subtitles only
ffmpeg -nostdin -i /data/movie.mkv -map 0:3 -c:s srt /data/source.srt

# Export PGS verbatim as SUP; SUP is still images and needs separate OCR
ffmpeg -nostdin -i /data/movie.mkv -map 0:3 -c:s copy /data/source.sup
```

With accurate image subtitles, an externally OCR'd SRT is usually closer to the original text than ASR; OCR tooling, language packs and hardsub cropping need separate setup. This tool accepts OCR results via `--subtitle` but performs no image-subtitle or hardsub OCR itself.

## License

[MIT](LICENSE)
