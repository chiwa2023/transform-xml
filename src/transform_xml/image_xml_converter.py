"""Image to XML partial converter module (#4 画像XML部分変換PG)."""

import argparse
import base64
import datetime
import json
import os
import re
import sys
import urllib.error
import urllib.request
from dataclasses import asdict, dataclass, field
from pathlib import Path

# 直接スクリプト実行時にもパッケージパスを解決できるように追加
_SRC_DIR = Path(__file__).resolve().parent.parent
if str(_SRC_DIR) not in sys.path:
    sys.path.insert(0, str(_SRC_DIR))

# 定数定義
IMAGE_CONVERT_LOG_NAME = "image_convert.log"
IMAGE_CONVERT_JSON_NAME = "image_convert.json"
XML_CONVERT_LOG_NAME = "xml_convert.log"
XML_CONVERT_JSON_NAME = "xml_convert.json"
DEFAULT_CLAUDE_MODEL = "claude-3-5-sonnet-20241022"


@dataclass
class PageXmlRecord:
    """Record of a single page XML conversion."""

    page_number: int  # 1-based page index
    image_filename: str
    xml_filename: str
    xml_path: str
    form_number: int | None = None  # 様式番号 (1, 2, 6, 7, 13, 15, 17, 20 など)
    branch_number: int | None = None  # 様式枝番 (1, 2, 3, 8 など)
    status: str = "SUCCESS"  # "SUCCESS", "EMPTY", "FAILED"
    error_message: str | None = None
    converted_at: str = field(
        default_factory=lambda: datetime.datetime.now().astimezone().isoformat()
    )


@dataclass
class DirXmlConversionResult:
    """Result of converting images to XML for a single directory."""

    dir_path: Path
    total_images: int = 0
    converted_xmls: int = 0
    empty_xmls: int = 0
    failed_xmls: int = 0
    page_records: list[PageXmlRecord] = field(default_factory=list)
    status: str = "COMPLETED"  # "COMPLETED", "PARTIAL", "FAILED"
    error_message: str | None = None
    started_at: str = field(
        default_factory=lambda: datetime.datetime.now().astimezone().isoformat()
    )
    finished_at: str | None = None


@dataclass
class BatchXmlConversionResult:
    """Result of batch image-to-XML conversion for a root directory."""

    target_dir: Path
    target_dirs_count: int = 0
    success_dirs_count: int = 0
    failed_dirs_count: int = 0
    total_xmls_converted: int = 0
    total_empty_xmls: int = 0
    dir_results: list[DirXmlConversionResult] = field(default_factory=list)
    errors: list[tuple[Path, str]] = field(default_factory=list)


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


def resolve_env_variable(
    var_name: str,
    env_file_path: Path | None = None,
    default: str = "",
) -> str:
    """Resolve an environment variable from specified file, candidates, or os.environ."""
    # 1. Specified file
    if env_file_path and env_file_path.is_file():
        vars_dict = load_env_file(env_file_path)
        if var_name in vars_dict and vars_dict[var_name]:
            return vars_dict[var_name]

    # 2. Candidate files
    candidate_paths = [
        Path("config") / "settings.env",
        Path(".env"),
        Path("config") / ".env",
    ]
    for p in candidate_paths:
        if p.is_file():
            vars_dict = load_env_file(p)
            if var_name in vars_dict and vars_dict[var_name]:
                return vars_dict[var_name]

    # 3. os.environ
    if var_name in os.environ and os.environ[var_name]:
        return os.environ[var_name]

    return default


def find_xml_convert_targets(target_dir: Path) -> list[Path]:
    """Find directories that have image conversion log but no XML conversion log (#4-a).

    Args:
        target_dir: Target root directory.

    Returns:
        Sorted list of Path objects for target directories.
    """
    if not target_dir.exists():
        raise FileNotFoundError(f"指定されたディレクトリが存在しません: {target_dir}")
    if not target_dir.is_dir():
        raise NotADirectoryError(f"指定されたパスはディレクトリではありません: {target_dir}")

    targets: list[Path] = []
    # target_dir 自体も対象になり得るかチェック
    candidates = [target_dir] + [p for p in target_dir.rglob("*") if p.is_dir()]

    for d in candidates:
        has_image_log = (
            (d / IMAGE_CONVERT_LOG_NAME).is_file()
            or (d / IMAGE_CONVERT_JSON_NAME).is_file()
        )
        has_xml_log = (
            (d / XML_CONVERT_LOG_NAME).is_file()
            or (d / XML_CONVERT_JSON_NAME).is_file()
        )
        if has_image_log and not has_xml_log:
            targets.append(d)

    targets.sort(key=lambda p: str(p))
    return targets


