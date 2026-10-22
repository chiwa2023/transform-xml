"""Unit tests for config module and settings.env integration."""

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from transform_xml.config import (
    find_env_file_in_argv,
    load_env_file,
    resolve_env_float,
    resolve_env_int,
    resolve_env_path,
    resolve_env_str,
    resolve_env_variable,
)
import transform_xml.pdf_downloader as pdf_downloader
import transform_xml.pdf_image_converter as pdf_image_converter
import transform_xml.site_crawler as site_crawler
import transform_xml.xml_integrator as xml_integrator


class TestConfigModule(unittest.TestCase):
    """Test suite for configuration loading and environment variable resolution."""

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.temp_path = Path(self.temp_dir.name)

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_load_env_file(self):
        """Test parsing .env file."""
        env_file = self.temp_path / "custom.env"
        env_file.write_text(
            "# Comment line\n"
            "KEY1=VALUE1\n"
            "KEY2 = 'VALUE2'\n"
            'KEY3 = "VALUE3"\n'
            "EMPTY=\n",
            encoding="utf-8",
        )

        res = load_env_file(env_file)
        self.assertEqual(res.get("KEY1"), "VALUE1")
        self.assertEqual(res.get("KEY2"), "VALUE2")
        self.assertEqual(res.get("KEY3"), "VALUE3")
        self.assertEqual(res.get("EMPTY"), "")

    def test_resolve_env_types(self):
        """Test resolving int, float, str, Path with type conversion."""
        env_file = self.temp_path / "test.env"
        env_file.write_text(
            "FLOAT_VAL=2.75\n"
            "INT_VAL=42\n"
            "STR_VAL=hello\n"
            "PATH_VAL=custom/path\n"
            "INVALID_NUM=not_a_num\n",
            encoding="utf-8",
        )

        self.assertEqual(resolve_env_float("FLOAT_VAL", env_file_path=env_file, default=1.0), 2.75)
        self.assertEqual(resolve_env_float("INVALID_NUM", env_file_path=env_file, default=1.0), 1.0)
        self.assertEqual(resolve_env_float("NON_EXISTENT", env_file_path=env_file, default=3.14), 3.14)

        self.assertEqual(resolve_env_int("INT_VAL", env_file_path=env_file, default=10), 42)
        self.assertEqual(resolve_env_int("INVALID_NUM", env_file_path=env_file, default=10), 10)

        self.assertEqual(resolve_env_str("STR_VAL", env_file_path=env_file, default="def"), "hello")
        self.assertEqual(resolve_env_str("NON_EXISTENT", env_file_path=env_file, default="def"), "def")

        self.assertEqual(resolve_env_path("PATH_VAL", env_file_path=env_file, default=Path("def")), Path("custom/path"))

    def test_find_env_file_in_argv(self):
        """Test extracting --env-file from argv before parsing."""
        self.assertIsNone(find_env_file_in_argv(["--sleep", "1.0"]))
        self.assertEqual(
            find_env_file_in_argv(["target", "--env-file", "my/path.env"]),
            Path("my/path.env"),
        )
        self.assertEqual(
            find_env_file_in_argv(["--env-file=my/path.env", "target"]),
            Path("my/path.env"),
        )


