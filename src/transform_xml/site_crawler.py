"""Site crawler module (#1 サイト巡回PG)."""

import argparse
import csv
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from html.parser import HTMLParser
from pathlib import Path

# 地方公共団体コード県の定義 (00: 総務省, 01〜47: 都道府県)
VALID_PREF_CODES = {f"{i:02d}" for i in range(48)}

PDF_LINKS_FILE_NAME = "pdf_links.csv"
DEFAULT_OUTPUT_DIR = r"C:\transfer-xml"
DEFAULT_CONFIG_PATH = Path("config") / "site_crawler_config.json"
MAX_CRAWL_DEPTH = 7
DEFAULT_SLEEP_SEC = 0.5


@dataclass
class ExtractedLink:
    """Represents an extracted hyperlink."""

    url: str
    label: str
    is_pdf: bool


def validate_pref_code(pref_code: str) -> str:
    """Validate prefecture code (00-47).

    Args:
        pref_code: 2-digit prefecture code or integer string.

    Returns:
        Formatted 2-digit prefecture code ("00" - "47").

    Raises:
        ValueError: If pref_code is invalid.
    """
    code = pref_code.strip()
    if code.isdigit() and len(code) <= 2:
        code = f"{int(code):02d}"

    if code not in VALID_PREF_CODES:
        raise ValueError(
            f"起動条件不正: 地方公共団体コード県は 00〜47 を指定してください (入力値: '{pref_code}')"
        )
    return code


def sanitize_dir_name(label: str) -> str:
    """Sanitize directory name according to specifications (#1-e / ユーザー要件2).

    Replaces invalid directory characters (\\/:*?\"<>|) and control characters with '=X'.
    """
    if not label:
        return "unnamed"

    # Windows/POSIX prohibited characters: \ / : * ? " < > |
    sanitized = re.sub(r'[\\/:*?"<>|]', "=X", label)
    # Control characters
    sanitized = re.sub(r"[\x00-\x1f]", "=X", sanitized)
    # Windows doesn't allow trailing dots or spaces in folder names
    sanitized = sanitized.strip(" .")
    return sanitized if sanitized else "unnamed"


def load_env_file(env_path: Path) -> dict[str, str]:
    """Parse a simple KEY=VALUE env file."""
    env_vars: dict[str, str] = {}
    if not env_path.is_file():
        return env_vars

    with open(env_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if "=" in line:
                key, val = line.split("=", 1)
                env_vars[key.strip()] = val.strip().strip("'\"")
    return env_vars


def resolve_output_dir(env_file_path: Path | None = None) -> Path:
    """Resolve artifact output directory from env files or environment variables."""
    # 1. Check specified env file
    if env_file_path and env_file_path.is_file():
        vars_dict = load_env_file(env_file_path)
        if "OUTPUT_DIR" in vars_dict and vars_dict["OUTPUT_DIR"]:
            return Path(vars_dict["OUTPUT_DIR"])

    # 2. Check candidate env files
    candidate_paths = [
        Path("config") / "settings.env",
        Path(".env"),
        Path("config") / ".env",
    ]
    for p in candidate_paths:
        if p.is_file():
            vars_dict = load_env_file(p)
            if "OUTPUT_DIR" in vars_dict and vars_dict["OUTPUT_DIR"]:
                return Path(vars_dict["OUTPUT_DIR"])

    # 3. Check os.environ
    if "OUTPUT_DIR" in os.environ and os.environ["OUTPUT_DIR"]:
        return Path(os.environ["OUTPUT_DIR"])

    # 4. Fallback default
    return Path(DEFAULT_OUTPUT_DIR)


def load_crawler_config(config_path: Path | None = None) -> dict[str, dict[str, str]]:
    """Load site crawler JSON config file."""
    target_path = config_path or DEFAULT_CONFIG_PATH
    if not target_path.is_file():
        raise FileNotFoundError(f"サイト巡回設定ファイルが見つかりません: {target_path}")

    with open(target_path, "r", encoding="utf-8") as f:
        return json.load(f)


def get_pref_target(pref_code: str, config: dict[str, dict[str, str]]) -> dict[str, str]:
    """Retrieve target configuration for the given prefecture code."""
    valid_code = validate_pref_code(pref_code)
    if valid_code not in config:
        raise KeyError(
            f"設定ファイルに地方公共団体コード '{valid_code}' の設定が存在しません"
        )
    return config[valid_code]


def fetch_html(
    url: str,
    timeout: float = 15.0,
    user_agent: str = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) transform-xml/0.1.0",
) -> str:
    """Fetch HTML content from URL with automatic charset decoding."""
    req = urllib.request.Request(url, headers={"User-Agent": user_agent})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        content = resp.read()
        charset = resp.headers.get_content_charset()

    candidates: list[str] = []
    if charset:
        candidates.append(charset)
    candidates.extend(["utf-8", "cp932", "shift_jis", "euc-jp"])

    for enc in candidates:
        try:
            return content.decode(enc)
        except (UnicodeDecodeError, LookupError):
            continue

    return content.decode("utf-8", errors="replace")


