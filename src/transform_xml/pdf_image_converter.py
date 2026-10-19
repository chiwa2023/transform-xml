"""PDF to image converter module (#3 pdf画像変換PG)."""

import argparse
import datetime
import json
import os
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path

# 直接スクリプト実行時にもパッケージパスを解決できるように追加
_SRC_DIR = Path(__file__).resolve().parent.parent
if str(_SRC_DIR) not in sys.path:
    sys.path.insert(0, str(_SRC_DIR))

try:
    import pypdfium2 as pdfium
    from PIL import Image
except ImportError:  # pragma: no cover
    pdfium = None  # type: ignore[assignment]
    Image = None  # type: ignore[assignment]

# 定数定義
DEFAULT_DPI = 200
DEFAULT_FORMAT = "PNG"
IMAGE_CONVERT_LOG_NAME = "image_convert.log"
IMAGE_CONVERT_JSON_NAME = "image_convert.json"


@dataclass
class PageConversionRecord:
    """Record of a single page image conversion."""

    page_number: int  # 1-based page index
    image_filename: str
    image_path: str
    width: int
    height: int
    dpi: int
    status: str  # "SUCCESS" or "FAILED"
    error_message: str | None = None
    converted_at: str = field(
        default_factory=lambda: datetime.datetime.now().astimezone().isoformat()
    )


@dataclass
class PdfConversionResult:
    """Result of converting a single PDF to images."""

    pdf_path: Path
    output_dir: Path
    total_pages: int = 0
    converted_pages: int = 0
    failed_pages: int = 0
    page_records: list[PageConversionRecord] = field(default_factory=list)
    status: str = "COMPLETED"  # "COMPLETED", "PARTIAL", or "FAILED"
    error_message: str | None = None
    started_at: str = field(
        default_factory=lambda: datetime.datetime.now().astimezone().isoformat()
    )
    finished_at: str | None = None


@dataclass
class BatchConversionResult:
    """Result of batch PDF conversion for a directory."""

    target_dir: Path
    pdf_count: int = 0
    success_pdf_count: int = 0
    failed_pdf_count: int = 0
    total_pages_converted: int = 0
    pdf_results: list[PdfConversionResult] = field(default_factory=list)
    errors: list[tuple[Path, str]] = field(default_factory=list)


def find_pdf_files(target_dir: Path) -> list[Path]:
    """Find all PDF files in target_dir and its subdirectories (#3, #3-d).

    Excludes files within directories that are already image output directories
    (identified by having image_convert.log).

    Args:
        target_dir: Target root directory.

    Returns:
        Sorted list of Path objects for found PDF files.
    """
    if not target_dir.exists():
        raise FileNotFoundError(f"指定されたディレクトリが存在しません: {target_dir}")
    if not target_dir.is_dir():
        raise NotADirectoryError(f"指定されたパスはディレクトリではありません: {target_dir}")

    all_pdfs: list[Path] = []
    for p in target_dir.rglob("*"):
        if p.is_file() and p.suffix.lower() == ".pdf":
            # 出力ディレクトリ内の誤走査を避ける（通常出力先にはPDFは入らないが念のため）
            if not (p.parent / IMAGE_CONVERT_LOG_NAME).is_file():
                all_pdfs.append(p)

    all_pdfs.sort(key=lambda p: str(p))
    return all_pdfs


def write_conversion_logs(
    output_dir: Path,
    pdf_result: PdfConversionResult,
) -> tuple[Path, Path]:
    """Write human-readable and JSON conversion logs to output directory (#3-c).

    Args:
        output_dir: Output directory where images and logs reside.
        pdf_result: Conversion result details.

    Returns:
        Tuple of (log_file_path, json_file_path).
    """
    output_dir.mkdir(parents=True, exist_ok=True)
    log_path = output_dir / IMAGE_CONVERT_LOG_NAME
    json_path = output_dir / IMAGE_CONVERT_JSON_NAME

    # 人間が読めるテキストログの出力
    with open(log_path, "w", encoding="utf-8") as f:
        f.write("==================================================\n")
        f.write("[画像変換作業ログ]\n")
        f.write(f"対象PDF: {pdf_result.pdf_path.name}\n")
        f.write(f"元パス: {pdf_result.pdf_path.resolve()}\n")
        f.write(f"格納先ディレクトリ: {output_dir.resolve()}\n")
        f.write(f"処理開始日時: {pdf_result.started_at}\n")
        f.write(f"処理終了日時: {pdf_result.finished_at}\n")
        f.write(f"総ページ数: {pdf_result.total_pages}\n")
        f.write(f"変換成功ページ数: {pdf_result.converted_pages}\n")
        f.write(f"変換失敗ページ数: {pdf_result.failed_pages}\n")
        f.write(f"変換ステータス: {pdf_result.status}\n")
        if pdf_result.error_message:
            f.write(f"エラー内容: {pdf_result.error_message}\n")
        f.write("--------------------------------------------------\n")
        f.write("ページ別変換記録:\n")
        for record in pdf_result.page_records:
            f.write(
                f"  ページ {record.page_number:04d}: "
                f"ファイル={record.image_filename}, "
                f"サイズ={record.width}x{record.height}, "
                f"DPI={record.dpi}, "
                f"状態={record.status}, "
                f"変換日時={record.converted_at}\n"
            )
            if record.error_message:
                f.write(f"    エラー: {record.error_message}\n")
        f.write("==================================================\n")

    # 機械判読用 JSON ログの出力 (#4, #5 との連携用)
    serializable = {
        "pdf_name": pdf_result.pdf_path.name,
        "pdf_path": str(pdf_result.pdf_path.resolve()),
        "output_dir": str(output_dir.resolve()),
        "total_pages": pdf_result.total_pages,
        "converted_pages": pdf_result.converted_pages,
        "failed_pages": pdf_result.failed_pages,
        "status": pdf_result.status,
        "error_message": pdf_result.error_message,
        "started_at": pdf_result.started_at,
        "finished_at": pdf_result.finished_at,
        "page_records": [asdict(rec) for rec in pdf_result.page_records],
    }
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(serializable, f, ensure_ascii=False, indent=2)

    return log_path, json_path


