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

from transform_xml.main import hello_world, main


class TestMain(unittest.TestCase):
    def test_hello_world_default(self):
        self.assertEqual(hello_world(), "Hello, World!")

    def test_hello_world_custom_name(self):
        self.assertEqual(hello_world("Python"), "Hello, Python!")

    @patch("sys.stdout", new_callable=io.StringIO)
    def test_main(self, mock_stdout):
        main()
        self.assertEqual(mock_stdout.getvalue().strip(), "Hello, World!")

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


if __name__ == "__main__":
    unittest.main()