def extract_section_html(html: str, start_key: str, end_key: str) -> str:
    """Extract HTML snippet between start_key and end_key (#1-d).

    Prioritizes searching after main content markers to skip global header navigation.
    """
    search_start = 0
    # Markers indicating the start of actual body content
    for marker in [
        "<!-- 本文 -->",
        "<main",
        'id="container"',
        'id="content"',
        'id="main"',
        "<body",
        "</head>",
    ]:
        pos = html.find(marker)
        if pos != -1:
            search_start = pos
            break

    idx1 = html.find(start_key, search_start)
    if idx1 == -1:
        # Fallback to searching from document start
        idx1 = html.find(start_key)

    if idx1 == -1:
        return ""

    idx2 = html.find(end_key, idx1 + len(start_key))
    if idx2 == -1:
        return ""

    return html[idx1:idx2]


class _SectionLinkParser(HTMLParser):
    """HTML parser to extract hyperlinks and their anchor labels."""

    def __init__(self) -> None:
        super().__init__()
        self.raw_links: list[tuple[str, str]] = []
        self._current_href: str | None = None
        self._current_text: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.lower() == "a":
            self._current_href = None
            self._current_text = []
            for k, v in attrs:
                if k.lower() == "href" and v is not None:
                    self._current_href = v
        elif tag.lower() == "img" and self._current_href is not None:
            # If an image is inside <a>, check alt attribute for fallback label
            for k, v in attrs:
                if k.lower() == "alt" and v:
                    self._current_text.append(v)

    def handle_data(self, data: str) -> None:
        if self._current_href is not None:
            self._current_text.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() == "a" and self._current_href is not None:
            label = "".join(self._current_text).strip()
            self.raw_links.append((self._current_href, label))
            self._current_href = None
            self._current_text = []


def extract_links_from_section(
    base_url: str,
    section_html: str,
    root_host: str,
) -> tuple[list[ExtractedLink], list[ExtractedLink]]:
    """Parse section HTML and extract PDF links and page links.

    Filters by domain restriction (root_host) and ignores jump anchors (#...).
    """
    parser = _SectionLinkParser()
    parser.feed(section_html)

    pdf_links: list[ExtractedLink] = []
    page_links: list[ExtractedLink] = []

    seen_urls: set[str] = set()

    for raw_href, raw_label in parser.raw_links:
        href = raw_href.strip()
        if not href or href.startswith("#") or href.startswith("javascript:") or href.startswith("mailto:"):
            continue

        full_url = urllib.parse.urljoin(base_url, href)
        parsed = urllib.parse.urlsplit(full_url)

        # 巡回範囲制限: ルートホストと一致するもののみ巡回
        if parsed.netloc.lower() != root_host.lower():
            continue

        # Normalize URL (remove fragment)
        clean_url = urllib.parse.urlunsplit((parsed.scheme, parsed.netloc, parsed.path, parsed.query, ""))
        if clean_url in seen_urls:
            continue
        seen_urls.add(clean_url)

        label = raw_label or Path(parsed.path).name or "link"
        path_lower = parsed.path.lower()

        if path_lower.endswith(".pdf"):
            pdf_links.append(ExtractedLink(url=clean_url, label=label, is_pdf=True))
        else:
            # Check if this is an HTML / page link
            ext = Path(parsed.path).suffix.lower()
            if ext in ["", ".htm", ".html", ".php", ".asp", ".aspx", ".shtml"]:
                page_links.append(ExtractedLink(url=clean_url, label=label, is_pdf=False))

    return pdf_links, page_links