def find_page_images(image_dir: Path) -> list[Path]:
    """Retrieve images in page order from the given directory (#4-b).

    Prioritizes page order listed in image_convert.json if available.
    """
    json_path = image_dir / IMAGE_CONVERT_JSON_NAME
    if json_path.is_file():
        try:
            with open(json_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            records = data.get("page_records", [])
            images: list[Path] = []
            for rec in sorted(records, key=lambda r: r.get("page_number", 0)):
                fn = rec.get("image_filename")
                if fn:
                    img_path = image_dir / fn
                    if img_path.is_file():
                        images.append(img_path)
            if images:
                return images
        except Exception:
            pass

    # フォールバック: ディレクトリ内の画像ファイルを自然順序で取得
    images = []
    for ext in ("*.png", "*.PNG", "*.jpg", "*.JPG", "*.jpeg", "*.JPEG"):
        images.extend(image_dir.glob(ext))

    # ユニーク化してソート
    unique_images = list(dict.fromkeys(images))
    unique_images.sort(key=lambda p: p.name)
    return unique_images


def extract_form_info_from_text(text: str) -> tuple[int | None, int | None]:
    """Extract form number and branch number from OCR text (#4-f, #4-e000~#4-e013).

    Returns:
        Tuple of (form_number, branch_number).
        If not applicable or audit opinion, returns (None, None).
    """
    if not text:
        return None, None

    # 監査意見書などの対象外判定 (#4-e013)
    if "監査意見書" in text or "監査報告書" in text:
        return None, None

    # 全角数字を半角に正規化
    normalized = text.translate(str.maketrans("０１２３４５６７８９（）", "0123456789()"))

    # 様式番号（「その1」「その 1」「(その1)」など）の抽出
    # パターン: (その(\d+)) または その(\d+)
    match = re.search(r"[（(]?\s*その\s*(\d+)\s*[)）]?", normalized)
    if not match:
        return None, None

    form_num = int(match.group(1))
    branch_num: int | None = None

    # 様式ごとの枝番判定
    if form_num in (7, 8, 11, 12):
        # 収入の内訳: 1: 個人, 2: 法人その他の団体, 3: 政治団体
        if "法人その他の団体" in normalized or "法人" in normalized:
            branch_num = 2
        elif "政治団体" in normalized:
            branch_num = 3
        elif "個人" in normalized:
            branch_num = 1
    elif form_num == 14:
        # 経常経費の内訳: 2: 光熱水費, 3: 備品・消耗品費, 4: 事務所費
        if "光熱水費" in normalized:
            branch_num = 2
        elif "備品" in normalized or "消耗品費" in normalized:
            branch_num = 3
        elif "事務所費" in normalized:
            branch_num = 4
    elif form_num == 15:
        # 政治活動費の内訳
        if (
            "組織活動費" in normalized
            or "組織対策費" in normalized
            or "渉外費" in normalized
            or "行事費" in normalized
            or "1.組織活動費" in normalized
            or "1. 組織活動費" in normalized
        ):
            branch_num = 1
        elif "選挙関係費" in normalized or "2.選挙関係費" in normalized:
            branch_num = 2
        elif "機関紙" in normalized or "3.機関紙" in normalized:
            branch_num = 3
        elif "宣伝事業費" in normalized or "4.宣伝事業費" in normalized:
            branch_num = 4
        elif "パーティー" in normalized or "5.政治資金パーティー" in normalized:
            branch_num = 5
        elif "その他の事業費" in normalized or "6.その他の事業費" in normalized:
            branch_num = 6
        elif "調査研究費" in normalized or "7.調査研究費" in normalized:
            branch_num = 7
        elif (
            "寄付・交付金" in normalized
            or "寄付金" in normalized
            or "寄附金" in normalized
            or "交付金" in normalized
            or "8.寄付" in normalized
            or "8. 寄付" in normalized
        ):
            branch_num = 8
        elif "その他の経費" in normalized or "9.その他の経費" in normalized:
            branch_num = 9

    return form_num, branch_num


def get_xml_template(form_num: int | None, branch_num: int | None) -> str:
    """Retrieve XML template skeleton for the given form and branch (#4-g).

    Args:
        form_num: Form number (e.g., 1, 2, 6, 7, 13, 15, 17, 20).
        branch_num: Branch number (e.g., 1, 2, 3, 8).

    Returns:
        XML snippet string. If form_num is None, returns empty string.
    """
    if form_num is None:
        return ""

    if form_num == 1:
        return (
            "        <SYUUSHI07_01>\n"
            "                <SHEET>\n"
            "                        <HOUKOKU_NEN></HOUKOKU_NEN>\n"
            "                        <KAISAI_DT></KAISAI_DT>\n"
            "                        <DANTAI_NM></DANTAI_NM>\n"
            "                        <DANTAI_KANA></DANTAI_KANA>\n"
            "                        <JIM_ADR></JIM_ADR>\n"
            "                        <JIM_APA_ADR></JIM_APA_ADR>\n"
            "                        <DAI_NM1></DAI_NM1>\n"
            "                        <DAI_NM2></DAI_NM2>\n"
            "                        <KAI_NM1></KAI_NM1>\n"
            "                        <KAI_NM2></KAI_NM2>\n"
            "                        <TANTOU1_NM1></TANTOU1_NM1>\n"
            "                        <TANTOU1_NM2></TANTOU1_NM2>\n"
            "                        <TANTOU1_TEL></TANTOU1_TEL>\n"
            "                        <TANTOU2_NM1></TANTOU2_NM1>\n"
            "                        <TANTOU2_NM2></TANTOU2_NM2>\n"
            "                        <TANTOU2_TEL></TANTOU2_TEL>\n"
            "                        <TANTOU3_NM1></TANTOU3_NM1>\n"
            "                        <TANTOU3_NM2></TANTOU3_NM2>\n"
            "                        <TANTOU3_TEL></TANTOU3_TEL>\n"
            "                        <DANTAI_KBN></DANTAI_KBN>\n"
            "                        <KATU_KUKI></KATU_KUKI>\n"
            "                        <SIKIN_UMU></SIKIN_UMU>\n"
            "                        <KOSYOKU_NM></KOSYOKU_NM>\n"
            "                        <KOSYOKU_KBN></KOSYOKU_KBN>\n"
            "                        <SIKIN_TODOKE_NM1></SIKIN_TODOKE_NM1>\n"
            "                        <SIKIN_TODOKE_NM2></SIKIN_TODOKE_NM2>\n"
            "                        <SIKIN_KIKAN1></SIKIN_KIKAN1>\n"
            "                        <SIKIN_KIKAN2></SIKIN_KIKAN2>\n"
            "                        <SIKIN_KIKAN_FUKUSU></SIKIN_KIKAN_FUKUSU>\n"
            "                        <GIIN_DANTAI_KBN></GIIN_DANTAI_KBN>\n"
            "                        <GIIN1_KOSYOKU_NM_1></GIIN1_KOSYOKU_NM_1>\n"
            "                        <GIIN1_KOSYOKU_NM_2></GIIN1_KOSYOKU_NM_2>\n"
            "                        <GIIN1_KOSYOKU_NM></GIIN1_KOSYOKU_NM>\n"
            "                        <GIIN1_KOSYOKU_KBN></GIIN1_KOSYOKU_KBN>\n"
            "                        <GIIN_KIKAN1></GIIN_KIKAN1>\n"
            "                        <GIIN_KIKAN2></GIIN_KIKAN2>\n"
            "                        <GIIN_KIKAN_FUKUSU></GIIN_KIKAN_FUKUSU>\n"
            "                        <GIIN2_KOSYOKU_NM_1></GIIN2_KOSYOKU_NM_1>\n"
            "                        <GIIN2_KOSYOKU_NM_2></GIIN2_KOSYOKU_NM_2>\n"
            "                        <GIIN2_KOSYOKU_NM></GIIN2_KOSYOKU_NM>\n"
            "                        <GIIN2_KOSYOKU_KBN></GIIN2_KOSYOKU_KBN>\n"
            "                        <GIIN3_KOSYOKU_NM_1></GIIN3_KOSYOKU_NM_1>\n"
            "                        <GIIN3_KOSYOKU_NM_2></GIIN3_KOSYOKU_NM_2>\n"
            "                        <GIIN3_KOSYOKU_NM></GIIN3_KOSYOKU_NM>\n"
            "                        <GIIN3_KOSYOKU_KBN></GIIN3_KOSYOKU_KBN>\n"
            "                </SHEET>\n"
            "        </SYUUSHI07_01>\n"
        )

    if form_num == 2:
        return (
            "        <SYUUSHI07_02>\n"
            "                <SHEET>\n"
            "                        <SYUNYU_SGK></SYUNYU_SGK>\n"
            "                        <ZENNEN_KKS_GK></ZENNEN_KKS_GK>\n"
            "                        <HONNEN_SYUNYU_GK></HONNEN_SYUNYU_GK>\n"
            "                        <SISYUTU_SGK></SISYUTU_SGK>\n"
            "                        <YOKUNEN_KKS_GK></YOKUNEN_KKS_GK>\n"
            "                        <KOJIN_FUTAN_KGK></KOJIN_FUTAN_KGK>\n"
            "                        <KOJIN_FUTAN_SU></KOJIN_FUTAN_SU>\n"
            "                        <KOJIN_KIFU_GK></KOJIN_KIFU_GK>\n"
            "                        <KOJIN_KIFU_BIKOU></KOJIN_KIFU_BIKOU>\n"
            "                        <TOKUTEI_KIFU_GK></TOKUTEI_KIFU_GK>\n"
            "                        <TOKUTEI_KIFU_BIKOU></TOKUTEI_KIFU_BIKOU>\n"
            "                        <HOJIN_KIFU_GK></HOJIN_KIFU_GK>\n"
            "                        <HOJIN_KIFU_BIKOU></HOJIN_KIFU_BIKOU>\n"
            "                        <SEIJI_KIFU_GK></SEIJI_KIFU_GK>\n"
            "                        <SEIJI_KIFU_BIKOU></SEIJI_KIFU_BIKOU>\n"
            "                        <KIFU_SKEI_GK></KIFU_SKEI_GK>\n"
            "                        <KIFU_SKEI_BIKOU></KIFU_SKEI_BIKOU>\n"
            "                        <ATUSEN_GK></ATUSEN_GK>\n"
            "                        <ATUSEN_BIKOU></ATUSEN_BIKOU>\n"
            "                        <TOKUMEI_KIFU_GK></TOKUMEI_KIFU_GK>\n"
            "                        <TOKUMEI_KIFU_BIKOU></TOKUMEI_KIFU_BIKOU>\n"
            "                        <KIFU_GKEI_GK></KIFU_GKEI_GK>\n"
            "                        <KIFU_GKEI_BIKOU></KIFU_GKEI_BIKOU>\n"
            "                </SHEET>\n"
            "        </SYUUSHI07_02>\n"
        )

    if form_num == 6:
        return (
            "        <SYUUSHI07_06>\n"
            "                <SHEET>\n"
            "                        <KINGAKU_GK></KINGAKU_GK>\n"
            "                        <MIMAN_GK></MIMAN_GK>\n"
            "                </SHEET>\n"
            "        </SYUUSHI07_06>\n"
        )

    if form_num == 7:
        k_tag = f"KUBUN{branch_num if branch_num else 1}"
        return (
            f"                <{k_tag}>\n"
            "                        <SHEET>\n"
            "                                <KINGAKU_GK></KINGAKU_GK>\n"
            "                                <SONOTA_GK></SONOTA_GK>\n"
            "                        </SHEET>\n"
            f"                </{k_tag}>\n"
        )

    if form_num == 13:
        return (
            "        <SYUUSHI07_13>\n"
            "                <SHEET>\n"
            "                        <JINKENHI_GK></JINKENHI_GK>\n"
            "                        <JINKENHI_KOUFU></JINKENHI_KOUFU>\n"
            "                        <JINKENHI_BIKOU></JINKENHI_BIKOU>\n"
            "                        <KOUNETU_GK></KOUNETU_GK>\n"
            "                        <KOUNETU_KOUFU></KOUNETU_KOUFU>\n"
            "                        <KOUNETU_BIKOU></KOUNETU_BIKOU>\n"
            "                        <BIHIN_GK></BIHIN_GK>\n"
            "                        <BIHIN_KOUFU></BIHIN_KOUFU>\n"
            "                        <BIHIN_BIKOU></BIHIN_BIKOU>\n"
            "                        <JIMUSYO_GK></JIMUSYO_GK>\n"
            "                        <JIMUSYO_KOUFU></JIMUSYO_KOUFU>\n"
            "                        <JIMUSYO_BIKOU></JIMUSYO_BIKOU>\n"
            "                        <KEIHI_SKEI_GK></KEIHI_SKEI_GK>\n"
            "                        <KEIHI_SKEI_KOUFU></KEIHI_SKEI_KOUFU>\n"
            "                        <KEIHI_SKEI_BIKOU></KEIHI_SKEI_BIKOU>\n"
            "                        <SOSIKI_GK></SOSIKI_GK>\n"
            "                        <SOSIKI_KOUFU></SOSIKI_KOUFU>\n"
            "                        <SOSIKI_BIKOU></SOSIKI_BIKOU>\n"
            "                        <SENKYO_GK></SENKYO_GK>\n"
            "                        <SENKYO_KOUFU></SENKYO_KOUFU>\n"
            "                        <SENKYO_BIKOU></SENKYO_BIKOU>\n"
            "                        <SONOTA_JIGYO_GK></SONOTA_JIGYO_GK>\n"
            "                        <SONOTA_JIGYO_KOUFU></SONOTA_JIGYO_KOUFU>\n"
            "                        <SONOTA_JIGYO_BIKOU></SONOTA_JIGYO_BIKOU>\n"
            "                        <HAKKOU_JIGYO_GK></HAKKOU_JIGYO_GK>\n"
            "                        <HAKKOU_JIGYO_KOUFU></HAKKOU_JIGYO_KOUFU>\n"
            "                        <HAKKOU_JIGYO_BIKOU></HAKKOU_JIGYO_BIKOU>\n"
            "                        <SENDEN_GK></SENDEN_GK>\n"
            "                        <SENDEN_KOUFU></SENDEN_KOUFU>\n"
            "                        <SENDEN_BIKOU></SENDEN_BIKOU>\n"
            "                        <KAISAI_GK></KAISAI_GK>\n"
            "                        <KAISAI_KOUFU></KAISAI_KOUFU>\n"
            "                        <KAISAI_BIKOU></KAISAI_BIKOU>\n"
            "                        <SONOTA_GK></SONOTA_GK>\n"
            "                        <SONOTA_KOUFU></SONOTA_KOUFU>\n"
            "                        <SONOTA_BIKOU></SONOTA_BIKOU>\n"
            "                        <CYOUSA_GK></CYOUSA_GK>\n"
            "                        <CYOUSA_KOUFU></CYOUSA_KOUFU>\n"
            "                        <CYOUSA_BIKOU></CYOUSA_BIKOU>\n"
            "                        <KIFU_GK></KIFU_GK>\n"
            "                        <KIFU_KOUFU></KIFU_KOUFU>\n"
            "                        <KIFU_BIKOU></KIFU_BIKOU>\n"
            "                        <SONOTA_KEIHI_GK></SONOTA_KEIHI_GK>\n"
            "                        <SONOTA_KEIHI_KOUFU></SONOTA_KEIHI_KOUFU>\n"
            "                        <SONOTA_KEIHI_BIKOU></SONOTA_KEIHI_BIKOU>\n"
            "                        <KATUDOU_SKEI_GK></KATUDOU_SKEI_GK>\n"
            "                        <KATUDOU_SKEI_KOUFU></KATUDOU_SKEI_KOUFU>\n"
            "                        <KATUDOU_SKEI_BIKOU></KATUDOU_SKEI_BIKOU>\n"
            "                        <GKEI_GK></GKEI_GK>\n"
            "                </SHEET>\n"
            "        </SYUUSHI07_13>\n"
        )

    if form_num == 15:
        if branch_num == 8:
            return (
                "                <KUBUN8>\n"
                "                        <SHEET>\n"
                "                                <HIMOKU></HIMOKU>\n"
                "                                <KINGAKU_GK></KINGAKU_GK>\n"
                "                                <SONOTA_GK></SONOTA_GK>\n"
                "                        </SHEET>\n"
                "                </KUBUN8>\n"
            )
        return (
            "                        <SHEET>\n"
            "                                <HIMOKU></HIMOKU>\n"
            "                                <KINGAKU_GK></KINGAKU_GK>\n"
            "                                <SONOTA_GK></SONOTA_GK>\n"
            "                        </SHEET>\n"
        )

    if form_num == 17:
        return (
            "        <SYUUSHI07_17>\n"
            "                <SHEET>\n"
            "                        <TOCHI_UMU></TOCHI_UMU>\n"
            "                        <TOCHI_BIKOU></TOCHI_BIKOU>\n"
            "                        <TATEMONO_UMU></TATEMONO_UMU>\n"
            "                        <TATEMONO_BIKOU></TATEMONO_BIKOU>\n"
            "                        <SYAKUCHI_UMU></SYAKUCHI_UMU>\n"
            "                        <SYAKUCHI_BIKOU></SYAKUCHI_BIKOU>\n"
            "                        <DOUSAN_UMU></DOUSAN_UMU>\n"
            "                        <DOUSAN_BIKOU></DOUSAN_BIKOU>\n"
            "                        <YOKIN_UMU></YOKIN_UMU>\n"
            "                        <YOKIN_BIKOU></YOKIN_BIKOU>\n"
            "                        <SINTAKU_UMU></SINTAKU_UMU>\n"
            "                        <SINTAKU_BIKOU></SINTAKU_BIKOU>\n"
            "                        <SYOUKEN_UMU></SYOUKEN_UMU>\n"
            "                        <SYOUKEN_BIKOU></SYOUKEN_BIKOU>\n"
            "                        <SYUSSI_UMU></SYUSSI_UMU>\n"
            "                        <SYUSSI_BIKOU></SYUSSI_BIKOU>\n"
            "                        <KASITUKE_UMU></KASITUKE_UMU>\n"
            "                        <KASITUKE_BIKOU></KASITUKE_BIKOU>\n"
            "                        <SIKIKIN_UMU></SIKIKIN_UMU>\n"
            "                        <SIKIKIN_BIKOU></SIKIKIN_BIKOU>\n"
            "                        <SISETURIYOU_UMU></SISETURIYOU_UMU>\n"
            "                        <SISETURIYOU_BIKOU></SISETURIYOU_BIKOU>\n"
            "                        <KARIIRE_UMU></KARIIRE_UMU>\n"
            "                        <KARIIRE_BIKOU></KARIIRE_BIKOU>\n"
            "                </SHEET>\n"
            "        </SYUUSHI07_17>\n"
        )

    if form_num == 20:
        return (
            "        <SYUUSHI07_20>\n"
            "                <SHEET>\n"
            "                        <RYOUSYU_UMU></RYOUSYU_UMU>\n"
            "                        <KANSA_IKEN_UMU></KANSA_IKEN_UMU>\n"
            "                        <KANSA_HOUKOKU_UMU></KANSA_HOUKOKU_UMU>\n"
            "                        <SENSEI_DT></SENSEI_DT>\n"
            "                        <DANTAI_NM></DANTAI_NM>\n"
            "                        <KAI_NM1></KAI_NM1>\n"
            "                        <KAI_NM2></KAI_NM2>\n"
            "                        <DAI_NM1></DAI_NM1>\n"
            "                        <DAI_NM2></DAI_NM2>\n"
            "                </SHEET>\n"
            "        </SYUUSHI07_20>\n"
        )

    # 汎用様式
    tag = f"SYUUSHI07_{form_num:02d}"
    return f"        <{tag}>\n                <SHEET>\n                </SHEET>\n        </{tag}>\n"


class BaseOcrEngine:
    """Base class for OCR engine abstraction (#4-d)."""

    def process_image(
        self,
        image_path: Path,
    ) -> tuple[int | None, int | None, str, str | None]:
        """Process image and return (form_number, branch_number, xml_content, error_message).

        Returns:
            Tuple of:
            - form_number: Form number (int) or None if not applicable / failed.
            - branch_number: Branch number (int) or None.
            - xml_content: Resulting XML snippet (str). Empty string if failed/not applicable.
            - error_message: Error message or None if successful.
        """
        raise NotImplementedError


class ClaudeOcrEngine(BaseOcrEngine):
    """OCR engine using Anthropic Claude Vision API (#4-d, #4-e)."""

    def __init__(
        self,
        api_key: str,
        model: str = DEFAULT_CLAUDE_MODEL,
        api_url: str = "https://api.anthropic.com/v1/messages",
        timeout: float = 60.0,
    ) -> None:
        self.api_key = api_key
        self.model = model
        self.api_url = api_url
        self.timeout = timeout

    def process_image(
        self,
        image_path: Path,
    ) -> tuple[int | None, int | None, str, str | None]:
        """Send image to Claude Vision API and extract XML snippet and form info."""
        if not self.api_key:
            return None, None, "", "CLAUDE_API_KEY が設定されていません"

        try:
            # 画像読み込み & Base64 エンコード
            with open(image_path, "rb") as f:
                img_bytes = f.read()
            media_type = "image/png"
            if image_path.suffix.lower() in (".jpg", ".jpeg"):
                media_type = "image/jpeg"

            img_b64 = base64.b64encode(img_bytes).decode("ascii")

            prompt = (
                "この画像は日本の政治資金収支報告書の1ページです。\n"
                "1. 画像内の様式番号（例: その1、その2、その6、その7、その13、その15、その17、その20）と、"
                "枝番（その7の法人/政治団体/個人、その15の組織活動費/寄付交付金など）を特定してください。\n"
                "2. 監査意見書など「その～」が存在しないページ、または対象外ページの場合は様式番号を null としてください。\n"
                "3. 総務省政治資金収支報告書ソフトウェア互換の部分XML（例: <SYUUSHI07_01>... または <SHEET>... または <KUBUN2>...）を抽出・生成してください。\n"
                "回答は以下のJSON形式のみを出力してください。Markdownバッククォート(```json等)は付けず純粋なJSONで返してください:\n"
                '{"form_number": <int または null>, "branch_number": <int または null>, "xml": "<生成されたXML文字列>"}'
            )

            request_data = {
                "model": self.model,
                "max_tokens": 4096,
                "messages": [
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "image",
                                "source": {
                                    "type": "base64",
                                    "media_type": media_type,
                                    "data": img_b64,
                                },
                            },
                            {
                                "type": "text",
                                "text": prompt,
                            },
                        ],
                    }
                ],
            }

            req = urllib.request.Request(
                self.api_url,
                data=json.dumps(request_data).encode("utf-8"),
                headers={
                    "Content-Type": "application/json",
                    "x-api-key": self.api_key,
                    "anthropic-version": "2023-06-01",
                },
                method="POST",
            )

            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                resp_json = json.loads(resp.read().decode("utf-8"))

            content_blocks = resp_json.get("content", [])
            reply_text = "".join(
                b.get("text", "") for b in content_blocks if b.get("type") == "text"
            ).strip()

            # JSONパース
            cleaned_reply = reply_text
            if cleaned_reply.startswith("```"):
                cleaned_reply = re.sub(r"^```(?:json)?\s*", "", cleaned_reply)
                cleaned_reply = re.sub(r"\s*```$", "", cleaned_reply)

            parsed = json.loads(cleaned_reply)
            form_num = parsed.get("form_number")
            branch_num = parsed.get("branch_number")
            xml_str = parsed.get("xml", "")

            # XMLが空で様式番号がある場合はテンプレートをフォールバック
            if not xml_str and form_num is not None:
                xml_str = get_xml_template(form_num, branch_num)

            return form_num, branch_num, xml_str, None

        except Exception as e:
            return None, None, "", str(e)


