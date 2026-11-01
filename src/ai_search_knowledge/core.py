from __future__ import annotations

import hashlib
import ipaddress
import json
import re
import socket
import threading
import time
import calendar
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit
from urllib.robotparser import RobotFileParser
from zoneinfo import ZoneInfo

import httpx

ROOT = Path(__file__).resolve().parents[2]
CHANNEL_ID = "UCIgnGlGkVRhd4qNFcEwLL4A"
URL_RE = re.compile(r"https?://[^\s<>\"\u200b]+")
CHAPTER_RE = re.compile(r"^\s*(\d{1,2}:\d{2}(?::\d{2})?)\s+(.+?)\s*$")


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def digest(value: str | bytes) -> str:
    return hashlib.sha256(value.encode() if isinstance(value, str) else value).hexdigest()


def save(path: Path, value: dict | list) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n")
    tmp.replace(path)


def read(path: Path, default=None):
    return json.loads(path.read_text()) if path.exists() else default


def config(root: Path = ROOT) -> dict:
    return read(root / "config.json")


def canonical_url(url: str) -> str:
    url = url.rstrip(".,;!")
    p = urlsplit(url)
    host = (p.hostname or "").lower()
    if host in {"youtube.com", "www.youtube.com"} and p.path == "/redirect":
        q = dict(parse_qsl(p.query))
        return canonical_url(q.get("q") or q.get("url") or urlunsplit((p.scheme, p.netloc, p.path, "", "")))
    tracking = {'fbclid', 'gclid'}
    if host in {'youtube.com', 'www.youtube.com', 'youtu.be'}:
        tracking |= {'si', 'feature'}
    query = [(k, v) for k, v in parse_qsl(p.query, keep_blank_values=True)
             if not k.lower().startswith("utm_") and k not in tracking]
    return urlunsplit((p.scheme.lower(), p.netloc.lower(), p.path or "/", urlencode(query), ""))


def chapter_seconds(timestamp: str) -> int:
    result = 0
    for part in timestamp.split(":"):
        result = result * 60 + int(part)
    return result


def description_parts(text: str) -> tuple[list[dict], list[dict]]:
    chapters, links = [], []
    for line_no, line in enumerate(text.splitlines(), 1):
        match = CHAPTER_RE.match(line)
        if match:
            chapters.append({"title": match[2], "start_seconds": chapter_seconds(match[1]),
                             "timestamp": match[1], "description_line": line_no})
        for match in URL_RE.finditer(line):
            original = match[0]
            # A final ')' commonly closes prose, but balanced URL parentheses are retained.
            while original.endswith(")") and original.count(")") > original.count("("):
                original = original[:-1]
            url = canonical_url(original)
            label = (line[:match.start()] + line[match.end():]).strip(" -:•\t")
            label = URL_RE.sub("", label).strip()
            host = (urlsplit(url).hostname or "").removeprefix("www.")
            low = label.lower()
            role = "reference"
            reason = "description link; relevance not yet reviewed"
            if host in {"amzn.to", "amazon.com", "ko-fi.com", "patreon.com"}:
                role, reason = "promotion", "shopping/support link"
            elif host in {"youtu.be", "youtube.com"}:
                role, reason = "related_video", "video reference; audiovisual coverage is separate from document text"
            elif any(s in low for s in ["newsletter", "my equipment", "audio interface", "see my x", "support:", "find ai tools", "lenovo thinkbook", "dell precision", "shure sm7b", "scarlett solo", "nvidia rtx 5000"]):
                role, reason = "channel_resource", "channel/equipment boilerplate"
            elif (host in {"x.com", "twitter.com"} and "/status/" not in urlsplit(url).path) or host in {"aisearch.substack.com", "ai-search.io"}:
                role, reason = "channel_resource", "social/profile or channel resource"
            elif any(s in low for s in ["sponsor", "thanks to", "affiliate", "discount", "promo code"]):
                role, reason = "promotion", "description identifies commercial context"
            if "..." in url or "…" in url:
                role, reason = "unresolved", "description contains a truncated URL"
            links.append({"url": url, "original_url": original, "label": label,
                          "role": role, "role_reason": reason, "description_line": line_no})
    return chapters, links


def extract_json(html: str, variable: str) -> dict:
    match = re.search(r"(?:var\s+)?" + re.escape(variable) + r"\s*=\s*", html)
    if not match:
        raise ValueError(f"{variable} missing; page may be unavailable or require interaction")
    return json.JSONDecoder().raw_decode(html[match.end():])[0]