def convert_single_pdf(
    pdf_path: Path,
    dpi: int = DEFAULT_DPI,
    image_format: str = DEFAULT_FORMAT,
    output_dir: Path | None = None,
) -> PdfConversionResult:
    """Convert a single PDF file into images page by page (#3-a, #3-b, #3-c).

    Args:
        pdf_path: Path to the target PDF file.
        dpi: Image resolution in dots per inch (default: 200).
        image_format: Image format (default: 'PNG').
        output_dir: Destination directory. Defaults to a subdirectory with the same
                    name as the PDF stem located in the PDF's parent directory (#3-a).

    Returns:
        PdfConversionResult containing conversion details and page records.
    """
    if pdfium is None:  # pragma: no cover
        raise RuntimeError("pypdfium2 がインストールされていません。pip install pypdfium2 pillow を実行してください。")

    resolved_pdf = Path(pdf_path).resolve()
    if not resolved_pdf.is_file():
        raise FileNotFoundError(f"PDFファイルが見つかりません: {resolved_pdf}")

    # #3-a 1pdfに1下位ディレクトリを作成する
    if output_dir is None:
        sub_dir_name = resolved_pdf.stem
        dest_dir = resolved_pdf.parent / sub_dir_name
    else:
        dest_dir = Path(output_dir).resolve()

    dest_dir.mkdir(parents=True, exist_ok=True)

    result = PdfConversionResult(
        pdf_path=resolved_pdf,
        output_dir=dest_dir,
    )

    fmt_ext = image_format.lower()
    if fmt_ext == "jpeg":
        fmt_ext = "jpg"

    try:
        doc = pdfium.PdfDocument(resolved_pdf)
        result.total_pages = len(doc)

        scale = dpi / 72.0  # PDF points (1/72 inch) to target DPI scale

        # #3-b 下位ディレクトリ内にpdfの1ページを1画像に変換したファイルを格納
        for page_idx in range(result.total_pages):
            page_num = page_idx + 1
            # 命名: {stem}_page_{page_num:04d}.png (または {stem}_{page_num:04d}.png)
            image_filename = f"{resolved_pdf.stem}_{page_num:04d}.{fmt_ext}"
            image_dest_path = dest_dir / image_filename

            try:
                page = doc[page_idx]
                pil_image = page.render(scale=scale).to_pil()
                pil_image.save(image_dest_path, format=image_format.upper())

                record = PageConversionRecord(
                    page_number=page_num,
                    image_filename=image_filename,
                    image_path=str(image_dest_path),
                    width=pil_image.width,
                    height=pil_image.height,
                    dpi=dpi,
                    status="SUCCESS",
                )
                result.converted_pages += 1
                result.page_records.append(record)
            except Exception as page_err:
                record = PageConversionRecord(
                    page_number=page_num,
                    image_filename=image_filename,
                    image_path=str(image_dest_path),
                    width=0,
                    height=0,
                    dpi=dpi,
                    status="FAILED",
                    error_message=str(page_err),
                )
                result.failed_pages += 1
                result.page_records.append(record)

        if result.failed_pages == 0:
            result.status = "COMPLETED"
        elif result.converted_pages > 0:
            result.status = "PARTIAL"
        else:
            result.status = "FAILED"

    except Exception as doc_err:
        result.status = "FAILED"
        result.error_message = str(doc_err)

    result.finished_at = datetime.datetime.now().astimezone().isoformat()

    # #3-c 下位ディレクトリ内に、変換画像と格納された画像の作業ログを作成し、ログに変換記録追加
    write_conversion_logs(dest_dir, result)

    return result