class LocalOcrEngine(BaseOcrEngine):
    """Local non-AI OCR engine using pytesseract if available, or safe fallback (#4-d)."""

    def __init__(self, lang: str = "jpn") -> None:
        self.lang = lang
        self._tesseract_available: bool | None = None

    def _check_tesseract(self) -> bool:
        if self._tesseract_available is not None:
            return self._tesseract_available
        try:
            import pytesseract  # type: ignore[import-not-found]
            from PIL import Image

            # 単純なインポートチェック
            self._tesseract_available = True
        except ImportError:
            self._tesseract_available = False
        return self._tesseract_available

    def process_image(
        self,
        image_path: Path,
    ) -> tuple[int | None, int | None, str, str | None]:
        """Perform OCR via pytesseract and generate XML skeleton (#4-f, #4-g)."""
        if not self._check_tesseract():
            # pytesseract がない環境でも安全に空XMLを作成 (#4-i)
            # 画像ファイル名から様式番号が推測できる場合のフォールバック等も考慮
            return None, None, "", "pytesseract がインストールされていません (空ファイル作成)"

        try:
            import pytesseract
            from PIL import Image

            with Image.open(image_path) as img:
                text = pytesseract.image_to_string(img, lang=self.lang)

            form_num, branch_num = extract_form_info_from_text(text)
            xml_content = get_xml_template(form_num, branch_num)
            return form_num, branch_num, xml_content, None
        except Exception as e:
            return None, None, "", str(e)


