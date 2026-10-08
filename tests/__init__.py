"""Tests package."""

import sys
from pathlib import Path

# src ディレクトリを sys.path に追加してテスト時・ディスカバリ時に確実にインポート可能にする
_SRC_DIR = Path(__file__).resolve().parent.parent / "src"
if str(_SRC_DIR) not in sys.path:
    sys.path.insert(0, str(_SRC_DIR))
