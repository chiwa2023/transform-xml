"""Fetch pipeline module (連続実行取得PG: #1, #2, #3).

#1 サイト巡回PG (site_crawler)
#2 PDF取得PG (pdf_downloader)
#3 PDF画像変換PG (pdf_image_converter)
を連続して実行し、指定された地方自治体のPDFリンク取得から画像変換までを一括処理します。
"""

import argparse
import sys
from pathlib import Path

# 直接スクリプト実行時にもパッケージパスを解決できるように追加
_SRC_DIR = Path(__file__).resolve().parent.parent
if str(_SRC_DIR) not in sys.path:
    sys.path.insert(0, str(_SRC_DIR))

from transform_xml.config import (
    find_env_file_in_argv,
    resolve_env_float,
    resolve_env_int,
    resolve_env_path,
    resolve_env_str,
)
from transform_xml.pdf_downloader import (
    DEFAULT_SLEEP_SEC as DEFAULT_DOWNLOAD_SLEEP_SEC,
    DEFAULT_TIMEOUT,
    download_pdfs_in_dir,
)
from transform_xml.pdf_image_converter import (
    DEFAULT_DPI,
    DEFAULT_FORMAT,
    convert_pdfs_in_dir,
)
from transform_xml.site_crawler import (
    DEFAULT_CONFIG_PATH,
    DEFAULT_OUTPUT_DIR,
    DEFAULT_SLEEP_SEC as DEFAULT_CRAWLER_SLEEP_SEC,
    MAX_CRAWL_DEPTH,
    resolve_output_dir,
    run_crawler,
    validate_pref_code,
)


def run_fetch_pipeline(
    pref_code: str,
    output_dir: Path | None = None,
    config_path: Path | None = None,
    env_file_path: Path | None = None,
    max_depth: int | None = None,
    sleep_sec: float | None = None,
    crawler_sleep_sec: float | None = None,
    download_sleep_sec: float | None = None,
    timeout: float | None = None,
    dpi: int | None = None,
    image_format: str | None = None,
) -> int:
    """Execute continuous fetch pipeline (#1 サイト巡回 -> #2 PDF取得 -> #3 PDF画像変換).

    Args:
        pref_code: 地方公共団体コード県 (00〜47).
        output_dir: 成果物保存ベースディレクトリ (未指定時は settings.env またはデフォルト).
        config_path: サイト巡回設定ファイルパス.
        env_file_path: 設定ファイルパス.
        max_depth: 巡回階層上限.
        sleep_sec: 共通スリープ待機秒数.
        crawler_sleep_sec: サイト巡回用スリープ秒数.
        download_sleep_sec: PDFダウンロード用スリープ秒数.
        timeout: HTTPリクエストタイムアウト秒数.
        dpi: PDF画像変換DPI.
        image_format: 出力画像フォーマット.

    Returns:
        終了コード (0: 成功, 1: 失敗)
    """
    valid_code = validate_pref_code(pref_code)
    resolved_output_base = output_dir or resolve_output_dir(env_file_path)
    pref_dir = resolved_output_base / valid_code

    print("==================================================")
    print("【連続実行取得PG 開始 (#1 -> #2 -> #3)】")
    print(f"  対象地方公共団体コード県: {valid_code}")
    print(f"  成果物保存ディレクトリ: {pref_dir}")
    print("==================================================")

    # ----------------------------------------------------
    # ステップ1: #1 サイト巡回PG
    # ----------------------------------------------------
    print("\n>>> [ステップ 1/3] #1 サイト巡回PG の実行...")
    c_sleep = crawler_sleep_sec if crawler_sleep_sec is not None else sleep_sec
    ret_crawl = run_crawler(
        pref_code=valid_code,
        output_dir=resolved_output_base,
        config_path=config_path,
        env_file_path=env_file_path,
        max_depth=max_depth if max_depth is not None else MAX_CRAWL_DEPTH,
        sleep_sec=c_sleep if c_sleep is not None else DEFAULT_CRAWLER_SLEEP_SEC,
    )
    if ret_crawl != 0:
        print(f"\nエラー: #1 サイト巡回PG が異常終了しました (コード: {ret_crawl})。", file=sys.stderr)
        return ret_crawl

    # ----------------------------------------------------
    # ステップ2: #2 PDF取得PG
    # ----------------------------------------------------
    print("\n>>> [ステップ 2/3] #2 PDF取得PG の実行...")
    d_sleep = download_sleep_sec if download_sleep_sec is not None else sleep_sec
    try:
        download_result = download_pdfs_in_dir(
            target_dir=pref_dir,
            sleep_sec=d_sleep,
            timeout=timeout,
        )
        if download_result.errors:
            print(
                f"  警告: 一部のPDFダウンロードに失敗しました (エラー: {len(download_result.errors)}件)",
                file=sys.stderr,
            )
    except Exception as e:
        print(f"\nエラー: #2 PDF取得PG の実行中に例外が発生しました: {e}", file=sys.stderr)
        return 1

    # ----------------------------------------------------
    # ステップ3: #3 PDF画像変換PG
    # ----------------------------------------------------
    print("\n>>> [ステップ 3/3] #3 PDF画像変換PG の実行...")
    try:
        convert_result = convert_pdfs_in_dir(
            target_dir=pref_dir,
            dpi=dpi,
            image_format=image_format,
        )
        if convert_result.errors or convert_result.failed_pdf_count > 0:
            print(
                f"  警告: 一部のPDF画像変換に失敗しました (失敗PDF: {convert_result.failed_pdf_count}件)",
                file=sys.stderr,
            )
    except Exception as e:
        print(f"\nエラー: #3 PDF画像変換PG の実行中に例外が発生しました: {e}", file=sys.stderr)
        return 1

    print("\n==================================================")
    print("【連続実行取得PG 完了】")
    print(f"  対象ディレクトリ: {pref_dir}")
    print(f"  検出CSVファイル数: {download_result.csv_count}件")
    print(f"  ダウンロード完了PDF数: {download_result.downloaded_count}件")
    print(f"  変換成功PDF数: {convert_result.success_pdf_count}件")
    print(f"  総変換画像ページ数: {convert_result.total_pages_converted}ページ")
    print("==================================================")

    return 0