class MockOcrEngine(BaseOcrEngine):
    """Mock/Preset OCR engine for unit tests and offline testing (#4-y1, #4-y2)."""

    def __init__(
        self,
        default_form_num: int | None = None,
        default_branch_num: int | None = None,
        custom_mapping: dict[str, tuple[int | None, int | None, str]] | None = None,
    ) -> None:
        self.default_form_num = default_form_num
        self.default_branch_num = default_branch_num
        self.custom_mapping = custom_mapping or {}

    def process_image(
        self,
        image_path: Path,
    ) -> tuple[int | None, int | None, str, str | None]:
        img_name = image_path.name

        if img_name in self.custom_mapping:
            form_num, branch_num, xml_content = self.custom_mapping[img_name]
            return form_num, branch_num, xml_content, None

        if self.default_form_num is not None:
            xml_content = get_xml_template(self.default_form_num, self.default_branch_num)
            return self.default_form_num, self.default_branch_num, xml_content, None

        # 監査意見書や末尾などの簡易ルール
        return None, None, "", None


def get_ocr_engine(
    engine_name: str | None = None,
    env_file_path: Path | None = None,
    api_key: str | None = None,
    model: str | None = None,
) -> BaseOcrEngine:
    """Factory to create the appropriate OCR engine based on settings (#4-d, #4-e).

    Args:
        engine_name: "claude", "local", or "mock" / "dummy".
        env_file_path: Optional path to settings.env.
        api_key: Direct Claude API key if provided.
        model: Direct Claude model name if provided.

    Returns:
        BaseOcrEngine instance.
    """
    resolved_engine = engine_name or resolve_env_variable(
        "OCR_ENGINE", env_file_path=env_file_path, default=""
    ).lower()

    resolved_api_key = api_key or resolve_env_variable(
        "CLAUDE_API_KEY", env_file_path=env_file_path, default=""
    )

    resolved_model = model or resolve_env_variable(
        "CLAUDE_MODEL", env_file_path=env_file_path, default=DEFAULT_CLAUDE_MODEL
    )

    if resolved_engine in ("claude", "ai") or (not resolved_engine and resolved_api_key):
        return ClaudeOcrEngine(api_key=resolved_api_key, model=resolved_model)

    return LocalOcrEngine()


