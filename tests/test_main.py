"""Unit tests for transform_xml."""

import io
import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

# src ディレクトリを sys.path に追加 (単独実行・ディスカバリ時の解決用)
_SRC_DIR = Path(__file__).resolve().parent.parent / "src"
if str(_SRC_DIR) not in sys.path:
    sys.path.insert(0, str(_SRC_DIR))

from transform_xml.main import main


class TestMain(unittest.TestCase):
    def test_main_default(self):
        ret = main([])
        self.assertEqual(ret, 0)

    @patch("transform_xml.image_xml_converter.main")
    def test_main_convert_images_to_xml(self, mock_image_xml_main):
        mock_image_xml_main.return_value = 0
        ret = main(["--convert-images-to-xml", "dummy_dir"])
        self.assertEqual(ret, 0)
        mock_image_xml_main.assert_called_once_with(["dummy_dir"])

    @patch("transform_xml.pdf_image_converter.main")
    def test_main_convert_pdfs(self, mock_convert_main):
        mock_convert_main.return_value = 0
        ret = main(["--convert-pdfs", "dummy_dir"])
        self.assertEqual(ret, 0)
        mock_convert_main.assert_called_once_with(["dummy_dir"])

    @patch("transform_xml.pdf_downloader.main")
    def test_main_fetch_pdfs(self, mock_pdf_main):
        mock_pdf_main.return_value = 0
        ret = main(["--fetch-pdfs", "dummy_dir"])
        self.assertEqual(ret, 0)
        mock_pdf_main.assert_called_once_with(["dummy_dir"])

    @patch("transform_xml.xml_integrator.main")
    def test_main_integrate_xml(self, mock_xml_integrate_main):
        mock_xml_integrate_main.return_value = 0
        ret = main(["--integrate-xml", "dummy_dir"])
        self.assertEqual(ret, 0)
        mock_xml_integrate_main.assert_called_once_with(["dummy_dir"])

    @patch("transform_xml.fetch_pipeline.main")
    def test_main_fetch_pipeline(self, mock_fetch_pipeline):
        mock_fetch_pipeline.return_value = 0
        ret = main(["--fetch-pipeline", "24"])
        self.assertEqual(ret, 0)
        mock_fetch_pipeline.assert_called_once_with(["24"])

    @patch("transform_xml.analyze_pipeline.main")
    def test_main_analyze_pipeline(self, mock_analyze_pipeline):
        mock_analyze_pipeline.return_value = 0
        ret = main(["--analyze-pipeline", "dummy_dir"])
        self.assertEqual(ret, 0)
        mock_analyze_pipeline.assert_called_once_with(["dummy_dir"])

    @patch("transform_xml.main.run_full_pipeline")
    def test_main_full_pipeline(self, mock_full_pipeline):
        mock_full_pipeline.return_value = 0
        ret = main(["--all", "24"])
        self.assertEqual(ret, 0)
        mock_full_pipeline.assert_called_once_with(["24"])


if __name__ == "__main__":
    unittest.main()
