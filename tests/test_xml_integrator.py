"""Unit tests for xml_integrator module (#5 XML部分統合PG)."""

import io
import json
import shutil
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

# src ディレクトリを sys.path に追加
_SRC_DIR = Path(__file__).resolve().parent.parent / "src"
if str(_SRC_DIR) not in sys.path:
    sys.path.insert(0, str(_SRC_DIR))

from transform_xml.xml_integrator import (
    TEMPLATE_BLANK_DIR_NAME,
    TEMPLATE_LEAST_NAME,
    XML_CONVERT_JSON_NAME,
    XML_CONVERT_LOG_NAME,
    BatchIntegrationResult,
    IntegrationResult,
    check_xml_conversion_completed,
    find_integration_targets,
    find_partial_xml_files,
    get_blank_mapping,
    integrate_single_dir,
    integrate_xml_in_target_dir,
    main,
    parse_partial_xml,
)

FIXTURES_27_DIR = Path(__file__).resolve().parent / "fixtures" / "27"
FIXTURES_27_ANS_DIR = Path(__file__).resolve().parent / "fixtures" / "27_ans"
TEMPLATE_DIR = Path(__file__).resolve().parent.parent / "config" / "template"


class TestXmlIntegrator(unittest.TestCase):
    """Test suite for xml_integrator (#5 XML部分統合PG)."""

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.temp_path = Path(self.temp_dir)

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_find_integration_targets(self):
        """Test finding directories containing XML conversion logs (#5-1)."""
        # 1. ログが存在するディレクトリを作成
        dir_ok1 = self.temp_path / "group1" / "pdf_a"
        dir_ok1.mkdir(parents=True)
        (dir_ok1 / XML_CONVERT_JSON_NAME).write_text("{}", encoding="utf-8")

        dir_ok2 = self.temp_path / "group2" / "pdf_b"
        dir_ok2.mkdir(parents=True)
        (dir_ok2 / XML_CONVERT_LOG_NAME).write_text("dummy log", encoding="utf-8")

        # 2. ログが存在しないディレクトリ
        dir_ng = self.temp_path / "group1" / "no_log"
        dir_ng.mkdir(parents=True)
        (dir_ng / "some_file.txt").write_text("text", encoding="utf-8")

        targets = find_integration_targets(self.temp_path)
        self.assertEqual(len(targets), 2)
        self.assertIn(dir_ok1, targets)
        self.assertIn(dir_ok2, targets)
        self.assertNotIn(dir_ng, targets)

    def test_find_integration_targets_on_fixtures_27(self):
        """Test target extraction on real fixtures tests/fixtures/27 (#5-1)."""
        targets = find_integration_targets(FIXTURES_27_DIR)
        target_names = [t.name for t in targets]
        self.assertEqual(len(targets), 2)
        self.assertIn("2022年ホリエモン新党", target_names)
        self.assertIn("藪野裕道後援会", target_names)
        self.assertNotIn("八島立門後援会", target_names)

    def test_check_xml_conversion_completed(self):
        """Test validation of XML conversion logs (#5-2)."""
        # 正常系 (JSON)
        dir_success = self.temp_path / "success_dir"
        dir_success.mkdir()
        json_data = {
            "status": "COMPLETED",
            "failed_xmls": 0,
            "page_records": [
                {"page_number": 1, "status": "SUCCESS"},
                {"page_number": 2, "status": "SUCCESS"},
            ],
        }
        (dir_success / XML_CONVERT_JSON_NAME).write_text(
            json.dumps(json_data), encoding="utf-8"
        )
        ok, msg = check_xml_conversion_completed(dir_success)
        self.assertTrue(ok)
        self.assertIsNone(msg)

        # 異常系 (JSON failed_xmls > 0)
        dir_failed = self.temp_path / "failed_dir"
        dir_failed.mkdir()
        json_data_failed = {
            "status": "FAILED",
            "failed_xmls": 1,
            "page_records": [{"page_number": 1, "status": "FAILED"}],
        }
        (dir_failed / XML_CONVERT_JSON_NAME).write_text(
            json.dumps(json_data_failed), encoding="utf-8"
        )
        ok, msg = check_xml_conversion_completed(dir_failed)
        self.assertFalse(ok)
        self.assertIn("失敗", msg)

        # ログなし
        dir_empty = self.temp_path / "empty_dir"
        dir_empty.mkdir()
        ok, msg = check_xml_conversion_completed(dir_empty)
        self.assertFalse(ok)
        self.assertIn("存在しません", msg)

    def test_get_blank_mapping(self):
        """Test building blank mapping from template directory (#5-3d)."""
        mapping = get_blank_mapping(TEMPLATE_DIR)
        self.assertEqual(len(mapping), 49)

        # 様式1 (枝番なし) -> 01_01_blank.xml, order=1
        self.assertIn((1, None), mapping)
        self.assertEqual(mapping[(1, None)], ("01_01_blank.xml", 1))

        # 様式7 枝番2 -> 08_07_02_blank.xml, order=8
        self.assertIn((7, 2), mapping)
        self.assertEqual(mapping[(7, 2)], ("08_07_02_blank.xml", 8))

        # 様式20 (枝番なし) -> 49_20_blank.xml, order=49
        self.assertIn((20, None), mapping)
        self.assertEqual(mapping[(20, None)], ("49_20_blank.xml", 49))

    def test_parse_partial_xml(self):
        """Test parsing partial XML and handling empty files (#5-3b, #4-i)."""
        # 空ファイル
        empty_file = self.temp_path / "test_0001.xml"
        empty_file.write_text("", encoding="utf-8")
        self.assertIsNone(parse_partial_xml(empty_file))

        # 枝番なしXML
        xml_no_branch = self.temp_path / "test_0002.xml"
        xml_no_branch.write_text(
            "<SYUUSHI07_01><SHEET><DANTAI_NM>テスト</DANTAI_NM></SHEET></SYUUSHI07_01>",
            encoding="utf-8",
        )
        form, branch, content = parse_partial_xml(xml_no_branch)
        self.assertEqual(form, 1)
        self.assertIsNone(branch)

        # 枝番ありXML
        xml_with_branch = self.temp_path / "test_0003.xml"
        xml_with_branch.write_text(
            "<SYUUSHI07_15><KUBUN1><SHEET><HIMOKU>費</HIMOKU></SHEET></KUBUN1></SYUUSHI07_15>",
            encoding="utf-8",
        )
        form, branch, content = parse_partial_xml(xml_with_branch)
        self.assertEqual(form, 15)
        self.assertEqual(branch, 1)

    def test_integrate_single_dir_horie(self):
        """Test integration of Horie partial XMLs against 27_ans (#5-y).

        tests/fixtures/27/tmp/2022年ホリエモン新党 の処理結果が
        tests/fixtures/27_ans/tmp/2022年ホリエモン新党/2022年ホリエモン新党.xml と
        バイト単位で完全一致することを検証する。
        """
        src_horie = FIXTURES_27_DIR / "tmp" / "2022年ホリエモン新党"
        dest_horie = self.temp_path / "2022年ホリエモン新党"
        shutil.copytree(src_horie, dest_horie)

        res = integrate_single_dir(dest_horie, template_dir=TEMPLATE_DIR)
        self.assertEqual(res.status, "SUCCESS")
        self.assertEqual(res.page_count, 12)
        self.assertTrue(res.output_xml_path.is_file())

        generated_bytes = res.output_xml_path.read_bytes()
        expected_path = (
            FIXTURES_27_ANS_DIR
            / "tmp"
            / "2022年ホリエモン新党"
            / "2022年ホリエモン新党.xml"
        )
        expected_bytes = expected_path.read_bytes()

        self.assertEqual(
            generated_bytes,
            expected_bytes,
            "生成された2022年ホリエモン新党.xmlが27_ansとバイト単位で一致しません",
        )

    def test_integrate_single_dir_yabuno(self):
        """Test integration of Yabuno partial XMLs against 27_ans (#5-y).

        tests/fixtures/27/（令和７年分）/（令和７年分）_2/藪野裕道後援会 の処理結果が
        tests/fixtures/27_ans/.../藪野裕道後援会.xml とバイト単位で完全一致することを検証する。
        """
        src_yabuno = (
            FIXTURES_27_DIR / "（令和７年分）" / "（令和７年分）_2" / "藪野裕道後援会"
        )
        dest_yabuno = self.temp_path / "藪野裕道後援会"
        shutil.copytree(src_yabuno, dest_yabuno)

        res = integrate_single_dir(dest_yabuno, template_dir=TEMPLATE_DIR)
        self.assertEqual(res.status, "SUCCESS")
        self.assertEqual(res.page_count, 7)
        self.assertTrue(res.output_xml_path.is_file())

        generated_bytes = res.output_xml_path.read_bytes()
        expected_path = (
            FIXTURES_27_ANS_DIR
            / "（令和７年分）"
            / "（令和７年分）_2"
            / "藪野裕道後援会"
            / "藪野裕道後援会.xml"
        )
        expected_bytes = expected_path.read_bytes()

        self.assertEqual(
            generated_bytes,
            expected_bytes,
            "生成された藪野裕道後援会.xmlが27_ansとバイト単位で一致しません",
        )

    def test_integrate_xml_in_target_dir_batch(self):
        """Test batch integration on fixtures 27 (#5-4, #5-z)."""
        copy_dest = self.temp_path / "27"
        shutil.copytree(FIXTURES_27_DIR, copy_dest)

        batch_res = integrate_xml_in_target_dir(
            copy_dest, template_dir=TEMPLATE_DIR
        )
        self.assertEqual(batch_res.total_dirs, 2)
        self.assertEqual(batch_res.success_count, 2)
        self.assertEqual(batch_res.skipped_count, 0)
        self.assertEqual(batch_res.failed_count, 0)

        # 2つの成果物XMLが生成されていること
        horie_out = copy_dest / "tmp" / "2022年ホリエモン新党" / "2022年ホリエモン新党.xml"
        yabuno_out = (
            copy_dest
            / "（令和７年分）"
            / "（令和７年分）_2"
            / "藪野裕道後援会"
            / "藪野裕道後援会.xml"
        )
        self.assertTrue(horie_out.is_file())
        self.assertTrue(yabuno_out.is_file())

    def test_main_cli(self):
        """Test CLI main function for xml_integrator."""
        copy_dest = self.temp_path / "27"
        shutil.copytree(FIXTURES_27_DIR, copy_dest)

        f = io.StringIO()
        with redirect_stdout(f):
            ret = main([str(copy_dest)])
        self.assertEqual(ret, 0)
        self.assertIn("作業完了: 成功=2", f.getvalue())


if __name__ == "__main__":
    unittest.main()
