"""Unit tests for fetch pipeline, analyze pipeline, and full pipeline."""

import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from transform_xml.analyze_pipeline import (
    main as analyze_main,
    resolve_target_directory,
    run_analyze_pipeline,
)
from transform_xml.fetch_pipeline import (
    main as fetch_main,
    run_fetch_pipeline,
)
from transform_xml.main import run_full_pipeline
from transform_xml.pdf_downloader import DownloadResult
from transform_xml.pdf_image_converter import BatchConversionResult
from transform_xml.image_xml_converter import BatchXmlConversionResult
from transform_xml.xml_integrator import BatchIntegrationResult


class TestFetchPipeline(unittest.TestCase):
    """Test suite for continuous fetch pipeline (#1 -> #2 -> #3)."""

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.temp_path = Path(self.temp_dir.name)

    def tearDown(self):
        self.temp_dir.cleanup()

    @patch("transform_xml.fetch_pipeline.convert_pdfs_in_dir")
    @patch("transform_xml.fetch_pipeline.download_pdfs_in_dir")
    @patch("transform_xml.fetch_pipeline.run_crawler")
    def test_run_fetch_pipeline_success(
        self, mock_crawler, mock_download, mock_convert
    ):
        mock_crawler.return_value = 0
        mock_download.return_value = DownloadResult(target_dir=self.temp_path / "24")
        mock_convert.return_value = BatchConversionResult(target_dir=self.temp_path / "24")

        ret = run_fetch_pipeline(
            pref_code="24",
            output_dir=self.temp_path,
            sleep_sec=0.5,
            timeout=10.0,
            dpi=300,
            image_format="PNG",
        )
        self.assertEqual(ret, 0)

        # 1. run_crawler called
        mock_crawler.assert_called_once_with(
            pref_code="24",
            output_dir=self.temp_path,
            config_path=None,
            env_file_path=None,
            max_depth=7,
            sleep_sec=0.5,
        )
        # 2. download_pdfs_in_dir called on pref_dir
        mock_download.assert_called_once_with(
            target_dir=self.temp_path / "24",
            sleep_sec=0.5,
            timeout=10.0,
        )
        # 3. convert_pdfs_in_dir called on pref_dir
        mock_convert.assert_called_once_with(
            target_dir=self.temp_path / "24",
            dpi=300,
            image_format="PNG",
        )

    @patch("transform_xml.fetch_pipeline.convert_pdfs_in_dir")
    @patch("transform_xml.fetch_pipeline.download_pdfs_in_dir")
    @patch("transform_xml.fetch_pipeline.run_crawler")
    def test_run_fetch_pipeline_crawler_fails(
        self, mock_crawler, mock_download, mock_convert
    ):
        mock_crawler.return_value = 1

        ret = run_fetch_pipeline(
            pref_code="24",
            output_dir=self.temp_path,
        )
        self.assertEqual(ret, 1)
        mock_crawler.assert_called_once()
        mock_download.assert_not_called()
        mock_convert.assert_not_called()

    @patch("transform_xml.fetch_pipeline.run_fetch_pipeline")
    def test_fetch_pipeline_cli(self, mock_pipeline):
        mock_pipeline.return_value = 0
        ret = fetch_main(["24", "--sleep", "2.0"])
        self.assertEqual(ret, 0)
        self.assertEqual(mock_pipeline.call_args[1]["pref_code"], "24")
        self.assertEqual(mock_pipeline.call_args[1]["sleep_sec"], 2.0)


class TestAnalyzePipeline(unittest.TestCase):
    """Test suite for continuous analyze pipeline (#4 -> #5)."""

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.temp_path = Path(self.temp_dir.name)
        # Create dummy target directory
        self.target_dir = self.temp_path / "test_target"
        self.target_dir.mkdir(parents=True)

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_resolve_target_directory(self):
        # Path directly
        self.assertEqual(
            resolve_target_directory(self.target_dir),
            self.target_dir.resolve(),
        )

    @patch("transform_xml.analyze_pipeline.integrate_xml_in_target_dir")
    @patch("transform_xml.analyze_pipeline.convert_xmls_in_target_dir")
    def test_run_analyze_pipeline_success(self, mock_convert, mock_integrate):
        mock_convert.return_value = BatchXmlConversionResult(target_dir=self.target_dir)
        mock_integrate.return_value = BatchIntegrationResult(target_dir=self.target_dir)

        ret = run_analyze_pipeline(
            target_dir=self.target_dir,
            engine_name="local",
        )
        self.assertEqual(ret, 0)

        mock_convert.assert_called_once_with(
            target_dir=self.target_dir.resolve(),
            ocr_engine=None,
            engine_name="local",
            env_file_path=None,
            api_key=None,
            model=None,
        )
        mock_integrate.assert_called_once_with(
            target_dir=self.target_dir.resolve(),
            template_dir=None,
            env_file_path=None,
        )

    @patch("transform_xml.analyze_pipeline.run_analyze_pipeline")
    def test_analyze_pipeline_cli(self, mock_pipeline):
        mock_pipeline.return_value = 0
        ret = analyze_main([str(self.target_dir), "--ocr-engine", "local"])
        self.assertEqual(ret, 0)
        self.assertEqual(mock_pipeline.call_args[1]["target_dir"], str(self.target_dir))
        self.assertEqual(mock_pipeline.call_args[1]["engine_name"], "local")


class TestFullPipeline(unittest.TestCase):
    """Test suite for end-to-end full pipeline execution (#1 -> #5)."""

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.temp_path = Path(self.temp_dir.name)

    def tearDown(self):
        self.temp_dir.cleanup()

    @patch("transform_xml.main.run_analyze_pipeline")
    @patch("transform_xml.main.run_fetch_pipeline")
    def test_run_full_pipeline_success(self, mock_fetch, mock_analyze):
        mock_fetch.return_value = 0
        mock_analyze.return_value = 0

        ret = run_full_pipeline([
            "24",
            "--output-dir", str(self.temp_path),
            "--ocr-engine", "local",
        ])
        self.assertEqual(ret, 0)

        mock_fetch.assert_called_once()
        self.assertEqual(mock_fetch.call_args[1]["pref_code"], "24")
        self.assertEqual(mock_fetch.call_args[1]["output_dir"], self.temp_path)

        mock_analyze.assert_called_once()
        self.assertEqual(mock_analyze.call_args[1]["target_dir"], self.temp_path / "24")
        self.assertEqual(mock_analyze.call_args[1]["engine_name"], "local")

    @patch("transform_xml.main.run_analyze_pipeline")
    @patch("transform_xml.main.run_fetch_pipeline")
    def test_run_full_pipeline_fetch_abort(self, mock_fetch, mock_analyze):
        mock_fetch.return_value = 1

        ret = run_full_pipeline([
            "24",
            "--output-dir", str(self.temp_path),
        ])
        self.assertEqual(ret, 1)
        mock_fetch.assert_called_once()
        mock_analyze.assert_not_called()


if __name__ == "__main__":
    unittest.main()
