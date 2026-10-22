"""XML integrator module (#5 XML(部分)を統合してpdfに対して1XMLとなるよう成形する『XML部分統合PG』)."""

import argparse
import json
import os
import re
import shutil
import sys
from dataclasses import dataclass, field
from pathlib import Path

# 直接スクリプト実行時にもパッケージパスを解決できるように追加
_SRC_DIR = Path(__file__).resolve().parent.parent
if str(_SRC_DIR) not in sys.path:
    sys.path.insert(0, str(_SRC_DIR))

# 定数定義
XML_CONVERT_LOG_NAME = "xml_convert.log"
XML_CONVERT_JSON_NAME = "xml_convert.json"
TEMPLATE_LEAST_NAME = "SYUUSI_least.xml"
TEMPLATE_BLANK_DIR_NAME = "blank"

# デフォルトのテンプレートディレクトリ (config/template)
_DEFAULT_TEMPLATE_DIR = (
    Path(__file__).resolve().parent.parent.parent / "config" / "template"
)


@dataclass
class IntegrationResult:
    """Result of XML integration for a single directory."""

    dir_path: Path
    output_xml_path: Path | None = None
    status: str = "SUCCESS"  # "SUCCESS", "SKIPPED", "FAILED"
    page_count: int = 0
    used_orders: list[int] = field(default_factory=list)
    error_message: str | None = None
    message: str = ""


@dataclass
class BatchIntegrationResult:
    """Result of batch XML integration for multiple directories."""

    target_dir: Path
    total_dirs: int = 0
    success_count: int = 0
    skipped_count: int = 0
    failed_count: int = 0
    results: list[IntegrationResult] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


def find_integration_targets(target_dir: Path) -> list[Path]:
    """Find directories containing XML conversion logs (#5-1).

    下位ディレクトリを走査し、xml_convert.json または xml_convert.log が
    存在するディレクトリを抽出する。

    Args:
        target_dir: 探索対象のルートディレクトリ

    Returns:
        XML変換ログが存在するディレクトリパスのソート済みリスト
    """
    target_dir = Path(target_dir).resolve()
    if not target_dir.exists():
        raise FileNotFoundError(f"指定されたディレクトリが存在しません: {target_dir}")
    if not target_dir.is_dir():
        raise NotADirectoryError(f"指定されたパスはディレクトリではありません: {target_dir}")

    matched_dirs: set[Path] = set()

    # 対象ディレクトリ直下のチェック
    if (target_dir / XML_CONVERT_JSON_NAME).is_file() or (
        target_dir / XML_CONVERT_LOG_NAME
    ).is_file():
        matched_dirs.add(target_dir)

    # 再帰走査
    for item in target_dir.rglob("*"):
        if item.is_dir():
            if (item / XML_CONVERT_JSON_NAME).is_file() or (
                item / XML_CONVERT_LOG_NAME
            ).is_file():
                matched_dirs.add(item)

    return sorted(matched_dirs)


