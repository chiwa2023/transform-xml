"""Unit tests for pdf_image_converter module (#3 pdf画像変換PG)."""

import io
import json
import shutil
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest.mock import MagicMock, patch

from PIL import Image

# src ディレクトリを sys.path に追加
_SRC_DIR = Path(__file__).resolve().parent.parent / "src"
if str(_SRC_DIR) not in sys.path:
    sys.path.insert(0, str(_SRC_DIR))

from transform_xml.pdf_image_converter import (
    DEFAULT_DPI,
    DEFAULT_FORMAT,
    IMAGE_CONVERT_JSON_NAME,
    IMAGE_CONVERT_LOG_NAME,
    BatchConversionResult,
    PageConversionRecord,
    PdfConversionResult,
    convert_pdfs_in_dir,
    convert_single_pdf,
    find_pdf_files,
    main,
    write_conversion_logs,
)

FIXTURES_DIR = Path(__file__).resolve().parent / "fixtures" / "25"


class TestPdfImageConverter(unittest.TestCase):
    """Test suite for pdf_image_converter."""

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.temp_path = Path(self.temp_dir)

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_find_pdf_files(self):
        """Test recursive discovery of PDF files (#3-d)."""
        # Create dummy PDF files in nested directories
        sub1 = self.temp_path / "sub1"
        sub2 = self.temp_path / "sub1" / "sub2"
        sub1.mkdir(parents=True)
        sub2.mkdir(parents=True)

        pdf1 = sub1 / "sample1.pdf"
        pdf2 = sub2 / "sample2.PDF"
        txt_file = sub1 / "other.txt"
        pdf1.write_bytes(b"%PDF-1.4 dummy")
        pdf2.write_bytes(b"%PDF-1.4 dummy")
        txt_file.write_text("dummy", encoding="utf-8")

        found = find_pdf_files(self.temp_path)
        self.assertEqual(len(found), 2)
        self.assertEqual(found[0], pdf1)
        self.assertEqual(found[1], pdf2)

    def test_find_pdf_files_non_existent(self):
        """Test find_pdf_files raises FileNotFoundError if directory does not exist."""
        with self.assertRaises(FileNotFoundError):
            find_pdf_files(self.temp_path / "does_not_exist")

    def test_find_pdf_files_not_a_directory(self):
        """Test find_pdf_files raises NotADirectoryError if path is a file."""
        dummy_file = self.temp_path / "test.txt"
        dummy_file.write_text("hello", encoding="utf-8")
        with self.assertRaises(NotADirectoryError):
            find_pdf_files(dummy_file)

    def test_write_conversion_logs(self):
        """Test writing conversion log and json (#3-c)."""
        out_dir = self.temp_path / "sample_out"
        rec1 = PageConversionRecord(
            page_number=1,
            image_filename="sample_0001.png",
            image_path=str(out_dir / "sample_0001.png"),
            width=1000,
            height=1400,
            dpi=200,
            status="SUCCESS",
        )
        rec2 = PageConversionRecord(
            page_number=2,
            image_filename="sample_0002.png",
            image_path=str(out_dir / "sample_0002.png"),
            width=0,
            height=0,
            dpi=200,
            status="FAILED",
            error_message="Render error",
        )
        result = PdfConversionResult(
            pdf_path=self.temp_path / "sample.pdf",
            output_dir=out_dir,
            total_pages=2,
            converted_pages=1,
            failed_pages=1,
            status="PARTIAL",
            page_records=[rec1, rec2],
        )

        log_path, json_path = write_conversion_logs(out_dir, result)
        self.assertTrue(log_path.is_file())
        self.assertTrue(json_path.is_file())

        log_content = log_path.read_text(encoding="utf-8")
        self.assertIn("[画像変換作業ログ]", log_content)
        self.assertIn("対象PDF: sample.pdf", log_content)
        self.assertIn("総ページ数: 2", log_content)
        self.assertIn("変換成功ページ数: 1", log_content)
        self.assertIn("変換失敗ページ数: 1", log_content)
        self.assertIn("sample_0001.png", log_content)
        self.assertIn("Render error", log_content)

        with open(json_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        self.assertEqual(data["pdf_name"], "sample.pdf")
        self.assertEqual(data["total_pages"], 2)
        self.assertEqual(data["converted_pages"], 1)
        self.assertEqual(data["status"], "PARTIAL")
        self.assertEqual(len(data["page_records"]), 2)

    def test_convert_single_pdf_with_fixture(self):
        """Test converting a single PDF using sample fixture from tests/fixtures/25."""
        self.assertTrue(FIXTURES_DIR.is_dir(), f"Fixtures dir not found: {FIXTURES_DIR}")
        pdf_fixture = FIXTURES_DIR / "（令和７年分）" / "八島立門後援会.pdf"
        self.assertTrue(pdf_fixture.is_file(), f"Fixture PDF not found: {pdf_fixture}")

        # 一時ディレクトリにPDFをコピーして実行
        work_pdf = self.temp_path / "八島立門後援会.pdf"
        shutil.copyfile(pdf_fixture, work_pdf)

        res = convert_single_pdf(work_pdf, dpi=150, image_format="PNG")

        # #3-a 1pdfに1下位ディレクトリを作成する
        expected_out_dir = self.temp_path / "八島立門後援会"
        self.assertEqual(res.output_dir, expected_out_dir)
        self.assertTrue(expected_out_dir.is_dir())

        # 八島立門後援会.pdf は全5ページ
        self.assertEqual(res.total_pages, 5)
        self.assertEqual(res.converted_pages, 5)
        self.assertEqual(res.failed_pages, 0)
        self.assertEqual(res.status, "COMPLETED")

        # #3-b 下位ディレクトリ内にpdfの1ページを1画像に変換したファイルを格納
        for page_num in range(1, 6):
            img_file = expected_out_dir / f"八島立門後援会_{page_num:04d}.png"
            self.assertTrue(img_file.is_file(), f"Image missing: {img_file}")
            # Pillowで実際に画像として開けるか検証
            with Image.open(img_file) as img:
                self.assertEqual(img.format, "PNG")
                self.assertGreater(img.width, 0)
                self.assertGreater(img.height, 0)

        # #3-c 下位ディレクトリ内に変換記録ログが存在すること
        log_file = expected_out_dir / IMAGE_CONVERT_LOG_NAME
        json_file = expected_out_dir / IMAGE_CONVERT_JSON_NAME
        self.assertTrue(log_file.is_file())
        self.assertTrue(json_file.is_file())

        with open(json_file, "r", encoding="utf-8") as f:
            jdata = json.load(f)
        self.assertEqual(jdata["total_pages"], 5)
        self.assertEqual(jdata["converted_pages"], 5)
        self.assertEqual(jdata["status"], "COMPLETED")

    def test_convert_pdfs_in_fixtures_dir(self):
        """Test end-to-end PDF image conversion on tests/fixtures/25 fixtures (#3-y).

        Verifies recursive traversal, creation of subdirectories for each PDF,
        generation of images per page, and creation of logs.
        """
        self.assertTrue(FIXTURES_DIR.is_dir(), f"Fixtures dir not found: {FIXTURES_DIR}")

        # fixtures/25 を一時ディレクトリにコピー
        work_dir = self.temp_path / "25"
        shutil.copytree(FIXTURES_DIR, work_dir)

        captured_out = io.StringIO()
        with redirect_stdout(captured_out):
            batch_res = convert_pdfs_in_dir(work_dir, dpi=100, image_format="PNG")

        # fixtures/25 には2つのPDF（八島立門後援会.pdf: 5ページ, 藪野裕道後援会.pdf: 7ページ）
        self.assertEqual(batch_res.pdf_count, 2)
        self.assertEqual(batch_res.success_pdf_count, 2)
        self.assertEqual(batch_res.failed_pdf_count, 0)
        self.assertEqual(batch_res.total_pages_converted, 12)
        self.assertEqual(len(batch_res.errors), 0)

        # 1つ目のPDF: tests/fixtures/25/（令和７年分）/八島立門後援会.pdf -> 下位ディレクトリ 八島立門後援会
        sub_dir1 = work_dir / "（令和７年分）" / "八島立門後援会"
        self.assertTrue(sub_dir1.is_dir())
        self.assertTrue((sub_dir1 / IMAGE_CONVERT_LOG_NAME).is_file())
        self.assertTrue((sub_dir1 / IMAGE_CONVERT_JSON_NAME).is_file())
        for page_num in range(1, 6):
            self.assertTrue((sub_dir1 / f"八島立門後援会_{page_num:04d}.png").is_file())

        # 2つ目のPDF: tests/fixtures/25/（令和７年分）/（令和７年分）_2/藪野裕道後援会.pdf -> 下位ディレクトリ 藪野裕道後援会
        sub_dir2 = work_dir / "（令和７年分）" / "（令和７年分）_2" / "藪野裕道後援会"
        self.assertTrue(sub_dir2.is_dir())
        self.assertTrue((sub_dir2 / IMAGE_CONVERT_LOG_NAME).is_file())
        self.assertTrue((sub_dir2 / IMAGE_CONVERT_JSON_NAME).is_file())
        for page_num in range(1, 8):
            self.assertTrue((sub_dir2 / f"藪野裕道後援会_{page_num:04d}.png").is_file())

        # #3-z 作業完了メッセージの確認
        stdout_content = captured_out.getvalue()
        self.assertIn("作業完了: PDF画像変換が正常に終了しました", stdout_content)
        self.assertIn("検出PDFファイル数: 2件", stdout_content)
        self.assertIn("変換成功PDF数: 2件", stdout_content)
        self.assertIn("総変換画像ページ数: 12ページ", stdout_content)

    def test_convert_pdfs_in_empty_dir(self):
        """Test conversion when directory has no PDF files."""
        empty_dir = self.temp_path / "empty"
        empty_dir.mkdir()

        captured_out = io.StringIO()
        with redirect_stdout(captured_out):
            batch_res = convert_pdfs_in_dir(empty_dir)

        self.assertEqual(batch_res.pdf_count, 0)
        self.assertEqual(batch_res.total_pages_converted, 0)
        self.assertIn("変換対象のPDFファイルが見つかりませんでした", captured_out.getvalue())

    def test_convert_invalid_pdf(self):
        """Test error handling when a corrupted PDF file is encountered."""
        invalid_pdf = self.temp_path / "corrupted.pdf"
        invalid_pdf.write_bytes(b"not a valid pdf header")

        res = convert_single_pdf(invalid_pdf)
        self.assertEqual(res.status, "FAILED")
        self.assertIsNotNone(res.error_message)
        self.assertTrue((res.output_dir / IMAGE_CONVERT_LOG_NAME).is_file())

    def test_main_cli_success(self):
        """Test main CLI entry point on valid directory."""
        # Create a mock batch result
        with patch("transform_xml.pdf_image_converter.convert_pdfs_in_dir") as mock_convert:
            mock_convert.return_value = BatchConversionResult(
                target_dir=self.temp_path,
                pdf_count=1,
                success_pdf_count=1,
                failed_pdf_count=0,
                total_pages_converted=5,
            )
            exit_code = main([str(self.temp_path), "--dpi", "300", "--format", "JPEG"])
            self.assertEqual(exit_code, 0)
            mock_convert.assert_called_once_with(
                target_dir=self.temp_path,
                dpi=300,
                image_format="JPEG",
            )

    def test_main_cli_non_existent_dir(self):
        """Test main CLI returns 1 on non-existent directory."""
        captured_err = io.StringIO()
        with redirect_stderr(captured_err):
            exit_code = main([str(self.temp_path / "missing_dir")])
        self.assertEqual(exit_code, 1)
        self.assertIn("エラー:", captured_err.getvalue())


if __name__ == "__main__":
    unittest.main()
