"""PDF downloader module (#2 pdf取得PG)."""

import argparse
import csv
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path

# 直接スクリプト実行時にもパッケージパスを解決できるように追加
_SRC_DIR = Path(__file__).resolve().parent.parent
if str(_SRC_DIR) not in sys.path:
    sys.path.insert(0, str(_SRC_DIR))

from transform_xml.config import find_env_file_in_argv, resolve_env_float

PDF_LINKS_FILE_NAME = "pdf_links.csv"
DEFAULT_SLEEP_SEC = 1.0
DEFAULT_TIMEOUT = 15.0
DEFAULT_USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) transform-xml/0.1.0"


@dataclass
class DownloadResult:
    """Result of PDF download processing."""

    target_dir: Path
    csv_count: int = 0
    downloaded_count: int = 0
    downloaded_files: list[Path] = field(default_factory=list)
    errors: list[tuple[str, str]] = field(default_factory=list)


def sanitize_pdf_filename(label: str) -> str:
    """Sanitize label string to create a valid PDF filename.

    Replaces invalid characters (\\/:*?\"<>|) and control characters with '=X'.
    Ensures filename ends with '.pdf' (case-insensitive).
    """
    if not label:
        return "unnamed.pdf"

    # Replace invalid Windows/POSIX filename characters
    sanitized = re.sub(r'[\\/:*?"<>|]', "=X", label)
    # Replace control characters
    sanitized = re.sub(r"[\x00-\x1f]", "=X", sanitized)
    # Remove leading/trailing whitespaces and dots (prohibited on Windows)
    sanitized = sanitized.strip(" .")

    if not sanitized:
        sanitized = "unnamed"

    # Ensure .pdf extension
    if not sanitized.lower().endswith(".pdf"):
        sanitized += ".pdf"

    return sanitized


def find_pdf_link_files(target_dir: Path) -> list[Path]:
    """Find all pdf_links.csv files in target_dir and its subdirectories (#2-a, #2-d).

    Returns:
        Sorted list of Path objects for found pdf_links.csv files.
    """
    if not target_dir.exists():
        raise FileNotFoundError(f"指定されたディレクトリが存在しません: {target_dir}")
    if not target_dir.is_dir():
        raise NotADirectoryError(f"指定されたパスはディレクトリではありません: {target_dir}")

    csv_files = list(target_dir.rglob(PDF_LINKS_FILE_NAME))
    # Sort deterministically
    csv_files.sort(key=lambda p: str(p))
    return csv_files


def load_pdf_links(csv_path: Path) -> list[tuple[str, str]]:
    """Load URL and label pairs from a pdf_links.csv file.

    Args:
        csv_path: Path to pdf_links.csv.

    Returns:
        List of (url, label) tuples.
    """
    links: list[tuple[str, str]] = []
    if not csv_path.is_file():
        return links

    with open(csv_path, "r", encoding="utf-8", errors="replace") as f:
        reader = csv.reader(f)
        for row in reader:
            if len(row) < 2:
                continue
            url = row[0].strip()
            label = row[1].strip()
            # Skip header row
            if url.lower() == "url" and label.lower() == "label":
                continue
            if url:
                links.append((url, label))

    return links


def download_file(
    url: str,
    dest_path: Path,
    timeout: float = DEFAULT_TIMEOUT,
    user_agent: str = DEFAULT_USER_AGENT,
) -> None:
    """Download binary content from URL and save to dest_path.

    Args:
        url: Remote file URL.
        dest_path: Local destination Path.
        timeout: Network timeout in seconds.
        user_agent: HTTP User-Agent header value.
    """
    req = urllib.request.Request(url, headers={"User-Agent": user_agent})
    dest_path.parent.mkdir(parents=True, exist_ok=True)

    with urllib.request.urlopen(req, timeout=timeout) as resp:
        with open(dest_path, "wb") as out_f:
            while True:
                chunk = resp.read(64 * 1024)
                if not chunk:
                    break
                out_f.write(chunk)


