"""Tests for verify_claude_api.py."""

import io
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from verify_claude_api import get_api_key_and_model, load_env_file, main


class TestVerifyClaudeApi(unittest.TestCase):
    """Test suite for Claude API verification script."""

    def test_load_env_file(self):
        """Test loading key-values from env file."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            env_file = Path(tmp_dir) / "test.env"
            env_file.write_text(
                "# Comment\nCLAUDE_API_KEY=test_key_123\nCLAUDE_MODEL=claude-sonnet-4-6\n",
                encoding="utf-8",
            )
            data = load_env_file(env_file)
            self.assertEqual(data["CLAUDE_API_KEY"], "test_key_123")
            self.assertEqual(data["CLAUDE_MODEL"], "claude-sonnet-4-6")

    def test_get_api_key_and_model_defaults_and_priority(self):
        """Test API key and model resolution priorities."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            env_file = Path(tmp_dir) / "test.env"
            env_file.write_text(
                "CLAUDE_API_KEY=env_file_key\nCLAUDE_MODEL=env_file_model\n",
                encoding="utf-8",
            )

            # 1. From env file
            with patch.dict(os.environ, {}, clear=True):
                key, model = get_api_key_and_model(env_file_path=str(env_file))
                self.assertEqual(key, "env_file_key")
                self.assertEqual(model, "env_file_model")

            # 2. Command-line arg overrides env file
            with patch.dict(os.environ, {}, clear=True):
                key, model = get_api_key_and_model(
                    arg_api_key="arg_key",
                    arg_model="arg_model",
                    env_file_path=str(env_file),
                )
                self.assertEqual(key, "arg_key")
                self.assertEqual(model, "arg_model")

    @patch("anthropic.Anthropic")
    def test_main_success(self, mock_anthropic_cls):
        """Test main succeeds when API returns response."""
        mock_client = MagicMock()
        mock_anthropic_cls.return_value = mock_client

        mock_content_block = MagicMock()
        mock_content_block.text = "OK"
        mock_response = MagicMock()
        mock_response.content = [mock_content_block]
        mock_client.messages.create.return_value = mock_response

        with patch("sys.argv", ["verify_claude_api.py", "--api-key", "dummy_key_12345"]):
            with patch("sys.stdout", new_callable=io.StringIO) as mock_out:
                exit_code = main()
                self.assertEqual(exit_code, 0)
                output = mock_out.getvalue()
                self.assertIn("疎通成功", output)
                self.assertIn("OK", output)

    @patch("anthropic.Anthropic")
    def test_main_list_models(self, mock_anthropic_cls):
        """Test main --list-models flag."""
        mock_client = MagicMock()
        mock_anthropic_cls.return_value = mock_client

        mock_m1 = MagicMock()
        mock_m1.id = "claude-haiku-4-5-20251001"
        mock_m2 = MagicMock()
        mock_m2.id = "claude-sonnet-4-6"
        mock_models_resp = MagicMock()
        mock_models_resp.data = [mock_m1, mock_m2]
        mock_client.models.list.return_value = mock_models_resp

        with patch(
            "sys.argv",
            ["verify_claude_api.py", "--api-key", "dummy_key_12345", "--list-models"],
        ):
            with patch("sys.stdout", new_callable=io.StringIO) as mock_out:
                exit_code = main()
                self.assertEqual(exit_code, 0)
                output = mock_out.getvalue()
                self.assertIn("claude-haiku-4-5-20251001", output)
                self.assertIn("claude-sonnet-4-6", output)

    def test_main_no_api_key(self):
        """Test main fails gracefully when no API key is provided."""
        with patch.dict(os.environ, {}, clear=True):
            with patch(
                "sys.argv",
                ["verify_claude_api.py", "--env-file", "non_existent.env"],
            ):
                with patch("sys.stdout", new_callable=io.StringIO) as mock_out:
                    exit_code = main()
                    self.assertEqual(exit_code, 1)
                    output = mock_out.getvalue()
                    self.assertIn("APIキーが見つかりません", output)


if __name__ == "__main__":
    unittest.main()