def check_xml_conversion_completed(target_dir: Path) -> tuple[bool, str | None]:
    """Check if all pages in the directory have been converted to XML (#5-2).

    XML変換ログを開き、すべてのページが部分XMLに変換されていることを確認する。
    ログに未変換やエラーが記載されている場合は False とメッセージを返す。

    Args:
        target_dir: 検証対象のディレクトリ

    Returns:
        (変換完了フラグ, スキップ理由メッセージ)
    """
    json_path = target_dir / XML_CONVERT_JSON_NAME
    log_path = target_dir / XML_CONVERT_LOG_NAME

    if json_path.is_file():
        try:
            with open(json_path, "r", encoding="utf-8") as fp:
                data = json.load(fp)

            status = data.get("status")
            failed_xmls = data.get("failed_xmls", 0)
            page_records = data.get("page_records", [])

            if status == "FAILED" or failed_xmls > 0:
                return (
                    False,
                    f"XML変換ログで失敗({failed_xmls}件)が記録されています: status={status}",
                )

            # 各レコードのステータスチェック
            for rec in page_records:
                rec_status = rec.get("status")
                if rec_status == "FAILED":
                    page_num = rec.get("page_number", "?")
                    err = rec.get("error_message", "不明なエラー")
                    return (
                        False,
                        f"ページ {page_num} のXML変換が失敗しています: {err}",
                    )

            return True, None
        except Exception as e:
            return False, f"XML変換ログ(JSON)の読み込みに失敗しました: {e}"

    if log_path.is_file():
        try:
            with open(log_path, "r", encoding="utf-8", errors="ignore") as fp:
                content = fp.read()

            if "変換ステータス: FAILED" in content:
                return False, "XML変換ログでステータスがFAILEDです"
            if "状態=FAILED" in content:
                return False, "XML変換ログに失敗したページ(状態=FAILED)が存在します"

            m_failed = re.search(r"XML変換失敗数:\s*(\d+)", content)
            if m_failed and int(m_failed.group(1)) > 0:
                return False, f"XML変換失敗数が {m_failed.group(1)} 件記録されています"

            return True, None
        except Exception as e:
            return False, f"XML変換ログ(テキスト)の読み出しに失敗しました: {e}"

    return False, "XML変換ログが存在しません"


def get_blank_mapping(
    template_dir: Path,
) -> dict[tuple[int, int | None], tuple[str, int]]:
    """Build a mapping from (form_number, branch_number) to (blank_filename, order) (#5-3d).

    命名規則: XML表示順_様式番号(あれば_様式番号枝番).xml
    例:
      01_01_blank.xml -> (1, None): ('01_01_blank.xml', 1)
      08_07_02_blank.xml -> (7, 2): ('08_07_02_blank.xml', 8)

    Args:
        template_dir: テンプレートディレクトリパス

    Returns:
        (様式番号, 枝番) -> (blankファイル名, 表示順) の辞書
    """
    blank_dir = template_dir / TEMPLATE_BLANK_DIR_NAME
    if not blank_dir.is_dir():
        raise FileNotFoundError(
            f"blank テンプレートディレクトリが存在しません: {blank_dir}"
        )

    mapping: dict[tuple[int, int | None], tuple[str, int]] = {}

    for file_path in blank_dir.glob("*.xml"):
        filename = file_path.name
        # 命名規則: 01_01_blank.xml または 08_07_02_blank.xml
        base_name = filename.replace("_blank.xml", "").replace(".xml", "")
        parts = base_name.split("_")
        if len(parts) >= 2:
            try:
                order = int(parts[0])
                form = int(parts[1])
                branch = int(parts[2]) if len(parts) >= 3 else None
                mapping[(form, branch)] = (filename, order)
            except ValueError:
                continue

    return mapping


def find_partial_xml_files(dir_path: Path) -> list[Path]:
    """Find all partial XML files in the directory sorted by page number.

    ディレクトリ内の *.xml ファイルを収集し、成果物XML（ディレクトリ名.xml）を除外し、
    ファイル名末尾のページ番号等でソートして返却する。

    Args:
        dir_path: 対象ディレクトリ

    Returns:
        ソート済み部分XMLファイルパスのリスト
    """
    target_name = dir_path.name + ".xml"
    xml_files: list[tuple[int, Path]] = []

    for item in dir_path.glob("*.xml"):
        if item.name == target_name:
            continue
        # ページ番号抽出 (例: 2022年ホリエモン新党_0001.xml -> 1)
        m = re.search(r"_(\d{4})\.xml$", item.name, re.IGNORECASE)
        if m:
            page_no = int(m.group(1))
        else:
            page_no = 999999
        xml_files.append((page_no, item))

    xml_files.sort(key=lambda x: (x[0], x[1].name))
    return [p for _, p in xml_files]