def write_xml_conversion_logs(
    output_dir: Path,
    result: DirXmlConversionResult,
) -> tuple[Path, Path]:
    """Write human-readable and JSON XML conversion logs to directory (#4-j).

    Args:
        output_dir: Target directory where XMLs and logs reside.
        result: Conversion result details.

    Returns:
        Tuple of (log_file_path, json_file_path).
    """
    output_dir.mkdir(parents=True, exist_ok=True)
    log_path = output_dir / XML_CONVERT_LOG_NAME
    json_path = output_dir / XML_CONVERT_JSON_NAME

    # 人間が読めるテキストログの出力
    with open(log_path, "w", encoding="utf-8") as f:
        f.write("==================================================\n")
        f.write("[XML変換作業ログ]\n")
        f.write(f"格納先ディレクトリ: {output_dir.resolve()}\n")
        f.write(f"処理開始日時: {result.started_at}\n")
        f.write(f"処理終了日時: {result.finished_at}\n")
        f.write(f"総画像数: {result.total_images}\n")
        f.write(f"XML変換成功数: {result.converted_xmls}\n")
        f.write(f"空XML作成数: {result.empty_xmls}\n")
        f.write(f"XML変換失敗数: {result.failed_xmls}\n")
        f.write(f"変換ステータス: {result.status}\n")
        if result.error_message:
            f.write(f"エラー内容: {result.error_message}\n")
        f.write("--------------------------------------------------\n")
        f.write("ページ別変換記録:\n")
        for rec in result.page_records:
            f.write(
                f"  ページ {rec.page_number:04d}: "
                f"画像={rec.image_filename}, "
                f"XML={rec.xml_filename}, "
                f"様式={rec.form_number}, "
                f"枝番={rec.branch_number}, "
                f"状態={rec.status}, "
                f"日時={rec.converted_at}\n"
            )
            if rec.error_message:
                f.write(f"    エラー: {rec.error_message}\n")
        f.write("==================================================\n")

    # 機械判読用 JSON ログの出力 (#5 XML部分統合PGとの連携用)
    serializable = {
        "dir_name": output_dir.name,
        "dir_path": str(output_dir.resolve()),
        "total_images": result.total_images,
        "converted_xmls": result.converted_xmls,
        "empty_xmls": result.empty_xmls,
        "failed_xmls": result.failed_xmls,
        "status": result.status,
        "error_message": result.error_message,
        "started_at": result.started_at,
        "finished_at": result.finished_at,
        "page_records": [asdict(rec) for rec in result.page_records],
    }
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(serializable, f, ensure_ascii=False, indent=2)

    return log_path, json_path