class TestCliSettingsIntegration(unittest.TestCase):
    """Test CLI default value resolution from settings.env."""

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.temp_path = Path(self.temp_dir.name)
        self.custom_env = self.temp_path / "settings.env"
        self.custom_env.write_text(
            "SLEEP_SEC=2.5\n"
            "CRAWLER_SLEEP_SEC=3.0\n"
            "MAX_CRAWL_DEPTH=5\n"
            "DOWNLOAD_SLEEP_SEC=4.0\n"
            "TIMEOUT_SEC=20.0\n"
            "PDF_IMAGE_DPI=300\n"
            "PDF_IMAGE_FORMAT=JPEG\n"
            "TEMPLATE_DIR=custom/template_dir\n",
            encoding="utf-8",
        )

    def tearDown(self):
        self.temp_dir.cleanup()

    @patch("transform_xml.pdf_downloader.download_pdfs_in_dir")
    def test_pdf_downloader_uses_settings_env_and_allows_override(self, mock_download):
        """Test pdf_downloader defaults to settings.env but CLI arguments override."""
        mock_download.return_value = pdf_downloader.DownloadResult(target_dir=self.temp_path)

        # 1. Defaults from custom env
        pdf_downloader.main([str(self.temp_path), "--env-file", str(self.custom_env)])
        mock_download.assert_called_with(
            target_dir=self.temp_path,
            sleep_sec=4.0,  # DOWNLOAD_SLEEP_SEC
            timeout=20.0,   # TIMEOUT_SEC
        )

        mock_download.reset_mock()

        # 2. CLI override
        pdf_downloader.main([
            str(self.temp_path),
            "--env-file", str(self.custom_env),
            "--sleep", "0.2",
            "--timeout", "5.0",
        ])
        mock_download.assert_called_with(
            target_dir=self.temp_path,
            sleep_sec=0.2,
            timeout=5.0,
        )

    @patch("transform_xml.pdf_image_converter.convert_pdfs_in_dir")
    def test_pdf_image_converter_uses_settings_env_and_allows_override(self, mock_convert):
        """Test pdf_image_converter defaults to settings.env but CLI arguments override."""
        mock_convert.return_value = pdf_image_converter.BatchConversionResult(target_dir=self.temp_path)

        # 1. Defaults from custom env
        pdf_image_converter.main([str(self.temp_path), "--env-file", str(self.custom_env)])
        mock_convert.assert_called_with(
            target_dir=self.temp_path,
            dpi=300,
            image_format="JPEG",
        )

        mock_convert.reset_mock()

        # 2. CLI override
        pdf_image_converter.main([
            str(self.temp_path),
            "--env-file", str(self.custom_env),
            "--dpi", "150",
            "--format", "PNG",
        ])
        mock_convert.assert_called_with(
            target_dir=self.temp_path,
            dpi=150,
            image_format="PNG",
        )

    @patch("transform_xml.site_crawler.run_crawler")
    def test_site_crawler_uses_settings_env_and_allows_override(self, mock_crawler):
        """Test site_crawler defaults to settings.env but CLI arguments override."""
        mock_crawler.return_value = 0

        # 1. Defaults from custom env
        site_crawler.main(["24", "--env-file", str(self.custom_env)])
        mock_crawler.assert_called_with(
            pref_code="24",
            output_dir=None,
            config_path=Path("config/site_crawler_config.json"),
            env_file_path=self.custom_env,
            max_depth=5,     # MAX_CRAWL_DEPTH
            sleep_sec=3.0,   # CRAWLER_SLEEP_SEC
        )

        mock_crawler.reset_mock()

        # 2. CLI override
        site_crawler.main([
            "24",
            "--env-file", str(self.custom_env),
            "--sleep", "0.5",
            "--max-depth", "10",
        ])
        mock_crawler.assert_called_with(
            pref_code="24",
            output_dir=None,
            config_path=Path("config/site_crawler_config.json"),
            env_file_path=self.custom_env,
            max_depth=10,
            sleep_sec=0.5,
        )

    @patch("transform_xml.xml_integrator.integrate_xml_in_target_dir")
    def test_xml_integrator_uses_settings_env_and_allows_override(self, mock_integrate):
        """Test xml_integrator defaults to settings.env but CLI arguments override."""
        mock_integrate.return_value = xml_integrator.BatchIntegrationResult(target_dir=self.temp_path)

        # 1. Defaults from custom env
        xml_integrator.main([str(self.temp_path), "--env-file", str(self.custom_env)])
        mock_integrate.assert_called_with(
            target_dir=self.temp_path,
            template_dir=Path("custom/template_dir"),
        )

        mock_integrate.reset_mock()

        # 2. CLI override
        xml_integrator.main([
            str(self.temp_path),
            "--env-file", str(self.custom_env),
            "--template-dir", "override/template",
        ])
        mock_integrate.assert_called_with(
            target_dir=self.temp_path,
            template_dir=Path("override/template"),
        )


if __name__ == "__main__":
    unittest.main()
