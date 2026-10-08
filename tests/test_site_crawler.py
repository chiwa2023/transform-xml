"""Unit tests for site_crawler module."""

import csv
import io
import json
import shutil
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest.mock import MagicMock, patch

from transform_xml.site_crawler import (
    CrawlerContext,
    ExtractedLink,
    _crawl_recursive,
    _get_unique_dir_for_link,
    extract_links_from_section,
    extract_section_html,
    get_pref_target,
    load_crawler_config,
    load_env_file,
    main,
    resolve_output_dir,
    run_crawler,
    sanitize_dir_name,
    save_pdf_links_file,
    validate_pref_code,
)


class TestSiteCrawler(unittest.TestCase):
    """Test suite for site_crawler."""

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.temp_path = Path(self.temp_dir)

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_validate_pref_code(self):
        """Test validation of prefecture code."""
        self.assertEqual(validate_pref_code("00"), "00")
        self.assertEqual(validate_pref_code("01"), "01")
        self.assertEqual(validate_pref_code("24"), "24")
        self.assertEqual(validate_pref_code("47"), "47")
        self.assertEqual(validate_pref_code("0"), "00")
        self.assertEqual(validate_pref_code("7"), "07")

        invalid_codes = ["48", "99", "-1", "abc", "", "100"]
        for code in invalid_codes:
            with self.subTest(code=code):
                with self.assertRaises(ValueError):
                    validate_pref_code(code)

    def test_sanitize_dir_name(self):
        """Test sanitization of directory name with =X substitution."""
        # ユーザー要件2: ディレクトリ利用不可文字が存在する場合は=Xで代用
        raw = 'A/B:C*D?E"F<G>H|I\\J'
        expected = "A=XB=XC=XD=XE=XF=XG=XH=XI=XJ"
        self.assertEqual(sanitize_dir_name(raw), expected)

        # Control characters
        self.assertEqual(sanitize_dir_name("Test\x00Name\x1f"), "Test=XName=X")

        # Empty / whitespace fallback
        self.assertEqual(sanitize_dir_name("   "), "unnamed")
        self.assertEqual(sanitize_dir_name(""), "unnamed")

        # Normal text remains unchanged
        self.assertEqual(sanitize_dir_name("令和6年分"), "令和6年分")

    def test_load_env_file_and_resolve_output_dir(self):
        """Test env file loading and output directory resolution."""
        env_file = self.temp_path / "test.env"
        env_file.write_text(
            "# Comment line\n"
            "OUTPUT_DIR=/custom/output/dir\n"
            "OTHER_VAR=value\n",
            encoding="utf-8",
        )
        vars_dict = load_env_file(env_file)
        self.assertEqual(vars_dict["OUTPUT_DIR"], "/custom/output/dir")

        resolved = resolve_output_dir(env_file)
        self.assertEqual(resolved, Path("/custom/output/dir"))

    def test_load_crawler_config_and_get_pref_target(self):
        """Test JSON config parsing and target lookup."""
        config_file = self.temp_path / "config.json"
        config_data = {
            "24": {
                "name": "三重県",
                "root_url": "https://example.com/root",
                "start_key": "START",
                "end_key": "END",
            }
        }
        config_file.write_text(json.dumps(config_data, ensure_ascii=False), encoding="utf-8")

        config = load_crawler_config(config_file)
        target = get_pref_target("24", config)
        self.assertEqual(target["name"], "三重県")
        self.assertEqual(target["start_key"], "START")

        with self.assertRaises(KeyError):
            get_pref_target("01", config)

    def test_extract_section_html(self):
        """Test HTML snippet extraction between start_key and end_key."""
        html = (
            "<html><head><title>START title</title></head>"
            "<body><div id='container'>"
            "<h1>START</h1>"
            "<a href='test.pdf'>PDF Link</a>"
            "<div>END</div>"
            "</div></body></html>"
        )
        snippet = extract_section_html(html, "START", "END")
        self.assertIn("PDF Link", snippet)
        # Verify it skipped the <title>START in <head>
        self.assertNotIn("<title>", snippet)

    def test_extract_section_html_missing_key(self):
        """Test HTML extraction when keys are not found."""
        html = "<html><body>Hello World</body></html>"
        self.assertEqual(extract_section_html(html, "START", "END"), "")

    def test_extract_links_from_section(self):
        """Test link extraction, PDF separation, and domain filtering."""
        base_url = "https://www.pref.example.jp/page1.htm"
        root_host = "www.pref.example.jp"
        snippet = (
            "<div>"
            "<a href='report1.pdf'>報告書1</a>"
            "<a href='/sub/page2.htm'>サブページ</a>"
            "<a href='https://other-domain.com/link'>外部サイト</a>"
            "<a href='#anchor'>ジャンプ</a>"
            "<a href='mailto:test@example.jp'>メール</a>"
            "</div>"
        )
        pdf_links, page_links = extract_links_from_section(base_url, snippet, root_host)

        # PDF link check
        self.assertEqual(len(pdf_links), 1)
        self.assertEqual(pdf_links[0].url, "https://www.pref.example.jp/report1.pdf")
        self.assertEqual(pdf_links[0].label, "報告書1")
        self.assertTrue(pdf_links[0].is_pdf)

        # Page link check
        self.assertEqual(len(page_links), 1)
        self.assertEqual(page_links[0].url, "https://www.pref.example.jp/sub/page2.htm")
        self.assertEqual(page_links[0].label, "サブページ")
        self.assertFalse(page_links[0].is_pdf)

    def test_save_pdf_links_file(self):
        """Test saving and appending to pdf_links.csv."""
        target_dir = self.temp_path / "sub_dir"
        pdf_links = [
            ExtractedLink(url="https://example.jp/doc1.pdf", label="文書1", is_pdf=True),
            ExtractedLink(url="https://example.jp/doc2.pdf", label="文書2", is_pdf=True),
        ]
        csv_file = save_pdf_links_file(target_dir, pdf_links)
        self.assertTrue(csv_file.is_file())

        with open(csv_file, "r", encoding="utf-8") as f:
            reader = list(csv.reader(f))
        self.assertEqual(reader[0], ["url", "label"])
        self.assertEqual(reader[1], ["https://example.jp/doc1.pdf", "文書1"])
        self.assertEqual(reader[2], ["https://example.jp/doc2.pdf", "文書2"])

    def test_get_unique_dir_for_link(self):
        """Test directory creation and collision disambiguation."""
        parent = self.temp_path / "base"
        parent.mkdir()
        url_map = {}

        dir1 = _get_unique_dir_for_link(parent, "ラベル", "https://example.jp/p1", url_map)
        self.assertEqual(dir1.name, "ラベル")

        # Same URL returns same dir
        dir1_again = _get_unique_dir_for_link(parent, "ラベル", "https://example.jp/p1", url_map)
        self.assertEqual(dir1, dir1_again)

        # Different URL with same label gets suffix
        dir2 = _get_unique_dir_for_link(parent, "ラベル", "https://example.jp/p2", url_map)
        self.assertEqual(dir2.name, "ラベル_2")

    @patch("transform_xml.site_crawler.fetch_html")
    def test_run_crawler_success(self, mock_fetch):
        """Test end-to-end crawling flow with mock HTTP."""
        config_file = self.temp_path / "config.json"
        config_data = {
            "24": {
                "name": "三重県",
                "root_url": "https://pref.example.jp/root.htm",
                "start_key": "START",
                "end_key": "END",
            }
        }
        config_file.write_text(json.dumps(config_data, ensure_ascii=False), encoding="utf-8")

        # Root page has link to subpage: /sub.htm
        root_html = (
            "<html><body><div id='container'>"
            "START"
            "<a href='/sub.htm'>年度別一覧</a>"
            "END"
            "</div></body></html>"
        )
        # Subpage has link to pdf: /report.pdf
        sub_html = (
            "<html><body><div id='container'>"
            "START"
            "<a href='/report.pdf'>令和6年収支報告書</a>"
            "END"
            "</div></body></html>"
        )

        def side_effect(url, **kwargs):
            if "root.htm" in url:
                return root_html
            elif "sub.htm" in url:
                return sub_html
            raise ValueError(f"Unknown url: {url}")

        mock_fetch.side_effect = side_effect

        output_dir = self.temp_path / "output"

        captured = io.StringIO()
        with redirect_stdout(captured):
            exit_code = run_crawler(
                pref_code="24",
                output_dir=output_dir,
                config_path=config_file,
                sleep_sec=0,
            )

        self.assertEqual(exit_code, 0)
        self.assertIn("作業完了: サイト巡回が正常に終了しました", captured.getvalue())

        # Check directory structure
        pref_dir = output_dir / "24"
        sub_dir = pref_dir / "年度別一覧"
        self.assertTrue(sub_dir.is_dir())

        # Check pdf_links.csv in sub_dir
        csv_path = sub_dir / "pdf_links.csv"
        self.assertTrue(csv_path.is_file())
        content = csv_path.read_text(encoding="utf-8")
        self.assertIn("https://pref.example.jp/report.pdf,令和6年収支報告書", content)

    @patch("transform_xml.site_crawler.fetch_html")
    def test_run_crawler_max_depth_abort(self, mock_fetch):
        """Test that crawler stops and warns when depth exceeds limit (#1-f)."""
        config_file = self.temp_path / "config.json"
        config_data = {
            "24": {
                "name": "三重県",
                "root_url": "https://pref.example.jp/d1.htm",
                "start_key": "START",
                "end_key": "END",
            }
        }
        config_file.write_text(json.dumps(config_data, ensure_ascii=False), encoding="utf-8")

        # Each page links to next depth page
        def side_effect(url, **kwargs):
            idx = int(url.split("d")[-1].split(".")[0])
            next_url = f"/d{idx + 1}.htm"
            return (
                "<html><body><div id='container'>"
                f"START <a href='{next_url}'>階層{idx + 1}</a> END"
                "</div></body></html>"
            )

        mock_fetch.side_effect = side_effect
        output_dir = self.temp_path / "output"

        captured_err = io.StringIO()
        captured_out = io.StringIO()
        with redirect_stderr(captured_err), redirect_stdout(captured_out):
            exit_code = run_crawler(
                pref_code="24",
                output_dir=output_dir,
                config_path=config_file,
                max_depth=3,  # Set depth limit to 3 to trigger abort
                sleep_sec=0,
            )

        self.assertEqual(exit_code, 1)
        self.assertIn("巡回階層が上限（3）を超えました", captured_err.getvalue())
        self.assertIn("【警告中断】", captured_out.getvalue())


if __name__ == "__main__":
    unittest.main()