def convert_images_in_dir(
    image_dir: Path,
    ocr_engine: BaseOcrEngine,
) -> DirXmlConversionResult:
    """Convert images in a single directory to XML partial files (#4-b~#4-j).

    Args:
        image_dir: Directory containing images and image_convert.log.
        ocr_engine: OCR engine to extract form info and XML content.

    Returns:
        DirXmlConversionResult detailing the conversion outcome.
    """
    resolved_dir = Path(image_dir).resolve()
    images = find_page_images(resolved_dir)

    result = DirXmlConversionResult(
        dir_path=resolved_dir,
        total_images=len(images),
    )

    # #4-k 4-bから4-jを取得した画像の分だけ繰り返す
    for idx, img_path in enumerate(images, start=1):
        # 命名規則: {pdfファイル名}_{総ページ番号}.xml (#4-h)
        xml_filename = f"{img_path.stem}.xml"
        xml_path = resolved_dir / xml_filename

        try:
            form_num, branch_num, xml_content, err = ocr_engine.process_image(img_path)

            # #4-i 読み取りができなかった場合でも空ファイルを作成すること
            # (form_num is None または xml_content が空文字の場合も空ファイル作成)
            content_to_write = xml_content if xml_content else ""

            with open(xml_path, "w", encoding="utf-8") as f:
                f.write(content_to_write)

            if err:
                status = "EMPTY" if xml_path.is_file() else "FAILED"
                if status == "EMPTY":
                    result.empty_xmls += 1
                else:
                    result.failed_xmls += 1
                rec = PageXmlRecord(
                    page_number=idx,
                    image_filename=img_path.name,
                    xml_filename=xml_filename,
                    xml_path=str(xml_path),
                    form_number=form_num,
                    branch_number=branch_num,
                    status=status,
                    error_message=err,
                )
            elif not content_to_write:
                result.empty_xmls += 1
                rec = PageXmlRecord(
                    page_number=idx,
                    image_filename=img_path.name,
                    xml_filename=xml_filename,
                    xml_path=str(xml_path),
                    form_number=form_num,
                    branch_number=branch_num,
                    status="EMPTY",
                )
            else:
                result.converted_xmls += 1
                rec = PageXmlRecord(
                    page_number=idx,
                    image_filename=img_path.name,
                    xml_filename=xml_filename,
                    xml_path=str(xml_path),
                    form_number=form_num,
                    branch_number=branch_num,
                    status="SUCCESS",
                )

            result.page_records.append(rec)

        except Exception as e:
            # 例外時でも空ファイルを作成 (#4-i)
            try:
                if not xml_path.exists():
                    xml_path.touch()
            except Exception:
                pass

            result.failed_xmls += 1
            rec = PageXmlRecord(
                page_number=idx,
                image_filename=img_path.name,
                xml_filename=xml_filename,
                xml_path=str(xml_path),
                form_number=None,
                branch_number=None,
                status="FAILED",
                error_message=str(e),
            )
            result.page_records.append(rec)

    # ステータス判定
    if result.failed_xmls == 0:
        result.status = "COMPLETED"
    elif result.converted_xmls > 0 or result.empty_xmls > 0:
        result.status = "PARTIAL"
    else:
        result.status = "FAILED"

    result.finished_at = datetime.datetime.now().astimezone().isoformat()

    # #4-j ディレクトリ内に格納されたXML変換ログに記録追加
    write_xml_conversion_logs(resolved_dir, result)

    return result