def parse_partial_xml(file_path: Path) -> tuple[int, int | None, str] | None:
    """Read a partial XML file and extract form number, branch number, and content (#5-3b).

    空ファイル（0バイト）の場合は None を返す (#4-i, #4-e013)。

    Args:
        file_path: 部分XMLファイルパス

    Returns:
        (様式番号, 枝番, XMLテキスト) または None
    """
    if file_path.stat().st_size == 0:
        return None

    # UTF-8 で読み込み、失敗時は CP932
    try:
        with open(file_path, "r", encoding="utf-8", newline="") as fp:
            content = fp.read()
    except UnicodeDecodeError:
        with open(file_path, "r", encoding="cp932", newline="") as fp:
            content = fp.read()

    if not content.strip():
        return None

    # 様式番号抽出: <SYUUSHI07_(\d{2})>
    m_form = re.search(r"<SYUUSHI07_(\d{2})>", content)
    if not m_form:
        return None
    form = int(m_form.group(1))

    # 枝番抽出: <KUBUN(\d+)>
    m_branch = re.search(r"<KUBUN(\d+)>", content)
    branch = int(m_branch.group(1)) if m_branch else None

    return form, branch, content


def integrate_single_dir(
    dir_path: Path, template_dir: Path | None = None
) -> IntegrationResult:
    """Integrate partial XMLs in a single directory into one XML file (#5-3a ~ #5-3j).

    Args:
        dir_path: 処理対象ディレクトリ
        template_dir: テンプレート配置ディレクトリ (未指定時は _DEFAULT_TEMPLATE_DIR)

    Returns:
        IntegrationResult オブジェクト
    """
    dir_path = Path(dir_path).resolve()
    template_dir = (
        Path(template_dir).resolve() if template_dir else _DEFAULT_TEMPLATE_DIR
    )

    # 1. ログチェック (#5-2)
    completed, skip_reason = check_xml_conversion_completed(dir_path)
    if not completed:
        msg = f"スキップ: {dir_path.name} ({skip_reason})"
        print(msg)
        return IntegrationResult(
            dir_path=dir_path,
            status="SKIPPED",
            message=msg,
            error_message=skip_reason,
        )

    # 2. テンプレートファイルの読み込み (#5-3a)
    least_template_path = template_dir / TEMPLATE_LEAST_NAME
    if not least_template_path.is_file():
        err_msg = (
            f"テンプレートファイルが存在しません: {least_template_path}"
        )
        return IntegrationResult(
            dir_path=dir_path,
            status="FAILED",
            error_message=err_msg,
            message=err_msg,
        )

    try:
        with open(least_template_path, "r", encoding="cp932", newline="") as fp:
            merged_xml = fp.read()
    except Exception as e:
        err_msg = f"テンプレートファイルの読み込みに失敗しました: {e}"
        return IntegrationResult(
            dir_path=dir_path,
            status="FAILED",
            error_message=err_msg,
            message=err_msg,
        )

    # blank ファイルマッピングの取得 (#5-3d)
    try:
        blank_map = get_blank_mapping(template_dir)
    except Exception as e:
        err_msg = f"blank テンプレートマッピングの構築に失敗しました: {e}"
        return IntegrationResult(
            dir_path=dir_path,
            status="FAILED",
            error_message=err_msg,
            message=err_msg,
        )

    # 3. 部分XMLファイルの収集と順次統合 (#5-3b ~ #5-3h)
    partial_files = find_partial_xml_files(dir_path)
    used_orders: set[int] = set()
    replaced_keys: set[tuple[int, int | None]] = set()
    processed_pages = 0

    for p_path in partial_files:
        parsed = parse_partial_xml(p_path)
        if parsed is None:
            # 0バイトまたは空XMLはスキップ
            continue

        form, branch, p_content = parsed
        processed_pages += 1
        key = (form, branch)

        # blank の頭2桁 (order) を記録 (#5-3f)
        if key in blank_map:
            _, order = blank_map[key]
            used_orders.add(order)

        if branch is not None:
            parent_tag = f"SYUUSHI07_{form:02d}"
            if key not in replaced_keys:
                # 初回: 対象親タグ内の <KUBUN{branch}>...</KUBUN{branch}> を置換 (#5-3e)
                m_parent = re.search(
                    rf"(<{parent_tag}>.*?</{parent_tag}>)",
                    merged_xml,
                    re.DOTALL,
                )
                m_p_kubun = re.search(
                    rf"(<KUBUN{branch}>.*?</KUBUN{branch}>)",
                    p_content,
                    re.DOTALL,
                )
                if m_parent and m_p_kubun:
                    parent_block = m_parent.group(1)
                    m_sub_k = re.search(
                        rf"(<KUBUN{branch}>.*?</KUBUN{branch}>)",
                        parent_block,
                        re.DOTALL,
                    )
                    if m_sub_k:
                        new_parent_block = (
                            parent_block[: m_sub_k.start()]
                            + m_p_kubun.group(1)
                            + parent_block[m_sub_k.end() :]
                        )
                        merged_xml = (
                            merged_xml[: m_parent.start()]
                            + new_parent_block
                            + merged_xml[m_parent.end() :]
                        )
                        replaced_keys.add(key)
            else:
                # 2回目以降: 同様式・枝番タグ内に <SHEET>...</SHEET> を追加 (#5-3g)
                m_sheet = re.search(
                    r"(\t*<SHEET>.*?</SHEET>\r?\n)", p_content, re.DOTALL
                )
                if m_sheet:
                    sheet_content = m_sheet.group(1).lstrip("\t")
                    sheet_content = "\t\t\t" + sheet_content  # インデント調整 (3タブ)

                    m_parent = re.search(
                        rf"(<{parent_tag}>.*?</{parent_tag}>)",
                        merged_xml,
                        re.DOTALL,
                    )
                    if m_parent:
                        parent_block = m_parent.group(1)
                        pos_end = parent_block.find(f"</KUBUN{branch}>")
                        if pos_end != -1:
                            last_nl = parent_block.rfind("\n", 0, pos_end)
                            indent_pos = last_nl + 1 if last_nl != -1 else pos_end
                            new_parent_block = (
                                parent_block[:indent_pos]
                                + sheet_content
                                + parent_block[indent_pos:]
                            )
                            merged_xml = (
                                merged_xml[: m_parent.start()]
                                + new_parent_block
                                + merged_xml[m_parent.end() :]
                            )
        else:
            tag = f"SYUUSHI07_{form:02d}"
            if key not in replaced_keys:
                # 初回: <SYUUSHI07_XX>...</SYUUSHI07_XX> を置換 (#5-3e)
                m_p_form = re.search(
                    rf"(<{tag}>.*?</{tag}>)", p_content, re.DOTALL
                )
                m_target_form = re.search(
                    rf"(<{tag}>.*?</{tag}>)", merged_xml, re.DOTALL
                )
                if m_p_form and m_target_form:
                    merged_xml = (
                        merged_xml[: m_target_form.start()]
                        + m_p_form.group(1)
                        + merged_xml[m_target_form.end() :]
                    )
                    replaced_keys.add(key)
            else:
                # 2回目以降: <SHEET>...</SHEET> を追加 (#5-3g)
                m_sheet = re.search(
                    r"(\t*<SHEET>.*?</SHEET>\r?\n)", p_content, re.DOTALL
                )
                if m_sheet:
                    sheet_content = m_sheet.group(1).lstrip("\t")
                    sheet_content = "\t\t" + sheet_content  # インデント調整 (2タブ)

                    pos_end = merged_xml.find(f"</{tag}>")
                    if pos_end != -1:
                        last_nl = merged_xml.rfind("\n", 0, pos_end)
                        indent_pos = last_nl + 1 if last_nl != -1 else pos_end
                        merged_xml = (
                            merged_xml[:indent_pos]
                            + sheet_content
                            + merged_xml[indent_pos:]
                        )

    # 4. <SYUUSHI_UMU> 存在フラグの更新 (#5-3i)
    m_umu = re.search(r"<SYUUSHI_UMU>(.*?)</SYUUSHI_UMU>", merged_xml)
    if m_umu:
        old_umu = m_umu.group(1)
        umu_chars = list(old_umu)
        for ord_val in sorted(used_orders):
            if 1 <= ord_val <= len(umu_chars):
                umu_chars[ord_val - 1] = "1"
        new_umu = "".join(umu_chars)
        merged_xml = (
            merged_xml[: m_umu.start(1)] + new_umu + merged_xml[m_umu.end(1) :]
        )

    # 5. 成果物ファイルの保存 (#5-3j)
    output_xml_path = dir_path / f"{dir_path.name}.xml"
    try:
        with open(output_xml_path, "w", encoding="cp932", newline="") as fp:
            fp.write(merged_xml)
    except Exception as e:
        err_msg = f"成果物XMLの保存に失敗しました: {e}"
        return IntegrationResult(
            dir_path=dir_path,
            status="FAILED",
            error_message=err_msg,
            message=err_msg,
        )

    msg = f"成功: {output_xml_path.name} を作成しました (対象ページ数: {processed_pages})"
    print(msg)
    return IntegrationResult(
        dir_path=dir_path,
        output_xml_path=output_xml_path,
        status="SUCCESS",
        page_count=processed_pages,
        used_orders=sorted(used_orders),
        message=msg,
    )