def save_pdf_links_file(directory: Path, pdf_links: list[ExtractedLink]) -> Path:
    """Save PDF links to pdf_links.csv in the specified directory (#1-d, #1-e)."""
    directory.mkdir(parents=True, exist_ok=True)
    target_path = directory / PDF_LINKS_FILE_NAME

    # Read existing links if file already exists to preserve and deduplicate
    existing_map: dict[str, str] = {}
    if target_path.is_file():
        try:
            with open(target_path, "r", encoding="utf-8", newline="") as f:
                reader = csv.reader(f)
                header = next(reader, None)
                for row in reader:
                    if len(row) >= 2:
                        existing_map[row[0]] = row[1]
        except Exception:
            pass

    for link in pdf_links:
        existing_map[link.url] = link.label

    with open(target_path, "w", encoding="utf-8", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["url", "label"])
        for url, label in existing_map.items():
            writer.writerow([url, label])

    return target_path


class CrawlerContext:
    """State tracking for crawler execution."""

    def __init__(
        self,
        root_host: str,
        start_key: str,
        end_key: str,
        max_depth: int = MAX_CRAWL_DEPTH,
        sleep_sec: float = DEFAULT_SLEEP_SEC,
    ) -> None:
        self.root_host = root_host
        self.start_key = start_key
        self.end_key = end_key
        self.max_depth = max_depth
        self.sleep_sec = sleep_sec
        self.visited_urls: set[str] = set()
        self.url_dir_map: dict[str, Path] = {}
        self.total_pages_crawled = 0
        self.total_pdf_links_found = 0
        self.aborted_due_to_depth = False


def _get_unique_dir_for_link(
    parent_dir: Path,
    label: str,
    url: str,
    url_dir_map: dict[str, Path],
) -> Path:
    """Determine a unique directory path for a page link."""
    if url in url_dir_map:
        return url_dir_map[url]

    base_name = sanitize_dir_name(label)
    candidate = parent_dir / base_name
    counter = 2

    # If the candidate path is already associated with another URL, append suffix
    while candidate.exists() and candidate in url_dir_map.values():
        candidate = parent_dir / f"{base_name}_{counter}"
        counter += 1

    candidate.mkdir(parents=True, exist_ok=True)
    url_dir_map[url] = candidate
    return candidate


def _crawl_recursive(
    current_url: str,
    current_dir: Path,
    depth: int,
    ctx: CrawlerContext,
) -> None:
    """Recursively crawl pages and collect PDF links (#1-d, #1-e, #1-f)."""
    # #1-f 巡回階層が7を超えた時点で注意喚起してPGを中断する
    if depth > ctx.max_depth:
        print(
            f"【注意喚起】巡回階層が上限（{ctx.max_depth}）を超えました。"
            f"設定ミス・ページフォーマット相違による無限アクセス防止のため処理を中断します。"
            f"(中断URL: {current_url})",
            file=sys.stderr,
        )
        ctx.aborted_due_to_depth = True
        return

    if current_url in ctx.visited_urls:
        return
    ctx.visited_urls.add(current_url)
    ctx.total_pages_crawled += 1

    print(f"[{depth}階層] 巡回中: {current_url}")

    try:
        html = fetch_html(current_url)
    except Exception as e:
        print(f"  警告: ページ取得失敗 ({current_url}): {e}", file=sys.stderr)
        return
    finally:
        # #1-d, #1-e 解析/URL採取後0.5秒スリープ (アクセス先負担軽減)
        if ctx.sleep_sec > 0:
            time.sleep(ctx.sleep_sec)

    section_html = extract_section_html(html, ctx.start_key, ctx.end_key)
    if not section_html:
        print(f"  情報: 読み出しキー範囲が見つかりませんでした (終端とみなします)")
        return

    pdf_links, page_links = extract_links_from_section(current_url, section_html, ctx.root_host)

    # PDFリンクの保存
    if pdf_links:
        save_path = save_pdf_links_file(current_dir, pdf_links)
        ctx.total_pdf_links_found += len(pdf_links)
        print(f"  PDFリンク保存: {len(pdf_links)}件 -> {save_path}")

    # #1-e 読み取りか所にpdfへのリンクだけでサイトページリンクが存在しない場合は、そのページを巡回Treeの枝の終端とする
    if not page_links:
        print(f"  枝の終端: ページリンクなし")
        return

    # サイトページリンクが存在する場合は再帰的に巡回
    for link in page_links:
        if ctx.aborted_due_to_depth:
            break
        if link.url in ctx.visited_urls:
            continue

        sub_dir = _get_unique_dir_for_link(current_dir, link.label, link.url, ctx.url_dir_map)
        _crawl_recursive(link.url, sub_dir, depth + 1, ctx)


