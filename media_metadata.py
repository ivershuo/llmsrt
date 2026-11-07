"""Public IMDb/Douban webpage metadata with conservative title matching.

IMDb search and title information are read directly from public HTML pages.
No login, captcha solving, or anti-bot bypass is performed.
Only selected title metadata is retained; reviews and full page HTML are not cached.
"""

from __future__ import annotations

import gzip
import hashlib
import html
from http.client import HTTPException
import json
import logging
from pathlib import Path
import re
import tempfile
import threading
import time
import unicodedata
from typing import Any
from urllib import error, parse, request


LOG = logging.getLogger("llmsrt")
SOURCES = {"imdb", "douban"}
ALLOWED_HOSTS = {"www.imdb.com", "imdb.com", "movie.douban.com"}


class MetadataError(Exception):
    """Unavailable or ambiguous movie metadata."""


def text(value: Any, limit: int = 1600) -> str:
    if not isinstance(value, str):
        return ""
    return re.sub(r"\s+", " ", html.unescape(value)).strip()[:limit]


def names(value: Any, limit: int = 20) -> list[str]:
    values = value if isinstance(value, list) else [value]
    result = []
    for item in values:
        name = text(item.get("name", "") if isinstance(item, dict) else item, 160)
        if name and name not in result:
            result.append(name)
    return result[:limit]


def year_of(value: Any) -> int | None:
    match = re.search(r"\b((?:18|19|20|21)\d{2})\b", str(value))
    return int(match[1]) if match else None


def canonical_url(source: str, reference: str) -> str:
    reference = reference.strip()
    pattern = r"tt\d{5,12}" if source == "imdb" else r"\d{1,12}"
    if re.fullmatch(pattern, reference):
        identifier = reference
    else:
        parsed = parse.urlsplit(reference)
        hosts = {"imdb.com", "www.imdb.com"} if source == "imdb" else {"movie.douban.com"}
        path = r"/title/(tt\d{5,12})/?" if source == "imdb" else r"/subject/(\d{1,12})/?"
        match = re.fullmatch(path, parsed.path)
        if parsed.scheme not in {"http", "https"} or parsed.hostname not in hosts or parsed.username or not match:
            raise MetadataError(f"Invalid {source} work ID/URL: {reference}")
        identifier = match[1]
    if source == "imdb":
        return f"https://www.imdb.com/title/{identifier}/"
    return f"https://movie.douban.com/subject/{identifier}/"


def normalized_title(value: str) -> str:
    value = unicodedata.normalize("NFKC", value).casefold()
    return "".join(char for char in value if char.isalnum())


def season_of(value: str) -> int | None:
    match = re.search(r"(?:\bseason\s*|\bs)(\d{1,3})\b", value, re.I)
    if match:
        return int(match[1])
    match = re.search(r"第([\d一二三四五六七八九十]+)季", value)
    if not match:
        return None
    number = match[1]
    if number.isdigit():
        return int(number)
    digits = dict(zip("一二三四五六七八九", range(1, 10)))
    if "十" in number:
        tens, ones = number.split("十", 1)
        return digits.get(tens, 1) * 10 + digits.get(ones, 0)
    return digits.get(number)


def without_season(value: str) -> str:
    value = re.sub(r"第[\d一二三四五六七八九十]+季", "", value)
    return re.sub(r"\bseason\s*\d+\b", "", value, flags=re.I).strip()