def integrate_xml_in_target_dir(
    target_dir: Path, template_dir: Path | None = None
) -> BatchIntegrationResult:
    """Batch integrate partial XMLs in all target directories (#5-4, #5-z).

    Args:
        target_dir: 処理対象ルートディレクトリ
        template_dir: テンプレート配置ディレクトリ

    Returns:
        BatchIntegrationResult オブジェクト
    """
    target_dir = Path(target_dir).resolve()
    target_dirs = find_integration_targets(target_dir)

    result = BatchIntegrationResult(
        target_dir=target_dir, total_dirs=len(target_dirs)
    )

    if not target_dirs:
        print(f"対象ディレクトリが見つかりませんでした: {target_dir}")
        return result

    print(f"XML部分統合PG 開始: 対象ディレクトリ数={len(target_dirs)}")

    for d in target_dirs:
        res = integrate_single_dir(d, template_dir=template_dir)
        result.results.append(res)
        if res.status == "SUCCESS":
            result.success_count += 1
        elif res.status == "SKIPPED":
            result.skipped_count += 1
        elif res.status == "FAILED":
            result.failed_count += 1
            if res.error_message:
                result.errors.append(f"{d.name}: {res.error_message}")

    # 作業完了メッセージ (#5-z)
    print(
        f"作業完了: 成功={result.success_count}, スキップ={result.skipped_count}, 失敗={result.failed_count}"
    )
    return result


