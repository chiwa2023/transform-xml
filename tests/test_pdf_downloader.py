"""Unit tests for pdf_downloader module (#2 pdf取得PG)."""

import csv
import io
import shutil
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest.mock import MagicMock, call, patch

# src ディレクトリを sys.path に追加
_SRC_DIR = Path(__file__).resolve().parent.parent / "src"
if str(_SRC_DIR) not in sys.path:
    sys.path.insert(0, str(_SRC_DIR))

from transform_xml.pdf_downloader import (
    DEFAULT_SLEEP_SEC,
    DEFAULT_TIMEOUT,
    PDF_LINKS_FILE_NAME,
    DownloadResult,
    download_file,
    download_pdfs_in_dir,
    find_pdf_link_files,
    load_pdf_links,
    main,
    sanitize_pdf_filename,
)

FIXTURES_DIR = Path(__file__).resolve().parent / "fixtures" / "24"


class TestPdfDownloader(unittest.TestCase):
    """Test suite for pdf_downloader."""

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.temp_path = Path(self.temp_dir)

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_sanitize_pdf_filename(self):
        """Test sanitizing filename from label string."""
        # Forbidden characters replaced with =X
        raw = 'A/B:C*D?E"F<G>H|I\\J'
        expected = "A=XB=XC=XD=XE=XF=XG=XH=XI=XJ.pdf"
        self.assertEqual(sanitize_pdf_filename(raw), expected)

        # Control characters replaced with =X
        self.assertEqual(sanitize_pdf_filename("Title\x00Name\x1f"), "Title=XName=X.pdf")

        # Empty / whitespace fallback
        self.assertEqual(sanitize_pdf_filename(""), "unnamed.pdf")
        self.assertEqual(sanitize_pdf_filename("   "), "unnamed.pdf")

        # Already has .pdf or .PDF extension
        self.assertEqual(sanitize_pdf_filename("report.pdf"), "report.pdf")
        self.assertEqual(sanitize_pdf_filename("report.PDF"), "report.PDF")

        # Normal Japanese label without extension
        self.assertEqual(sanitize_pdf_filename("八島立門後援会"), "八島立門後援会.pdf")
        self.assertEqual(sanitize_pdf_filename("藪野裕道後援会"), "藪野裕道後援会.pdf")

    def test_find_pdf_link_files(self):
        """Test finding all pdf_links.csv recursively (#2-a, #2-d)."""
        # Create nested test folder structure
        sub1 = self.temp_path / "sub1"
        sub2 = self.temp_path / "sub1" / "sub2"
        sub3 = self.temp_path / "sub3"
        sub1.mkdir(parents=True)
        sub2.mkdir(parents=True)
        sub3.mkdir(parents=True)

        (sub1 / "pdf_links.csv").write_text("url,label\n", encoding="utf-8")
        (sub2 / "pdf_links.csv").write_text("url,label\n", encoding="utf-8")
        (sub3 / "other.txt").write_text("hello", encoding="utf-8")

        found = find_pdf_link_files(self.temp_path)
        self.assertEqual(len(found), 2)
        self.assertEqual(found[0], sub1 / "pdf_links.csv")
        self.assertEqual(found[1], sub2 / "pdf_links.csv")

    def test_find_pdf_link_files_non_existent(self):
        """Test find_pdf_link_files raises FileNotFoundError if path doesn't exist."""
        non_existent = self.temp_path / "does_not_exist"
        with self.assertRaises(FileNotFoundError):
            find_pdf_link_files(non_existent)

    def test_find_pdf_link_files_not_a_directory(self):
        """Test find_pdf_link_files raises NotADirectoryError if path is a file."""
        file_path = self.temp_path / "test.txt"
        file_path.write_text("hello", encoding="utf-8")
        with self.assertRaises(NotADirectoryError):
            find_pdf_link_files(file_path)

    def test_load_pdf_links(self):
        """Test loading links from CSV file."""
        csv_file = self.temp_path / "pdf_links.csv"
        csv_file.write_text(
            "url,label\n"
            "https://example.com/a.pdf,文書A\n"
            "https://example.com/b.pdf,文書B\n"
            "\n"
            "invalid_line\n",
            encoding="utf-8",
        )
        links = load_pdf_links(csv_file)
        self.assertEqual(
            links,
            [
                ("https://example.com/a.pdf", "文書A"),
                ("https://example.com/b.pdf", "文書B"),
            ],
        )

    def test_load_pdf_links_non_existent(self):
        """Test loading links from non-existent file returns empty list."""
        links = load_pdf_links(self.temp_path / "missing.csv")
        self.assertEqual(links, [])

    @patch("urllib.request.urlopen")
    def test_download_file(self, mock_urlopen):
        """Test downloading binary file and saving to disk."""
        mock_resp = MagicMock()
        mock_resp.read.side_effect = [b"%PDF-1.4 sample content", b""]
        mock_urlopen.return_value.__enter__.return_value = mock_resp

        dest = self.temp_path / "sub" / "output.pdf"
        download_file("https://example.com/test.pdf", dest)

        self.assertTrue(dest.is_file())
        self.assertEqual(dest.read_bytes(), b"%PDF-1.4 sample content")

    @patch("time.sleep")
    @patch("transform_xml.pdf_downloader.download_file")
    def test_download_pdfs_in_fixtures(self, mock_download_file, mock_sleep):
        """Test end-to-end PDF downloading using the standard test fixtures (tests/fixtures/24).

        Analyzes 2 CSV files and downloads 2 PDF files as requested.
        """
        # Ensure fixtures exist in tests/fixtures/24
        self.assertTrue(FIXTURES_DIR.is_dir(), f"Fixtures dir not found: {FIXTURES_DIR}")

        # Copy fixtures to temporary directory to avoid mutating workspace
        work_dir = self.temp_path / "24"
        shutil.copytree(FIXTURES_DIR, work_dir)

        # Execute download processing with sleep_sec=1.0 (#2-b)
        captured_out = io.StringIO()
        with redirect_stdout(captured_out):
            result = download_pdfs_in_dir(work_dir, sleep_sec=1.0)

        # Verify 2 CSVs were processed and 2 PDFs were downloaded
        self.assertEqual(result.csv_count, 2, "2 CSV files must be analyzed")
        self.assertEqual(result.downloaded_count, 2, "2 PDF files must be downloaded")
        self.assertEqual(len(result.errors), 0)

        # Verify download_file was called twice with correct URLs and destination paths
        expected_calls = [
            (
                "https://www.pref.mie.lg.jp/common/content/001267098.pdf",
                work_dir / "（令和７年分）" / "八島立門後援会.pdf",
            ),
            (
                "https://www.pref.mie.lg.jp/common/content/001259974.pdf",
                work_dir / "（令和７年分）" / "（令和７年分）_2" / "藪野裕道後援会.pdf",
            ),
        ]
        self.assertEqual(mock_download_file.call_count, 2)
        for expected_url, expected_path in expected_calls:
            mock_download_file.assert_any_call(
                expected_url,
                expected_path,
                timeout=DEFAULT_TIMEOUT,
                user_agent=unittest.mock.ANY,
            )

        # Verify sleep(1.0) was invoked after each download (#2-b)
        self.assertEqual(mock_sleep.call_count, 2)
        mock_sleep.assert_has_calls([call(1.0), call(1.0)])

        # Verify completion message (#2-z)
        stdout_content = captured_out.getvalue()
        self.assertIn("作業完了: PDF取得が正常に終了しました", stdout_content)
        self.assertIn("検出CSVファイル数: 2件", stdout_content)
        self.assertIn("ダウンロードPDF数: 2件", stdout_content)

    @patch("time.sleep")
    @patch("transform_xml.pdf_downloader.download_file")
    def test_download_pdfs_error_handling(self, mock_download_file, mock_sleep):
        """Test error handling when download fails for some files."""
        csv_file = self.temp_path / "pdf_links.csv"
        csv_file.write_text(
            "url,label\n"
            "https://example.com/err.pdf,エラー文書\n",
            encoding="utf-8",
        )
        mock_download_file.side_effect = Exception("Connection refused")

        captured_out = io.StringIO()
        captured_err = io.StringIO()
        with redirect_stdout(captured_out), redirect_stderr(captured_err):
            result = download_pdfs_in_dir(self.temp_path, sleep_sec=0)

        self.assertEqual(result.downloaded_count, 0)
        self.assertEqual(len(result.errors), 1)
        self.assertIn("作業完了（一部失敗あり）", captured_out.getvalue())
        self.assertIn("ダウンロード失敗", captured_err.getvalue())

    @patch("transform_xml.pdf_downloader.download_pdfs_in_dir")
    def test_main_cli(self, mock_download_pdfs):
        """Test CLI main() entry point."""
        mock_result = DownloadResult(target_dir=self.temp_path, csv_count=1, downloaded_count=1)
        mock_download_pdfs.return_value = mock_result

        exit_code = main([str(self.temp_path), "--sleep", "0.5", "--timeout", "10.0"])
        self.assertEqual(exit_code, 0)
        mock_download_pdfs.assert_called_once_with(
            target_dir=self.temp_path,
            sleep_sec=0.5,
            timeout=10.0,
        )

    def test_main_cli_non_existent_dir(self):
        """Test CLI main() exits with 1 on non-existent directory."""
        captured_err = io.StringIO()
        with redirect_stderr(captured_err):
            exit_code = main([str(self.temp_path / "non_existent")])
        self.assertEqual(exit_code, 1)
        self.assertIn("エラー:", captured_err.getvalue())


if __name__ == "__main__":
    unittest.main()