def convert_pdfs_in_dir(
    target_dir: Path | str,
    dpi: int = DEFAULT_DPI,
    image_format: str = DEFAULT_FORMAT,
) -> BatchConversionResult:
    """Execute PDF image conversion processing for target directory (#3 pdf画像変換PG).

    Args:
        target_dir: Target directory containing PDF files (recursively scanned).
        dpi: Resolution in DPI (default 200).
        image_format: Image format (default 'PNG').

    Returns:
        BatchConversionResult containing operation summary.
    """
    resolved_dir = Path(target_dir).resolve()
    if not resolved_dir.exists():
        raise FileNotFoundError(f"指定されたディレクトリが存在しません: {resolved_dir}")
    if not resolved_dir.is_dir():
        raise NotADirectoryError(f"指定されたパスはディレクトリではありません: {resolved_dir}")

    print("==================================================")
    print("[#3 pdf画像変換PG] 起動条件:")
    print(f"  処理対象ディレクトリ: {resolved_dir}")
    print(f"  解像度 (DPI): {dpi}")
    print(f"  画像フォーマット: {image_format.upper()}")
    print("==================================================")

    # #3-d 再帰的にPDFファイルを探索
    pdf_files = find_pdf_files(resolved_dir)
    batch_result = BatchConversionResult(target_dir=resolved_dir, pdf_count=len(pdf_files))

    if not pdf_files:
        print("  情報: 対象ディレクトリ内に変換対象のPDFファイルが見つかりませんでした。")
    else:
        print(f"  検出されたPDFファイル: {len(pdf_files)}件")

    # #3-d 取得したpdf分だけ繰り返す
    for idx, pdf_path in enumerate(pdf_files, start=1):
        rel_pdf = pdf_path.relative_to(resolved_dir) if pdf_path.is_relative_to(resolved_dir) else pdf_path
        print(f"\n[{idx}/{len(pdf_files)}] PDF変換処理中: {rel_pdf}")

        try:
            pdf_res = convert_single_pdf(
                pdf_path=pdf_path,
                dpi=dpi,
                image_format=image_format,
            )
            batch_result.pdf_results.append(pdf_res)
            batch_result.total_pages_converted += pdf_res.converted_pages

            if pdf_res.status == "COMPLETED":
                batch_result.success_pdf_count += 1
                print(
                    f"  -> 変換完了: 全{pdf_res.total_pages}ページ "
                    f"(出力先: {pdf_res.output_dir.name})"
                )
            else:
                batch_result.failed_pdf_count += 1
                print(
                    f"  -> 一部失敗/失敗: 成功={pdf_res.converted_pages}/{pdf_res.total_pages}ページ, "
                    f"エラー={pdf_res.error_message or 'ページ単位エラー'}",
                    file=sys.stderr,
                )
                batch_result.errors.append((pdf_path, pdf_res.error_message or "Page conversion failure"))

        except Exception as e:
            batch_result.failed_pdf_count += 1
            batch_result.errors.append((pdf_path, str(e)))
            print(f"  -> 処理例外: {e}", file=sys.stderr)

    # #3-z 作業完了メッセージを出して終了する
    print("\n==================================================")
    if batch_result.errors or batch_result.failed_pdf_count > 0:
        print("[#3 pdf画像変換PG] 作業完了（一部失敗あり）:")
    else:
        print("[#3 pdf画像変換PG] 作業完了: PDF画像変換が正常に終了しました。")
    print(f"  対象ディレクトリ: {resolved_dir}")
    print(f"  検出PDFファイル数: {batch_result.pdf_count}件")
    print(f"  変換成功PDF数: {batch_result.success_pdf_count}件")
    if batch_result.failed_pdf_count > 0:
        print(f"  変換失敗PDF数: {batch_result.failed_pdf_count}件")
    print(f"  総変換画像ページ数: {batch_result.total_pages_converted}ページ")
    print("==================================================")

    return batch_result


def main(argv: list[str] | None = None) -> int:
    """CLI entry point for PDF image converter (#3 pdf画像変換PG)."""
    parser = argparse.ArgumentParser(description="#3 pdf画像変換PG")
    parser.add_argument(
        "target_dir",
        type=Path,
        help="変換対象のPDFを含むディレクトリ (下位フォルダも再帰走査)",
    )
    parser.add_argument(
        "--dpi",
        dest="dpi",
        type=int,
        default=DEFAULT_DPI,
        help=f"画像解像度 DPI (デフォルト: {DEFAULT_DPI})",
    )
    parser.add_argument(
        "--format",
        dest="image_format",
        type=str,
        default=DEFAULT_FORMAT,
        choices=["PNG", "png", "JPEG", "jpeg", "JPG", "jpg"],
        help=f"出力画像フォーマット (デフォルト: {DEFAULT_FORMAT})",
    )

    args = parser.parse_args(argv)

    try:
        result = convert_pdfs_in_dir(
            target_dir=args.target_dir,
            dpi=args.dpi,
            image_format=args.image_format,
        )
        return 1 if result.errors or result.failed_pdf_count > 0 else 0
    except (FileNotFoundError, NotADirectoryError, ValueError) as e:
        print(f"エラー: {e}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("\n処理がユーザーにより中断されました。", file=sys.stderr)
        return 130


if __name__ == "__main__":
    sys.exit(main())
