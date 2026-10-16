"""Shared helpers for the research engine: contract loading, JSONL ledger, HTTP with throttle and cache."""
import datetime
import hashlib
import html
import json
import os
import re
import time
import urllib.error
import urllib.request
from pathlib import Path

SKILL_DIR = Path(__file__).resolve().parent.parent
CONTRACT_PATH = SKILL_DIR / "contract" / "contract.json"
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"


def load_contract():
    return json.loads(CONTRACT_PATH.read_text(encoding="utf-8"))


def now_iso():
    return datetime.datetime.now(datetime.timezone.utc).replace(microsecond=0).isoformat()


def table_path(project_dir, table, contract=None):
    contract = contract or load_contract()
    return Path(project_dir) / contract["tables"][table]["file"]


def read_jsonl(path):
    path = Path(path)
    if not path.exists():
        return []
    rows = []
    for n, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        line = line.strip()
        if not line:
            continue
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError as e:
            raise SystemExit(f"{path}:{n}: invalid JSON: {e}")
    return rows


def append_jsonl(path, rows):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")


def write_jsonl(path, rows):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows), encoding="utf-8")
    os.replace(tmp, path)


def next_id(rows, key, prefix, width=4):
    n = 0
    for r in rows:
        m = re.match(re.escape(prefix) + r"(\d+)$", str(r.get(key, "")))
        if m:
            n = max(n, int(m.group(1)))
    return f"{prefix}{n + 1:0{width}d}"


def norm_text(s):
    """Normalisation used for verbatim span checks: unify quotes, dashes and whitespace, keep words and case."""
    s = html.unescape(s or "")
    s = s.replace("’", "'").replace("‘", "'").replace("“", '"').replace("”", '"')
    s = s.replace("—", "-").replace("–", "-").replace(" ", " ")
    return re.sub(r"\s+", " ", s).strip()


def span_in(span, text):
    span_n = norm_text(span)
    return bool(span_n) and span_n in norm_text(text)


def text_hash(s):
    return hashlib.sha1(norm_text(s).encode("utf-8")).hexdigest()[:12]


def author_key(platform, name):
    if not name:
        return "UNKNOWN"
    return hashlib.sha1(f"{platform}:{name.lower()}".encode("utf-8")).hexdigest()[:10]


class Fetcher:
    """HTTP GET with per-host minimum interval, on-disk cache and backoff on 429/5xx.

    Reddit rate-limits anonymous RSS. A cached response is reused so reruns do not spend the budget.
    """

    def __init__(self, cache_dir=None, min_interval=None, max_retries=5):
        self.cache_dir = Path(cache_dir) if cache_dir else None
        self.min_interval = min_interval or {"www.reddit.com": 7.0, "arctic-shift.photon-reddit.com": 2.0}
        self.max_retries = max_retries
        self.last = {}
        self.next_allowed = {}
        self.log = []
        self.state_path = self.cache_dir / "rate_state.json" if self.cache_dir else None
        if self.state_path and self.state_path.exists():
            try:
                state = json.loads(self.state_path.read_text())
                self.last = state.get("last", {})
                self.next_allowed = state.get("next_allowed", {})
            except (ValueError, OSError):
                pass

    def _save_state(self):
        if self.state_path:
            self.state_path.parent.mkdir(parents=True, exist_ok=True)
            self.state_path.write_text(json.dumps({"last": self.last, "next_allowed": self.next_allowed}))

    def _wait(self, host):
        gap = self.min_interval.get(host, 1.0)
        target = max(self.last.get(host, 0) + gap, self.next_allowed.get(host, 0))
        if time.time() < target:
            wait = target - time.time()
            if wait > 5:
                print(f"  rate limit on {host}: waiting {wait:.0f}s", flush=True)
            time.sleep(wait)
        self.last[host] = time.time()

    def _note_limits(self, host, headers):
        """Reddit sends x-ratelimit-remaining / x-ratelimit-reset. From cloud IPs the budget is about 1 request per minute."""
        try:
            remaining = float(headers.get("x-ratelimit-remaining", "1"))
            reset = float(headers.get("x-ratelimit-reset", "0"))
        except (TypeError, ValueError):
            return
        if remaining < 1:
            self.next_allowed[host] = time.time() + reset + 2
        self._save_state()

    def get(self, url, use_cache=True, max_age_hours=24):
        host = re.sub(r"^https?://([^/]+).*$", r"\1", url)
        cpath = None
        if self.cache_dir and use_cache:
            cpath = self.cache_dir / (hashlib.sha1(url.encode()).hexdigest() + ".cache")
            if cpath.exists() and time.time() - cpath.stat().st_mtime < max_age_hours * 3600:
                return 200, cpath.read_text(encoding="utf-8"), True
        delay = 30
        status = None
        for attempt in range(self.max_retries + 1):
            self._wait(host)
            try:
                req = urllib.request.Request(url, headers={"User-Agent": UA})
                with urllib.request.urlopen(req, timeout=45) as r:
                    body = r.read().decode("utf-8", errors="replace")
                    status = r.status
                    self._note_limits(host, r.headers)
                self.log.append((url, status))
                if cpath:
                    cpath.parent.mkdir(parents=True, exist_ok=True)
                    cpath.write_text(body, encoding="utf-8")
                return status, body, False
            except urllib.error.HTTPError as e:
                status = e.code
                self.log.append((url, status))
                self._note_limits(host, e.headers)
                if status in (429, 500, 502, 503, 504) and attempt < self.max_retries:
                    if host in self.next_allowed and self.next_allowed[host] > time.time():
                        print(f"  HTTP {status} on {host}, retry after reset (attempt {attempt + 1})", flush=True)
                    else:
                        retry_after = e.headers.get("Retry-After")
                        wait = int(retry_after) if retry_after and retry_after.isdigit() else delay
                        print(f"  HTTP {status} on {host}, waiting {wait}s (attempt {attempt + 1})", flush=True)
                        time.sleep(wait)
                        delay = min(delay * 2, 300)
                    continue
                return status, "", False
            except (urllib.error.URLError, TimeoutError) as e:
                self.log.append((url, str(e)))
                if attempt < self.max_retries:
                    time.sleep(10)
                    continue
                return None, "", False
        return status, "", False