def main(argv: list[str] | None = None) -> int:
    """CLI entry point for XML partial integrator (#5 XML部分統合PG).

    Args:
        argv: コマンドライン引数リスト (省略時は sys.argv[1:])

    Returns:
        終了コード (0: 成功, 1: 失敗)
    """
    parser = argparse.ArgumentParser(
        description="XML(部分)を統合してpdfに対して1XMLとなるよう成形する『XML部分統合PG』"
    )
    parser.add_argument(
        "target_dir",
        type=Path,
        help="処理対象ディレクトリパス (例: tests/fixtures/27 または C:/transfer-xml/24)",
    )
    parser.add_argument(
        "--template-dir",
        dest="template_dir",
        type=Path,
        default=None,
        help="テンプレート配置ディレクトリ (デフォルト: config/template)",
    )

    args = parser.parse_args(argv)

    try:
        batch_res = integrate_xml_in_target_dir(
            target_dir=args.target_dir, template_dir=args.template_dir
        )
        return 1 if batch_res.failed_count > 0 else 0
    except (FileNotFoundError, NotADirectoryError, ValueError) as e:
        print(f"エラー: {e}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("\n処理がユーザーにより中断されました。", file=sys.stderr)
        return 130


if __name__ == "__main__":
    sys.exit(main())
