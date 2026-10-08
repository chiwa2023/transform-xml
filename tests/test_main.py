"""Unit tests for transform_xml."""

import io
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

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


if __name__ == "__main__":
    unittest.main()