def parse_video(html: str, video_id: str, expected_channel: str = CHANNEL_ID) -> dict:
    player = extract_json(html, "ytInitialPlayerResponse")
    details = player.get("videoDetails", {})
    micro = player.get("microformat", {}).get("playerMicroformatRenderer", {})
    if details.get("videoId") != video_id or details.get("channelId") != expected_channel:
        raise ValueError("video/channel identity missing or mismatched")
    description = details.get("shortDescription", "")
    chapters, links = description_parts(description)
    return {"id": video_id, "channel_id": details["channelId"], "channel": details.get("author"),
            "title": details.get("title"), "url": f"https://www.youtube.com/watch?v={video_id}",
            "duration_seconds": int(details.get("lengthSeconds", 0)),
            "published_at": micro.get("publishDate"), "uploaded_at": micro.get("uploadDate"),
            "date_evidence": "YouTube playerMicroformatRenderer; original timezone retained",
            "description": description, "description_sha256": digest(description),
            "chapters": chapters, "links": links, "is_shorts_eligible": micro.get("isShortsEligible"),
            "fetched_at": now(), "html_sha256": digest(html), "status": "ok",
            "coverage": "metadata_description_links_only; audiovisual_content_not_reviewed",
            "raw_player_metadata": {"videoDetails": details, "microformat": player.get("microformat")}}


class FetchFailure(Exception):
    def __init__(self, status: str, message: str):
        self.status = status
        super().__init__(message)


class Fetcher:
    """Bounded public HTTP requests, robots checks, per-host spacing, no credentials."""

    def __init__(self, cfg: dict):
        self.cfg = cfg
        self.client = httpx.Client(headers={"User-Agent": cfg["user_agent"]},
                                   timeout=cfg["timeout_seconds"], follow_redirects=False,
                                   limits=httpx.Limits(max_connections=12))
        self._guard = threading.Lock()
        self._hosts: dict[str, threading.Lock] = {}
        self._last: dict[str, float] = {}
        self._robots: dict[str, RobotFileParser | str] = {}
        self._backoff: dict[str, float] = {}

    def close(self):
        self.client.close()

    def _public(self, url: str):
        p = urlsplit(url)
        if p.scheme not in {"http", "https"} or not p.hostname or p.username or p.password or p.port not in {None, 80, 443}:
            raise FetchFailure("unsafe_url", "Only public HTTP(S) URLs on standard ports are fetched")
        for info in socket.getaddrinfo(p.hostname, p.port or (443 if p.scheme == "https" else 80)):
            if not ipaddress.ip_address(info[4][0]).is_global:
                raise FetchFailure("unsafe_url", "Local/private network targets are not fetched")

    def _raw(self, url: str) -> tuple[httpx.Response, bytes]:
        self._public(url)
        host = urlsplit(url).netloc
        with self._guard:
            lock = self._hosts.setdefault(host, threading.Lock())
        with lock:
            if time.monotonic() < self._backoff.get(host, 0):
                raise FetchFailure("host_backoff", "Host requested a temporary request backoff")
            time.sleep(max(0, self.cfg["per_host_delay_seconds"] - (time.monotonic() - self._last.get(host, 0))))
            try:
                with self.client.stream("GET", url) as response:
                    if response.status_code == 429:
                        retry = response.headers.get("retry-after", "60")
                        seconds = float(retry) if retry.isdigit() else 60
                        self._backoff[host] = time.monotonic() + max(60, min(seconds, 86400))
                    if int(response.headers.get("content-length", "0")) > self.cfg["max_response_bytes"]:
                        raise FetchFailure("too_large", "Response exceeds configured size limit")
                    parts, length = [], 0
                    for part in response.iter_bytes():
                        length += len(part)
                        if length > self.cfg["max_response_bytes"]:
                            raise FetchFailure("too_large", "Response exceeds configured size limit")
                        parts.append(part)
                    return response, b"".join(parts)
            finally:
                self._last[host] = time.monotonic()

    def allowed(self, url: str) -> None:
        p = urlsplit(url)
        origin = f"{p.scheme}://{p.netloc}"
        with self._guard:
            cached = self._robots.get(origin)
        if cached is None:
            try:
                robots_url = origin + "/robots.txt"
                for _ in range(6):
                    response, body = self._raw(robots_url)
                    if not response.is_redirect or "location" not in response.headers:
                        break
                    robots_url = str(httpx.URL(robots_url).join(response.headers["location"]))
                if response.status_code in {404, 410}:
                    parser = RobotFileParser(); parser.parse([])
                    cached = parser
                elif response.status_code == 200:
                    parser = RobotFileParser(); parser.parse(body.decode("utf-8", "replace").splitlines())
                    cached = parser
                else:
                    cached = f"robots.txt HTTP {response.status_code}; conservative deferral"
            except Exception as exc:
                cached = f"robots.txt could not be checked: {type(exc).__name__}"
            with self._guard:
                self._robots[origin] = cached
        if isinstance(cached, str):
            raise FetchFailure("robots_unavailable", cached)
        if not cached.can_fetch(self.cfg["user_agent"], url):
            raise FetchFailure("robots_denied", "robots.txt disallows this request")

    def get(self, url: str) -> tuple[str, httpx.Response, bytes]:
        for _ in range(6):
            self.allowed(url)
            response, body = self._raw(url)
            if response.is_redirect:
                if "location" not in response.headers:
                    raise FetchFailure("http_error", "Redirect has no Location")
                url = str(httpx.URL(url).join(response.headers["location"]))
                continue
            if response.status_code != 200:
                raise FetchFailure("rate_limited" if response.status_code == 429 else "http_error", f"HTTP {response.status_code}")
            return url, response, body
        raise FetchFailure("redirect_limit", "Too many redirects")