def main(argv: list[str] | None = None) -> int:
    """CLI entry point for continuous fetch pipeline."""
    env_file = find_env_file_in_argv(argv)
    initial_common_sleep = resolve_env_float("SLEEP_SEC", env_file_path=env_file, default=1.0)
    initial_crawler_sleep = resolve_env_float(
        "CRAWLER_SLEEP_SEC", "SLEEP_SEC", env_file_path=env_file, default=initial_common_sleep
    )
    initial_download_sleep = resolve_env_float(
        "DOWNLOAD_SLEEP_SEC", "SLEEP_SEC", env_file_path=env_file, default=initial_common_sleep
    )
    initial_timeout = resolve_env_float(
        "TIMEOUT_SEC", "REQUEST_TIMEOUT", env_file_path=env_file, default=DEFAULT_TIMEOUT
    )
    initial_max_depth = resolve_env_int(
        "MAX_CRAWL_DEPTH", "MAX_DEPTH", env_file_path=env_file, default=MAX_CRAWL_DEPTH
    )
    initial_config = resolve_env_path(
        "CRAWLER_CONFIG_PATH", "SITE_CRAWLER_CONFIG", env_file_path=env_file, default=DEFAULT_CONFIG_PATH
    )
    initial_dpi = resolve_env_int("PDF_IMAGE_DPI", "DPI", env_file_path=env_file, default=DEFAULT_DPI)
    initial_format = resolve_env_str(
        "PDF_IMAGE_FORMAT", "IMAGE_FORMAT", env_file_path=env_file, default=DEFAULT_FORMAT
    )

    parser = argparse.ArgumentParser(
        description="連続実行取得PG (#1 サイト巡回 -> #2 PDF取得 -> #3 PDF画像変換)"
    )
    parser.add_argument(
        "pref_code",
        help="地方公共団体コード県 (00: 総務省, 01〜47: 都道府県)",
    )
    parser.add_argument(
        "--output-dir",
        dest="output_dir",
        type=Path,
        default=None,
        help="成果物保存ディレクトリの直接指定 (未指定時は設定ファイルから取得)",
    )
    parser.add_argument(
        "--config",
        dest="config_path",
        type=Path,
        default=initial_config,
        help=f"サイト巡回設定ファイルパス (デフォルト: settings.env または {DEFAULT_CONFIG_PATH})",
    )
    parser.add_argument(
        "--env-file",
        dest="env_file_path",
        type=Path,
        default=None,
        help="全体設定ファイルパス (デフォルト: config/settings.env または .env)",
    )
    parser.add_argument(
        "--max-depth",
        dest="max_depth",
        type=int,
        default=initial_max_depth,
        help=f"巡回階層上限 (デフォルト: settings.env または {MAX_CRAWL_DEPTH})",
    )
    parser.add_argument(
        "--sleep",
        dest="sleep_sec",
        type=float,
        default=initial_common_sleep,
        help=f"共通待機秒数 (デフォルト: settings.env または {initial_common_sleep}秒)",
    )
    parser.add_argument(
        "--crawler-sleep",
        dest="crawler_sleep_sec",
        type=float,
        default=initial_crawler_sleep,
        help=f"サイト巡回待機秒数 (デフォルト: settings.env または {initial_crawler_sleep}秒)",
    )
    parser.add_argument(
        "--download-sleep",
        dest="download_sleep_sec",
        type=float,
        default=initial_download_sleep,
        help=f"PDFダウンロード待機秒数 (デフォルト: settings.env または {initial_download_sleep}秒)",
    )
    parser.add_argument(
        "--timeout",
        dest="timeout",
        type=float,
        default=initial_timeout,
        help=f"リクエストタイムアウト秒数 (デフォルト: settings.env または {initial_timeout}秒)",
    )
    parser.add_argument(
        "--dpi",
        dest="dpi",
        type=int,
        default=initial_dpi,
        help=f"画像解像度 DPI (デフォルト: settings.env または {initial_dpi})",
    )
    parser.add_argument(
        "--format",
        dest="image_format",
        type=str,
        default=initial_format,
        choices=["PNG", "png", "JPEG", "jpeg", "JPG", "jpg"],
        help=f"出力画像フォーマット (デフォルト: settings.env または {initial_format})",
    )

    args = parser.parse_args(argv)

    try:
        return run_fetch_pipeline(
            pref_code=args.pref_code,
            output_dir=args.output_dir,
            config_path=args.config_path,
            env_file_path=args.env_file_path or env_file,
            max_depth=args.max_depth,
            sleep_sec=args.sleep_sec,
            crawler_sleep_sec=args.crawler_sleep_sec,
            download_sleep_sec=args.download_sleep_sec,
            timeout=args.timeout,
            dpi=args.dpi,
            image_format=args.image_format,
        )
    except (ValueError, KeyError, FileNotFoundError) as e:
        print(f"エラー: {e}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("\n処理がユーザーにより中断されました。", file=sys.stderr)
        return 130


if __name__ == "__main__":
    sys.exit(main())