def filename_hints(filename: str) -> dict[str, Any]:
    stem = Path(filename).stem
    result: dict[str, Any] = {}
    imdb = re.search(r"\btt\d{5,12}\b", stem, re.I)
    if imdb:
        result["imdb"] = imdb[0].lower()
    episode = re.search(r"(?i)(?:^|[\W_])s(\d{1,3})[ ._-]*e(\d{1,4})(?:[\W_]|$)", stem)
    if episode:
        result.update(season=int(episode[1]), episode=int(episode[2]), media_type="tv")
    # Cut at an episode, year, or common release marker instead of guessing plot.
    marker = re.search(
        r"(?i)(?:^|[\W_])(?:s\d{1,3}[ ._-]*e\d{1,4}|(?:19|20)\d{2}|"
        r"(?:480|576|720|1080|2160)[pi]|4k|uhd|bluray|blu-ray|bdrip|brrip|"
        r"web[ ._-]?(?:dl|rip)|hdtv|remux|x26[45]|h[ ._-]?26[45]|hevc|av1)(?:[\W_]|$)", stem,
    )
    cleaned = stem[:marker.start()] if marker else stem
    cleaned = re.sub(r"[\[{][^\]}]*[\]}]", " ", cleaned)
    cleaned = re.sub(r"[._]+", " ", cleaned).strip(" -()[]{}")
    result["title"] = cleaned or stem
    if not episode:
        year = year_of(stem)
        if year:
            result["year"] = year
    return result