def due(item: dict | None, days: int) -> bool:
    if not item or not item.get("fetched_at"):
        return True
    return (datetime.now(timezone.utc) - datetime.fromisoformat(item["fetched_at"])).total_seconds() > days * 86400


def needs_fetch(item: dict | None, error: dict | None, success_days: int, retry_days: int) -> bool:
    if error and (not item or datetime.fromisoformat(error["fetched_at"]) > datetime.fromisoformat(item["fetched_at"])):
        return due(error, retry_days)
    return due(item, success_days if item and item.get("status") == "ok" else retry_days)


def inventory(root: Path) -> list[dict]:
    entries = {}
    for tab in config(root)["tabs"]:
        path = root / f"data/raw/channel/{tab}.json"
        channel = read(path) or {}
        for entry in channel.get("entries", []):
            if not entry or not entry.get("id"):
                continue
            key = entry["id"]
            if key not in entries:
                entries[key] = {"id": key, "title": entry.get("title"), "url": entry.get("url"), "tabs": []}
            entries[key]["tabs"].append(path.stem)
    return list(entries.values())


def cutoff(cfg: dict, at: datetime | None = None) -> datetime:
    local = (at or datetime.now(timezone.utc)).astimezone(ZoneInfo(cfg["scope_timezone"]))
    month_index = local.year * 12 + local.month - 1 - cfg["lookback_months"]
    year, month = divmod(month_index, 12)
    month += 1
    day = min(local.day, calendar.monthrange(year, month)[1])
    return datetime(year, month, day, tzinfo=local.tzinfo)


def in_scope(item: dict, cfg: dict) -> bool:
    if item.get("status") != "ok" or not item.get("published_at") or "videos" not in item.get("tabs", []):
        return False
    published = datetime.fromisoformat(item["published_at"])
    return cutoff(cfg) <= published <= datetime.now(timezone.utc)


def collect_videos(root: Path, limit: int = 0, refresh: bool = False) -> dict:
    cfg = config(root)
    items = inventory(root)
    fetcher = Fetcher(cfg)

    def task(entry):
        path = root / f"data/raw/videos/{entry['id']}.json"
        old = read(path)
        try:
            _, _, body = fetcher.get(f"https://www.youtube.com/watch?v={entry['id']}")
            item = parse_video(body.decode("utf-8", "replace"), entry["id"], cfg["channel_id"])
            item["tabs"] = entry["tabs"]
            if old and old.get("status") == "ok" and old.get("description_sha256") != item["description_sha256"]:
                save(root / f"data/history/videos/{entry['id']}/{digest(old['fetched_at'])[:16]}.json", old)
            save(path, item)
            return "ok"
        except Exception as exc:
            failure = {**entry, "fetched_at": now(), "status": getattr(exc, "status", "error"), "error": str(exc)}
            if old and old.get("status") == "ok":
                save(root / f"data/errors/videos/{entry['id']}.json", failure)
            else:
                save(path, failure)
            return failure["status"]

    counts, visited, fetched, consecutive_old, previous_date = {}, [], 0, 0, None
    monotonic, boundary = True, False
    try:
        # /videos is the newest-first tab. Check exact publication dates before
        # scheduling the next request, rather than enqueueing the entire history.
        for entry in items:
            old = read(root / f"data/raw/videos/{entry['id']}.json")
            error = read(root / f"data/errors/videos/{entry['id']}.json")
            if refresh or needs_fetch(old, error, cfg["metadata_recheck_days"], cfg["retry_days"]):
                if limit and fetched >= limit:
                    break
                status = task(entry); fetched += 1
                counts[status] = counts.get(status, 0) + 1
            item = read(root / f"data/raw/videos/{entry['id']}.json") or {}
            visited.append(entry["id"])
            if item.get("status") == "ok" and item.get("published_at"):
                published = datetime.fromisoformat(item["published_at"])
                if previous_date and published > previous_date:
                    monotonic = False
                previous_date = published
                consecutive_old = consecutive_old + 1 if published < cutoff(cfg) else 0
            else:
                consecutive_old = 0
            if len(visited) % 10 == 0:
                print(json.dumps({"phase": "videos", "visited": len(visited), "fetched": fetched, "results": counts}), flush=True)
            if monotonic and consecutive_old >= 3:
                boundary = True
                break
    finally:
        fetcher.close()
    result = {"inventory": len(items), "visited": len(visited), "fetched": fetched, "results": counts,
              "fetched_at": now(), "cutoff": cutoff(cfg).isoformat(), "tabs": cfg["tabs"],
              "newest_first_verified_in_visited": monotonic, "boundary_reached": boundary,
              "method": "newest-first Videos traversal; stop after three exact dates older than cutoff when visited dates remain monotonic",
              "visited_ids": visited}
    save(root / "data/metadata-run.json", result)
    return result