def run_crawler(
    pref_code: str,
    output_dir: Path | None = None,
    config_path: Path | None = None,
    env_file_path: Path | None = None,
    max_depth: int = MAX_CRAWL_DEPTH,
    sleep_sec: float = DEFAULT_SLEEP_SEC,
) -> int:
    """Run site crawler for the specified prefecture code (#1 サイト巡回PG)."""
    valid_code = validate_pref_code(pref_code)

    config = load_crawler_config(config_path)
    target = get_pref_target(valid_code, config)

    resolved_output_base = output_dir or resolve_output_dir(env_file_path)
    pref_dir = resolved_output_base / valid_code

    root_url = target["root_url"]
    start_key = target["start_key"]
    end_key = target["end_key"]
    pref_name = target.get("name", valid_code)

    parsed_root = urllib.parse.urlsplit(root_url)
    root_host = parsed_root.netloc

    print("==================================================")
    print(f"[#1 サイト巡回PG] 起動条件:")
    print(f"  地方公共団体コード県: {valid_code} ({pref_name})")
    print(f"  成果物保存ディレクトリ: {pref_dir}")
    print(f"  ルートURL: {root_url}")
    print(f"  読み出しキー開始: '{start_key}'")
    print(f"  読み出しキー終了: '{end_key}'")
    print(f"  巡回階層上限: {max_depth}")
    print(f"  リクエスト待機間隔: {sleep_sec}秒")
    print("==================================================")

    pref_dir.mkdir(parents=True, exist_ok=True)

    ctx = CrawlerContext(
        root_host=root_host,
        start_key=start_key,
        end_key=end_key,
        max_depth=max_depth,
        sleep_sec=sleep_sec,
    )
    ctx.url_dir_map[root_url] = pref_dir

    _crawl_recursive(root_url, pref_dir, depth=1, ctx=ctx)

    # #1-z 作業完了メッセージ
    print("==================================================")
    if ctx.aborted_due_to_depth:
        print("[#1 サイト巡回PG] 【警告中断】階層上限超過により中断されました。")
    else:
        print("[#1 サイト巡回PG] 作業完了: サイト巡回が正常に終了しました。")
    print(f"  巡回ページ数: {ctx.total_pages_crawled}")
    print(f"  取得PDFリンク数: {ctx.total_pdf_links_found}")
    print(f"  成果物保存場所: {pref_dir}")
    print("==================================================")

    return 1 if ctx.aborted_due_to_depth else 0


def main(argv: list[str] | None = None) -> int:
    """CLI entry point for site crawler."""
    parser = argparse.ArgumentParser(description="#1 サイト巡回PG")
    parser.add_argument(
        "pref_code",
        help="地方公共団体コード県 (00: 総務省, 01〜47: 都道府県)",
    )
    parser.add_argument(
        "--config",
        dest="config_path",
        type=Path,
        default=None,
        help="サイト巡回設定ファイルパス (デフォルト: config/site_crawler_config.json)",
    )
    parser.add_argument(
        "--env-file",
        dest="env_file_path",
        type=Path,
        default=None,
        help="全体設定ファイルパス (デフォルト: config/settings.env または .env)",
    )
    parser.add_argument(
        "--output-dir",
        dest="output_dir",
        type=Path,
        default=None,
        help="成果物保存ディレクトリの直接指定 (未指定時は設定ファイルから取得)",
    )
    parser.add_argument(
        "--max-depth",
        dest="max_depth",
        type=int,
        default=MAX_CRAWL_DEPTH,
        help="巡回階層上限 (デフォルト: 7)",
    )
    parser.add_argument(
        "--sleep",
        dest="sleep_sec",
        type=float,
        default=DEFAULT_SLEEP_SEC,
        help="アクセス間隔スリープ秒数 (デフォルト: 0.5)",
    )

    args = parser.parse_args(argv)

    try:
        return run_crawler(
            pref_code=args.pref_code,
            output_dir=args.output_dir,
            config_path=args.config_path,
            env_file_path=args.env_file_path,
            max_depth=args.max_depth,
            sleep_sec=args.sleep_sec,
        )
    except (ValueError, KeyError, FileNotFoundError) as e:
        print(f"エラー: {e}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("\n処理がユーザーにより中断されました。", file=sys.stderr)
        return 130


if __name__ == "__main__":
    sys.exit(main())
