"""Analyze pipeline module (連続実行解析PG: #4, #5).

#4 画像XML部分変換PG (image_xml_converter)
#5 XML部分統合PG (xml_integrator)
を連続して実行し、画像から部分XMLへの変換および全体XMLへの統合・成形を一括処理します。
"""

import argparse
import sys
from pathlib import Path

# 直接スクリプト実行時にもパッケージパスを解決できるように追加
_SRC_DIR = Path(__file__).resolve().parent.parent
if str(_SRC_DIR) not in sys.path:
    sys.path.insert(0, str(_SRC_DIR))

from transform_xml.config import find_env_file_in_argv, resolve_env_path
from transform_xml.image_xml_converter import (
    DEFAULT_CLAUDE_MODEL,
    BaseOcrEngine,
    convert_xmls_in_target_dir,
)
from transform_xml.site_crawler import resolve_output_dir, VALID_PREF_CODES
from transform_xml.xml_integrator import (
    _DEFAULT_TEMPLATE_DIR,
    integrate_xml_in_target_dir,
)


def resolve_target_directory(
    target_arg: str | Path,
    env_file_path: Path | None = None,
) -> Path:
    """Resolve target directory from a path string or 2-digit prefecture code.

    If target_arg is a prefecture code (e.g. '24'), resolves to {OUTPUT_DIR}/{code}.
    Otherwise, resolves as a directory path.
    """
    arg_str = str(target_arg).strip()
    if arg_str.isdigit() and len(arg_str) <= 2:
        code = f"{int(arg_str):02d}"
        if code in VALID_PREF_CODES:
            output_base = resolve_output_dir(env_file_path)
            candidate = output_base / code
            if candidate.is_dir():
                return candidate.resolve()

    resolved = Path(target_arg).resolve()
    return resolved


def run_analyze_pipeline(
    target_dir: Path | str,
    ocr_engine: BaseOcrEngine | None = None,
    engine_name: str | None = None,
    env_file_path: Path | None = None,
    api_key: str | None = None,
    model: str | None = None,
    template_dir: Path | None = None,
) -> int:
    """Execute continuous analyze pipeline (#4 画像XML部分変換 -> #5 XML部分統合).

    Args:
        target_dir: 処理対象ディレクトリパス または 地方公共団体コード県 (00〜47).
        ocr_engine: 事前構築されたOCRエンジン (任意).
        engine_name: "claude", "local", または "mock".
        env_file_path: 設定ファイルパス.
        api_key: Claude APIキー.
        model: Claude Vision モデル名.
        template_dir: XMLテンプレートディレクトリ.

    Returns:
        終了コード (0: 成功, 1: 失敗)
    """
    resolved_dir = resolve_target_directory(target_dir, env_file_path=env_file_path)
    if not resolved_dir.exists():
        raise FileNotFoundError(f"指定された処理対象ディレクトリが存在しません: {resolved_dir}")
    if not resolved_dir.is_dir():
        raise NotADirectoryError(f"指定されたパスはディレクトリではありません: {resolved_dir}")

    print("==================================================")
    print("【連続実行解析PG 開始 (#4 -> #5)】")
    print(f"  処理対象ディレクトリ: {resolved_dir}")
    print("==================================================")

    # ----------------------------------------------------
    # ステップ1: #4 画像XML部分変換PG
    # ----------------------------------------------------
    print("\n>>> [ステップ 1/2] #4 画像XML部分変換PG の実行...")
    try:
        xml_convert_result = convert_xmls_in_target_dir(
            target_dir=resolved_dir,
            ocr_engine=ocr_engine,
            engine_name=engine_name,
            env_file_path=env_file_path,
            api_key=api_key,
            model=model,
        )
        if xml_convert_result.errors or xml_convert_result.failed_dirs_count > 0:
            print(
                f"  警告: 一部のディレクトリでXML部分変換に失敗しました (失敗数: {xml_convert_result.failed_dirs_count}件)",
                file=sys.stderr,
            )
    except Exception as e:
        print(f"\nエラー: #4 画像XML部分変換PG の実行中に例外が発生しました: {e}", file=sys.stderr)
        return 1

    # ----------------------------------------------------
    # ステップ2: #5 XML部分統合PG
    # ----------------------------------------------------
    print("\n>>> [ステップ 2/2] #5 XML部分統合PG の実行...")
    try:
        integrate_result = integrate_xml_in_target_dir(
            target_dir=resolved_dir,
            template_dir=template_dir,
            env_file_path=env_file_path,
        )
        if integrate_result.errors or integrate_result.failed_count > 0:
            print(
                f"  警告: 一部のディレクトリでXML統合に失敗しました (失敗数: {integrate_result.failed_count}件)",
                file=sys.stderr,
            )
    except Exception as e:
        print(f"\nエラー: #5 XML部分統合PG の実行中に例外が発生しました: {e}", file=sys.stderr)
        return 1

    print("\n==================================================")
    print("【連続実行解析PG 完了】")
    print(f"  対象ディレクトリ: {resolved_dir}")
    print(f"  XML部分変換対象数: {xml_convert_result.target_dirs_count}件")
    print(f"  XML部分変換成功数: {xml_convert_result.success_dirs_count}件")
    print(f"  XML統合成功数: {integrate_result.success_count}件")
    print(f"  XML統合スキップ数: {integrate_result.skipped_count}件")
    if integrate_result.failed_count > 0:
        print(f"  XML統合失敗数: {integrate_result.failed_count}件")
    print("==================================================")

    return 1 if (integrate_result.failed_count > 0 or xml_convert_result.failed_dirs_count > 0) else 0