class RestrictedRedirect(request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        parsed = parse.urlsplit(newurl)
        if parsed.scheme != "https" or parsed.hostname not in ALLOWED_HOSTS:
            raise MetadataError("Metadata site redirected to a login, verification or unexpected domain")
        return super().redirect_request(req, fp, code, msg, headers, newurl)




def soup_for(page: str) -> Any:
    try:
        from bs4 import BeautifulSoup
    except ImportError as exc:
        raise MetadataError("Missing beautifulsoup4; install the dependencies from requirements.txt") from exc
    soup = BeautifulSoup(page, "html.parser")
    heading = soup.title.get_text(" ", strip=True).casefold() if soup.title else ""
    if any(word in heading for word in ("captcha", "robot check", "security check", "安全验证", "访问验证", "登录豆瓣")):
        raise MetadataError("Metadata site requires login or bot verification")
    return soup


def movie_jsonld(soup: Any) -> dict[str, Any]:
    for script in soup.find_all("script", attrs={"type": "application/ld+json"}):
        try:
            decoded = json.loads(script.string or script.get_text())
        except (ValueError, TypeError):
            continue
        pending = decoded if isinstance(decoded, list) else [decoded]
        while pending:
            item = pending.pop(0)
            if not isinstance(item, dict):
                continue
            kind = item.get("@type", [])
            kinds = [kind] if isinstance(kind, str) else kind
            if isinstance(kinds, list) and any(k in {"Movie", "TVSeries", "TVEpisode"} for k in kinds):
                return item
            graph = item.get("@graph")
            if isinstance(graph, list):
                pending.extend(graph)
    return {}


def read_imdb_search(page: str) -> list[dict[str, Any]]:
    soup = soup_for(page)
    candidates: dict[str, dict[str, Any]] = {}
    # Find pages contain both poster links and text links to the same title.
    # Prefer text links and keep the year/type within their individual row.
    for link in soup.select('a[href*="/title/tt"]'):
        parsed = parse.urlsplit(link.get("href", ""))
        if parsed.netloc and parsed.hostname not in {"www.imdb.com", "imdb.com"}:
            continue
        identifier = re.fullmatch(r"/title/(tt\d{5,12})/?", parsed.path)
        title = text(link.get_text(" ", strip=True), 200)
        if not identifier or not title or identifier[1] in candidates:
            continue
        row = link.find_parent("li")
        if row is None:
            row = link.find_parent("tr", class_="findResult")
        if row is None:
            row = link.find_parent(attrs={"data-testid": "find-result-item"})
        row_text = text(row.get_text(" ", strip=True), 1200) if row is not None else ""
        # Don't interpret a year in the title itself as its release date.
        metadata_text = row_text.replace(title, "", 1).strip()
        kind = re.search(r"\b(TV Mini Series|TV Series|TV Episode|TV Movie|Movie|Short|Video)\b", metadata_text, re.I)
        candidates[identifier[1]] = {
            "id": identifier[1], "title": title, "aliases": [],
            "year": year_of(metadata_text), "kind": kind[1] if kind else "",
        }
    return list(candidates.values())


def read_imdb(page: str, url: str) -> dict[str, Any]:
    soup = soup_for(page)
    data = movie_jsonld(soup)
    heading = soup.select_one('h1[data-testid="hero__pageTitle"]')
    title = text(data.get("name")) or (text(heading.get_text(" ", strip=True)) if heading else "")
    if not title:
        raise MetadataError("No title found on the IMDb page; access may be restricted or the layout changed")
    plot_node = soup.select_one('[data-testid="plot-xl"], [data-testid="plot-l"], [data-testid="plot-xs"]')
    plot = text(data.get("description")) or (text(plot_node.get_text(" ", strip=True)) if plot_node else "")
    kind = data.get("@type", "")
    if isinstance(kind, list):
        kind = next((k for k in kind if k in {"Movie", "TVSeries", "TVEpisode"}), "")
    result: dict[str, Any] = {
        "source": "imdb", "provider": "imdb_web", "url": url, "id": re.search(r"tt\d+", url)[0],
        "title": title, "year": year_of(data.get("datePublished", "")),
        "media_type": "tv" if kind in {"TVSeries", "TVEpisode"} else "movie" if kind == "Movie" else "auto",
        "plot": plot, "genres": names(data.get("genre")),
        "directors": names(data.get("director")), "creators": names(data.get("creator")),
        "cast": [{"actor": name} for name in names(data.get("actor"))],
    }
    cast = []
    for item in soup.select('[data-testid="title-cast-item"]')[:20]:
        actor = item.select_one('[data-testid="title-cast-item__actor"]')
        roles = item.select('[data-testid="cast-item-characters-link"]')
        if not roles:
            roles = item.select('[data-testid="title-cast-item__characters"]')
        if actor:
            credit = {"actor": text(actor.get_text(" ", strip=True), 160)}
            characters = list(dict.fromkeys(text(role.get_text(" ", strip=True), 160) for role in roles))
            if any(characters):
                credit["characters"] = [name for name in characters if name][:6]
            if credit["actor"]:
                cast.append(credit)
    if cast:
        result["cast"] = cast
    return result


def read_douban(page: str, url: str) -> dict[str, Any]:
    soup = soup_for(page)
    data = movie_jsonld(soup)
    heading = soup.select_one('h1 span[property="v:itemreviewed"]')
    title = text(heading.get_text(" ", strip=True)) if heading else text(data.get("name"))
    if not title:
        raise MetadataError("No title found on the Douban page; access may be restricted or the layout changed")
    summary = soup.select_one('#link-report-intra .all.hidden, #link-report .all.hidden')
    if summary is None:
        summary = soup.select_one('span[property="v:summary"]')
    info = soup.select_one("#info")
    info_text = text(info.get_text(" ", strip=True), 6000) if info else ""
    def field(label: str) -> str:
        labels = "导演|编剧|主演|类型|制片国家/地区|语言|上映日期|首播|片长|单集片长|集数|又名|IMDb|季数|官方网站"
        found = re.search(r"(?:^|\s)" + re.escape(label) + r"\s*[:：]\s*(.*?)(?=\s(?:" + labels + r")\s*[:：]|$)", info_text)
        return found[1].strip() if found else ""
    year_node = soup.select_one("h1 .year")
    year = year_of(year_node.get_text()) if year_node else year_of(data.get("datePublished", ""))
    imdb = re.search(r"\btt\d{5,12}\b", info_text)
    result: dict[str, Any] = {
        "source": "douban", "url": url, "id": re.search(r"/subject/(\d+)", url)[1],
        "title": title, "year": year,
        "media_type": "tv" if field("集数") or field("首播") else "movie",
        "plot": text(summary.get_text(" ", strip=True)) if summary else text(data.get("description")),
        "genres": [text(item.get_text(), 80) for item in soup.select('span[property="v:genre"]')][:12],
        "directors": [text(item.get_text(), 160) for item in soup.select('a[rel="v:directedBy"]')][:10],
        "cast": [{"actor": text(item.get_text(), 160)} for item in soup.select('a[rel="v:starring"]')][:20],
        "aliases": [name.strip() for name in field("又名").split("/") if name.strip()][:12],
        "countries": field("制片国家/地区"), "languages": field("语言"),
    }
    if not result["genres"]:
        result["genres"] = names(data.get("genre"))
    if not result["directors"]:
        result["directors"] = names(data.get("director"))
    if not result["cast"]:
        result["cast"] = [{"actor": name} for name in names(data.get("actor"))]
    if imdb:
        result["imdb_id"] = imdb[0]
    season = season_of(title)
    if season is not None:
        result["season"] = season
    return result


class MetadataResolver:
    def __init__(self, cache_dir: Path, *, timeout: float, cache_days: float,
                 offline: bool, refresh: bool):
        self.cache_dir = cache_dir / "media"
        self.timeout = timeout
        self.ttl = cache_days * 86400
        self.offline = offline
        self.refresh = refresh
        self.memory: dict[str, Any] = {}
        self.failures: set[str] = set()
        self.opener = request.build_opener(RestrictedRedirect())
        self.last_request = 0.0
        self.lock = threading.Lock()

    def key(self, value: str) -> str:
        return hashlib.sha256(("metadata-v1:" + value).encode("utf-8")).hexdigest()

    def cached(self, key: str) -> Any | None:
        if key in self.memory:
            return self.memory[key]
        if self.refresh and not self.offline:
            return None
        path = self.cache_dir / f"{key}.json"
        try:
            record = json.loads(path.read_text(encoding="utf-8"))
            if not self.offline and time.time() - record["saved_at"] > self.ttl:
                return None
            value = record["data"]
            if not isinstance(value, (dict, list)):
                return None
            self.memory[key] = value
            return value
        except (OSError, ValueError, KeyError, TypeError):
            return None

    def save(self, key: str, value: Any) -> None:
        self.memory[key] = value
        temporary = None
        try:
            self.cache_dir.mkdir(parents=True, exist_ok=True)
            with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=self.cache_dir,
                                             prefix=".metadata-", suffix=".tmp", delete=False) as file:
                temporary = Path(file.name)
                json.dump({"saved_at": time.time(), "data": value}, file, ensure_ascii=False)
            temporary.replace(self.cache_dir / f"{key}.json")
        except OSError as exc:
            LOG.warning("Cannot write metadata cache: %s", exc)
        finally:
            if temporary is not None:
                try:
                    temporary.unlink(missing_ok=True)
                except OSError:
                    pass

    def fetch(self, url: str, progress: Any) -> str:
        if self.offline:
            raise MetadataError("Offline mode has no cached metadata for this work")
        parsed = parse.urlsplit(url)
        if parsed.scheme != "https" or parsed.hostname not in ALLOWED_HOSTS:
            raise MetadataError("Metadata may only be fetched from IMDb and Douban domains")
        interval = 1 - (time.monotonic() - self.last_request)
        if interval > 0:
            time.sleep(interval)
        progress.update(detail=f"fetching metadata: {url}", emit=True)
        self.last_request = time.monotonic()
        req = request.Request(url, headers={
            "User-Agent": "llmsrt/0.2.0 (subtitle background metadata)",
            "Accept": "text/html,application/json", "Accept-Language": "zh-CN,en;q=0.8",
        })
        try:
            with self.opener.open(req, timeout=self.timeout) as response:
                raw = response.read(6 * 1024 * 1024 + 1)
                if len(raw) > 6 * 1024 * 1024:
                    raise MetadataError("Metadata page exceeds the size limit")
                if response.headers.get("Content-Encoding", "").lower() == "gzip":
                    raw = gzip.decompress(raw)
                encoding = response.headers.get_content_charset() or "utf-8"
                return raw.decode(encoding, errors="replace")
        except error.HTTPError as exc:
            raise MetadataError(f"Metadata site HTTP {exc.code}; skipping restricted access, no bypass attempted") from None
        except (error.URLError, OSError, TimeoutError, HTTPException, LookupError, EOFError) as exc:
            raise MetadataError(f"Cannot read metadata site: {exc}") from exc

    def search(self, source: str, title: str, progress: Any) -> list[dict[str, Any]]:
        cache_source = "imdb-html-v1" if source == "imdb" else source
        key = self.key(f"search:{cache_source}:{title}")
        cached = self.cached(key)
        if isinstance(cached, list):
            return cached
        if source == "imdb":
            url = "https://www.imdb.com/find/?" + parse.urlencode({"q": title, "s": "tt"})
            candidates = read_imdb_search(self.fetch(url, progress))
            self.save(key, candidates)
            return candidates
        url = "https://movie.douban.com/j/subject_suggest?" + parse.urlencode({"q": title})
        try:
            data = json.loads(self.fetch(url, progress))
        except ValueError as exc:
            raise MetadataError(f"{source} search returned non-JSON; bot verification may be required") from exc
        items = data
        if not isinstance(items, list):
            raise MetadataError(f"{source} search data layout has changed")
        candidates = []
        for item in items[:30]:
            if not isinstance(item, dict):
                continue
            identifier = str(item.get("id", ""))
            if not re.fullmatch(r"\d{1,12}", identifier):
                continue
            candidate = {
                "id": identifier, "title": text(item.get("title"), 200),
                "aliases": names(item.get("sub_title"), 4),
                "year": year_of(item.get("year", "")),
                "kind": str(item.get("qid", item.get("q", ""))),
            }
            if candidate["title"]:
                candidates.append(candidate)
        self.save(key, candidates)
        return candidates

    @staticmethod
    def select(candidates: list[dict[str, Any]], title: str, year: int | None,
               media_type: str, season: int | None) -> str:
        title_key = normalized_title(without_season(title))
        matches: dict[str, tuple[int, dict[str, Any]]] = {}
        for item in candidates:
            options = [item["title"], *item.get("aliases", [])]
            if not any(normalized_title(without_season(name)) == title_key for name in options):
                continue
            if year and item.get("year") and item["year"] != year:
                continue
            item_season = season_of(item["title"])
            if season is not None and item_season is not None and season != item_season:
                continue
            kind = item.get("kind", "").casefold()
            known_tv = kind in {"tvseries", "tvminiseries", "tvepisode", "tv series", "tv mini series", "tv episode"}
            known_movie = kind in {"movie", "feature", "tvmovie", "tv movie", "short", "video"}
            if media_type == "movie" and known_tv or media_type == "tv" and known_movie:
                continue
            score = 10 + (4 if year and item.get("year") == year else 0)
            score += 3 if season is not None and item_season == season else 0
            score += 1 if (media_type == "tv" and known_tv or media_type == "movie" and known_movie) else 0
            matches[item["id"]] = (score, item)
        if not matches:
            raise MetadataError(f"No unique match for '{title}'; give an exact title, year, or ID/URL")
        best = max(score for score, _ in matches.values())
        selected = [item for score, item in matches.values() if score == best]
        if len(selected) != 1:
            options = "; ".join(f"{item['title']} ({item.get('year') or '?'}) ID={item['id']}" for item in selected[:5])
            raise MetadataError(f"Ambiguous same-named works: {options}; give a year, season, or ID/URL")
        return selected[0]["id"]

    def detail(self, source: str, reference: str, progress: Any) -> dict[str, Any]:
        url = canonical_url(source, reference)
        key = self.key(url)
        cached = self.cached(key)
        if isinstance(cached, dict) and cached.get("source") == source and cached.get("url") == url and cached.get("title"):
            progress.update(detail=f"using cached {source} metadata: {cached['title']}", emit=True)
            return cached
        page = self.fetch(url, progress)
        result = read_imdb(page, url) if source == "imdb" else read_douban(page, url)
        self.save(key, result)
        return result


    def enrich(self, context: dict[str, Any], args: Any, progress: Any) -> dict[str, Any]:
        if not args.metadata:
            return context
        progress.set_stage("waiting for show background")
        # Share the successful and failed lookups across concurrent episodes;
        # serialize catalog requests to preserve the site's request interval.
        while not self.lock.acquire(timeout=0.2):
            progress.check_cancelled()
        try:
            progress.check_cancelled()
            return self._enrich(context, args, progress)
        finally:
            self.lock.release()

    def _enrich(self, context: dict[str, Any], args: Any, progress: Any) -> dict[str, Any]:
        progress.set_stage("fetching show background", detail="searching IMDb/Douban for synopsis, genres and credits")
        hints = filename_hints(context["video_filename"])
        title = args.title or hints["title"]
        year = args.year or hints.get("year")
        season = args.season if args.season is not None else hints.get("season")
        kind = args.media_type if args.media_type != "auto" else hints.get("media_type", "auto")
        references = {"imdb": args.imdb or hints.get("imdb"), "douban": args.douban}
        records = []
        # Explicit links (including an IMDb ID embedded in the filename) are
        # resolved before name searches so they can identify the work precisely.
        sources = sorted(args.metadata_sources, key=lambda source: 0 if references[source] else 1)
        for source in sources:
            reference = references[source]
            # A Douban page's explicit IMDb link gives an unambiguous cross-site ID.
            if source == "imdb" and not reference:
                reference = next((r["imdb_id"] for r in records if r.get("imdb_id")), None)
            memo = json.dumps([source, reference, title, year, season, kind], ensure_ascii=False)
            if memo in self.failures:
                continue
            try:
                if not reference:
                    candidates = self.search(source, title, progress)
                    reference = self.select(candidates, title, year, kind, season)
                record = self.detail(source, reference, progress)
                if not references[source] and not (source == "imdb" and any(r.get("imdb_id") == record["id"] for r in records)):
                    valid_titles = [record["title"], *record.get("aliases", [])]
                    # Search suggestion aliases may be the English title when the
                    # Douban detail page presents a combined Chinese/English title.
                    if source == "imdb" and not any(normalized_title(without_season(t)) == normalized_title(without_season(title)) for t in valid_titles):
                        raise MetadataError("Search entry title does not match the IMDb detail page")
                    if year and record.get("year") and year != record["year"]:
                        raise MetadataError("Search entry year does not match the detail page")
                    if season is not None and record.get("season") is not None and season != record["season"]:
                        raise MetadataError("Search entry season does not match the Douban detail page")
                other_imdb = next((r.get("imdb_id") or (r["id"] if r["source"] == "imdb" else None) for r in records), None)
                record_imdb = record.get("imdb_id") or (record["id"] if source == "imdb" else None)
                if other_imdb and record_imdb and other_imdb != record_imdb:
                    raise MetadataError("IMDb and Douban IDs disagree; skipping the conflicting source")
                records.append(record)
                if references[source] and not args.title:
                    title = record["title"]
                    if year is None:
                        year = record.get("year")
                label = "IMDb" if source == "imdb" else "Douban"
                LOG.info("Fetched %s metadata: %s (%s) %s", source, record["title"], record.get("year") or "?", record["url"],
                         extra={"display_message": f"{label}: {record['title']} ({record.get('year') or '?'})"})
            except (MetadataError, ValueError, TypeError, KeyError, AttributeError) as exc:
                self.failures.add(memo)
                label = "IMDb" if source == "imdb" else "Douban"
                LOG.warning("%s metadata unavailable: %s; continuing with other sources or the manual background", source, exc,
                            extra={"optional_notice": True})
        # If IMDb name search failed, a subsequent Douban page may provide an
        # exact IMDb ID. Read that title page directly without another search.
        linked_id = next((r.get("imdb_id") for r in records if r.get("imdb_id")), None)
        if linked_id and "imdb" in sources and not any(r["source"] == "imdb" for r in records) and not args.imdb:
            try:
                record = self.detail("imdb", linked_id, progress)
                if record["id"] == linked_id:
                    records.append(record)
                    LOG.info("Fetched IMDb metadata via the Douban-linked ID: %s", record["title"])
            except (MetadataError, ValueError, TypeError, KeyError, AttributeError) as exc:
                LOG.warning("Douban-linked IMDb metadata unavailable: %s", exc,
                            extra={"optional_notice": True})
        enriched = dict(context)
        if records:
            enriched["catalog_metadata"] = records
            if not args.title:
                enriched["title"] = records[0]["title"]
                enriched["title_source"] = records[0]["source"]
            if enriched["media_type"] == "auto":
                enriched["media_type"] = next((r["media_type"] for r in records if r["media_type"] != "auto"), kind)
        for key in ("season", "episode"):
            if key not in enriched and key in hints:
                enriched[key] = hints[key]
        return enriched