def download_pdfs_in_dir(
    target_dir: Path | str,
    sleep_sec: float | None = None,
    timeout: float | None = None,
    user_agent: str = DEFAULT_USER_AGENT,
    env_file_path: Path | str | None = None,
) -> DownloadResult:
    """Execute PDF download processing for target directory (#2 pdf取得PG).

    Args:
        target_dir: Target directory containing pdf_links.csv files.
        sleep_sec: Sleep duration in seconds after each file download (defaults to settings.env or 1.0s).
        timeout: Network request timeout in seconds (defaults to settings.env or 15.0s).
        user_agent: HTTP User-Agent header string.
        env_file_path: Optional path to settings.env.

    Returns:
        DownloadResult containing operation summary.
    """
    if sleep_sec is None:
        sleep_sec = resolve_env_float(
            "DOWNLOAD_SLEEP_SEC",
            "SLEEP_SEC",
            env_file_path=env_file_path,
            default=DEFAULT_SLEEP_SEC,
        )
    if timeout is None:
        timeout = resolve_env_float(
            "TIMEOUT_SEC",
            "REQUEST_TIMEOUT",
            env_file_path=env_file_path,
            default=DEFAULT_TIMEOUT,
        )

    resolved_dir = Path(target_dir).resolve()
    if not resolved_dir.exists():
        raise FileNotFoundError(f"指定されたディレクトリが存在しません: {resolved_dir}")
    if not resolved_dir.is_dir():
        raise NotADirectoryError(f"指定されたパスはディレクトリではありません: {resolved_dir}")

    print("==================================================")
    print(f"[#2 pdf取得PG] 起動条件:")
    print(f"  処理対象ディレクトリ: {resolved_dir}")
    print(f"  リクエスト待機間隔: {sleep_sec}秒")
    print("==================================================")

    # #2-a, #2-d 下位フォルダも含めて pdf_links.csv を取得
    csv_files = find_pdf_link_files(resolved_dir)
    result = DownloadResult(target_dir=resolved_dir, csv_count=len(csv_files))

    if not csv_files:
        print(f"  情報: 対象ディレクトリ内に {PDF_LINKS_FILE_NAME} が見つかりませんでした。")
    else:
        print(f"  検出されたリンクリストファイル: {len(csv_files)}件")

    for csv_idx, csv_file in enumerate(csv_files, start=1):
        rel_csv = csv_file.relative_to(resolved_dir) if csv_file.is_relative_to(resolved_dir) else csv_file
        print(f"\n[{csv_idx}/{len(csv_files)}] リンクリスト処理中: {rel_csv}")

        links = load_pdf_links(csv_file)
        if not links:
            print("  情報: リスト内に有効なURLが存在しません。")
            continue

        save_dir = csv_file.parent  # #2-b リンクリストファイルの存在するディレクトリ

        # #2-c リスト掲載URL分繰り返す
        for url_idx, (url, label) in enumerate(links, start=1):
            filename = sanitize_pdf_filename(label)
            save_path = save_dir / filename

            print(f"  [{url_idx}/{len(links)}] ダウンロード開始: {filename}")
            print(f"    URL: {url}")

            try:
                # #2-b リスト内のURLにアクセスし、リンクラベル名にファイル名を変えてpdfを保存
                download_file(url, save_path, timeout=timeout, user_agent=user_agent)
                result.downloaded_count += 1
                result.downloaded_files.append(save_path)
                print(f"    -> 保存完了: {save_path.name}")
            except Exception as e:
                err_msg = f"ダウンロード失敗 ({url}): {e}"
                print(f"    -> エラー: {err_msg}", file=sys.stderr)
                result.errors.append((url, str(e)))
                continue
            finally:
                # #2-b 保存作業完了後1秒スリープ (アクセス先負担軽減)
                if sleep_sec > 0:
                    time.sleep(sleep_sec)

    # #2-z 作業完了メッセージ
    print("\n==================================================")
    if result.errors:
        print(f"[#2 pdf取得PG] 作業完了（一部失敗あり）:")
    else:
        print(f"[#2 pdf取得PG] 作業完了: PDF取得が正常に終了しました。")
    print(f"  対象ディレクトリ: {resolved_dir}")
    print(f"  検出CSVファイル数: {result.csv_count}件")
    print(f"  ダウンロードPDF数: {result.downloaded_count}件")
    if result.errors:
        print(f"  失敗件数: {len(result.errors)}件")
    print("==================================================")

    return result


def main(argv: list[str] | None = None) -> int:
    """CLI entry point for PDF downloader."""
    env_file = find_env_file_in_argv(argv)
    initial_sleep = resolve_env_float(
        "DOWNLOAD_SLEEP_SEC",
        "SLEEP_SEC",
        env_file_path=env_file,
        default=DEFAULT_SLEEP_SEC,
    )
    initial_timeout = resolve_env_float(
        "TIMEOUT_SEC",
        "REQUEST_TIMEOUT",
        env_file_path=env_file,
        default=DEFAULT_TIMEOUT,
    )

    parser = argparse.ArgumentParser(description="#2 pdf取得PG")
    parser.add_argument(
        "target_dir",
        type=Path,
        help="pdf_links.csv を含む処理対象ディレクトリ (下位フォルダも再帰走査)",
    )
    parser.add_argument(
        "--sleep",
        dest="sleep_sec",
        type=float,
        default=initial_sleep,
        help=f"保存作業完了後の待機秒数 (デフォルト: settings.env または {DEFAULT_SLEEP_SEC}秒)",
    )
    parser.add_argument(
        "--timeout",
        dest="timeout",
        type=float,
        default=initial_timeout,
        help=f"リクエストタイムアウト秒数 (デフォルト: settings.env または {DEFAULT_TIMEOUT}秒)",
    )
    parser.add_argument(
        "--env-file",
        dest="env_file_path",
        type=Path,
        default=None,
        help="全体設定ファイルパス (デフォルト: config/settings.env または .env)",
    )

    args = parser.parse_args(argv)

    try:
        result = download_pdfs_in_dir(
            target_dir=args.target_dir,
            sleep_sec=args.sleep_sec,
            timeout=args.timeout,
        )
        return 1 if result.errors else 0
    except (FileNotFoundError, NotADirectoryError, ValueError) as e:
        print(f"エラー: {e}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("\n処理がユーザーにより中断されました。", file=sys.stderr)
        return 130


if __name__ == "__main__":
    sys.exit(main())