def main(argv: list[str] | None = None) -> int:
    """CLI entry point for continuous analyze pipeline."""
    env_file = find_env_file_in_argv(argv)
    initial_template_dir = resolve_env_path(
        "TEMPLATE_DIR", env_file_path=env_file, default=_DEFAULT_TEMPLATE_DIR
    )

    parser = argparse.ArgumentParser(
        description="連続実行解析PG (#4 画像XML部分変換 -> #5 XML部分統合)"
    )
    parser.add_argument(
        "target_dir",
        help="画像変換ログが存在するディレクトリパス または 地方公共団体コード県 (例: 24 または C:/transfer-xml/24)",
    )
    parser.add_argument(
        "--env-file",
        dest="env_file_path",
        type=Path,
        default=None,
        help="全体設定ファイルパス (デフォルト: config/settings.env または .env)",
    )
    parser.add_argument(
        "--ocr-engine",
        dest="ocr_engine",
        type=str,
        default=None,
        choices=["claude", "local", "mock", "dummy"],
        help="使用するOCRエンジン (デフォルト: settings.env の設定または local)",
    )
    parser.add_argument(
        "--api-key",
        dest="api_key",
        type=str,
        default=None,
        help="Claude APIキー (未指定時は settings.env または環境変数より取得)",
    )
    parser.add_argument(
        "--model",
        dest="model",
        type=str,
        default=None,
        help=f"Claude Vision モデル名 (デフォルト: settings.env または {DEFAULT_CLAUDE_MODEL})",
    )
    parser.add_argument(
        "--template-dir",
        dest="template_dir",
        type=Path,
        default=initial_template_dir,
        help=f"テンプレート配置ディレクトリ (デフォルト: settings.env または {_DEFAULT_TEMPLATE_DIR})",
    )

    args = parser.parse_args(argv)

    try:
        return run_analyze_pipeline(
            target_dir=args.target_dir,
            engine_name=args.ocr_engine,
            env_file_path=args.env_file_path or env_file,
            api_key=args.api_key,
            model=args.model,
            template_dir=args.template_dir,
        )
    except (FileNotFoundError, NotADirectoryError, ValueError) as e:
        print(f"エラー: {e}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("\n処理がユーザーにより中断されました。", file=sys.stderr)
        return 130


if __name__ == "__main__":
    sys.exit(main())