def convert_xmls_in_target_dir(
    target_dir: Path | str,
    ocr_engine: BaseOcrEngine | None = None,
    engine_name: str | None = None,
    env_file_path: Path | None = None,
    api_key: str | None = None,
    model: str | None = None,
) -> BatchXmlConversionResult:
    """Execute XML partial conversion for target directory (#4 画像XML部分変換PG).

    Args:
        target_dir: Target directory (scanned recursively for target directories).
        ocr_engine: Optional pre-configured OCR engine.
        engine_name: "claude", "local", or "mock".
        env_file_path: Path to settings.env.
        api_key: Claude API key.
        model: Claude model name.

    Returns:
        BatchXmlConversionResult containing operation summary.
    """
    resolved_dir = Path(target_dir).resolve()
    if not resolved_dir.exists():
        raise FileNotFoundError(f"指定されたディレクトリが存在しません: {resolved_dir}")
    if not resolved_dir.is_dir():
        raise NotADirectoryError(f"指定されたパスはディレクトリではありません: {resolved_dir}")

    # OCRエンジンの解決
    active_engine = ocr_engine or get_ocr_engine(
        engine_name=engine_name,
        env_file_path=env_file_path,
        api_key=api_key,
        model=model,
    )

    print("==================================================")
    print("[#4 画像XML部分変換PG] 起動条件:")
    print(f"  処理対象ディレクトリ: {resolved_dir}")
    print(f"  OCRエンジン: {active_engine.__class__.__name__}")
    print("==================================================")

    # #4-a 指定処理ディレクトリの下位ディレクトリから対象ディレクトリを抽出
    target_subdirs = find_xml_convert_targets(resolved_dir)

    batch_result = BatchXmlConversionResult(
        target_dir=resolved_dir,
        target_dirs_count=len(target_subdirs),
    )

    if not target_subdirs:
        print("  情報: 画像変換ログが存在し、XML未変換の対象ディレクトリは見つかりませんでした。")
    else:
        print(f"  検出された対象ディレクトリ: {len(target_subdirs)}件")

    # #4-l 4-kを取得した画像ディレクトリの分だけ繰り返す
    for idx, sub_dir in enumerate(target_subdirs, start=1):
        rel_dir = sub_dir.relative_to(resolved_dir) if sub_dir.is_relative_to(resolved_dir) else sub_dir
        print(f"\n[{idx}/{len(target_subdirs)}] XML変換処理中: {rel_dir}")

        try:
            dir_res = convert_images_in_dir(sub_dir, active_engine)
            batch_result.dir_results.append(dir_res)
            batch_result.total_xmls_converted += dir_res.converted_xmls
            batch_result.total_empty_xmls += dir_res.empty_xmls

            if dir_res.status == "COMPLETED":
                batch_result.success_dirs_count += 1
                print(
                    f"  -> 変換完了: 全{dir_res.total_images}画像 "
                    f"(XML生成: {dir_res.converted_xmls}件, 空XML: {dir_res.empty_xmls}件)"
                )
            else:
                batch_result.failed_dirs_count += 1
                print(
                    f"  -> 一部失敗/失敗: 成功={dir_res.converted_xmls}/{dir_res.total_images}, "
                    f"エラー={dir_res.error_message or 'ページ単位エラー'}",
                    file=sys.stderr,
                )
                batch_result.errors.append((sub_dir, dir_res.error_message or "Directory conversion failure"))

        except Exception as e:
            batch_result.failed_dirs_count += 1
            batch_result.errors.append((sub_dir, str(e)))
            print(f"  -> 処理例外: {e}", file=sys.stderr)

    # #4-z 上記の作業を終えた時点で作業完了メッセージを出して終了する
    print("\n==================================================")
    if batch_result.errors or batch_result.failed_dirs_count > 0:
        print("[#4 画像XML部分変換PG] 作業完了（一部失敗あり）:")
    else:
        print("[#4 画像XML部分変換PG] 作業完了: 画像XML部分変換が正常に終了しました。")
    print(f"  対象ディレクトリ: {resolved_dir}")
    print(f"  処理対象ディレクトリ数: {batch_result.target_dirs_count}件")
    print(f"  変換成功ディレクトリ数: {batch_result.success_dirs_count}件")
    if batch_result.failed_dirs_count > 0:
        print(f"  変換失敗ディレクトリ数: {batch_result.failed_dirs_count}件")
    print(f"  総生成XML数: {batch_result.total_xmls_converted}件")
    print(f"  総空XML数: {batch_result.total_empty_xmls}件")
    print("==================================================")

    return batch_result


def main(argv: list[str] | None = None) -> int:
    """CLI entry point for image to XML partial converter (#4 画像XML部分変換PG)."""
    parser = argparse.ArgumentParser(description="#4 画像XML部分変換PG")
    parser.add_argument(
        "target_dir",
        type=Path,
        help="画像変換ログが存在する下位ディレクトリを含むディレクトリ (再帰走査)",
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
        help=f"Claude Vision モデル名 (デフォルト: {DEFAULT_CLAUDE_MODEL})",
    )

    args = parser.parse_args(argv)

    try:
        result = convert_xmls_in_target_dir(
            target_dir=args.target_dir,
            engine_name=args.ocr_engine,
            env_file_path=args.env_file_path,
            api_key=args.api_key,
            model=args.model,
        )
        return 1 if result.errors or result.failed_dirs_count > 0 else 0
    except (FileNotFoundError, NotADirectoryError, ValueError) as e:
        print(f"エラー: {e}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("\n処理がユーザーにより中断されました。", file=sys.stderr)
        return 130


if __name__ == "__main__":
    sys.exit(main())
