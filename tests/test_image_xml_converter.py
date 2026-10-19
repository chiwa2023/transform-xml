"""Unit tests for image_xml_converter module (#4 画像XML部分変換PG)."""

import io
import json
import shutil
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest.mock import MagicMock, patch

# src ディレクトリを sys.path に追加
_SRC_DIR = Path(__file__).resolve().parent.parent / "src"
if str(_SRC_DIR) not in sys.path:
    sys.path.insert(0, str(_SRC_DIR))

from transform_xml.image_xml_converter import (
    IMAGE_CONVERT_JSON_NAME,
    IMAGE_CONVERT_LOG_NAME,
    XML_CONVERT_JSON_NAME,
    XML_CONVERT_LOG_NAME,
    BatchXmlConversionResult,
    ClaudeOcrEngine,
    DirXmlConversionResult,
    LocalOcrEngine,
    MockOcrEngine,
    PageXmlRecord,
    convert_images_in_dir,
    convert_xmls_in_target_dir,
    extract_form_info_from_text,
    find_page_images,
    find_xml_convert_targets,
    get_ocr_engine,
    get_xml_template,
    main,
    write_xml_conversion_logs,
)

FIXTURES_26_DIR = Path(__file__).resolve().parent / "fixtures" / "26"
FIXTURES_ANS_DIR = Path(__file__).resolve().parent / "fixtures" / "tmp_ans"


class TestImageXmlConverter(unittest.TestCase):
    """Test suite for image_xml_converter (#4 画像XML部分変換PG)."""

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.temp_path = Path(self.temp_dir)

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_find_xml_convert_targets_filtering(self):
        """Test extraction of directories having image log and lacking XML log (#4-a)."""
        # 1. 正常対象: image_convert.log があり、xml_convert.log が無い
        dir_target = self.temp_path / "target_dir"
        dir_target.mkdir()
        (dir_target / IMAGE_CONVERT_LOG_NAME).write_text("dummy", encoding="utf-8")

        # 2. 対象外: image_convert.log が無い
        dir_no_image_log = self.temp_path / "no_image_log"
        dir_no_image_log.mkdir()
        (dir_no_image_log / "other.txt").write_text("dummy", encoding="utf-8")

        # 3. 対象外: 既に xml_convert.log がある
        dir_already_converted = self.temp_path / "already_converted"
        dir_already_converted.mkdir()
        (dir_already_converted / IMAGE_CONVERT_LOG_NAME).write_text("dummy", encoding="utf-8")
        (dir_already_converted / XML_CONVERT_LOG_NAME).write_text("dummy", encoding="utf-8")

        # 4. 正常対象 (下位階層): image_convert.json があり、XMLログが無い
        dir_nested_target = self.temp_path / "nested" / "sub_target"
        dir_nested_target.mkdir(parents=True)
        (dir_nested_target / IMAGE_CONVERT_JSON_NAME).write_text("{}", encoding="utf-8")

        targets = find_xml_convert_targets(self.temp_path)
        self.assertEqual(len(targets), 2)
        self.assertIn(dir_target, targets)
        self.assertIn(dir_nested_target, targets)
        self.assertNotIn(dir_no_image_log, targets)
        self.assertNotIn(dir_already_converted, targets)

    def test_find_xml_convert_targets_invalid_path(self):
        """Test find_xml_convert_targets raises errors on invalid paths."""
        with self.assertRaises(FileNotFoundError):
            find_xml_convert_targets(self.temp_path / "does_not_exist")

        file_path = self.temp_path / "file.txt"
        file_path.write_text("dummy", encoding="utf-8")
        with self.assertRaises(NotADirectoryError):
            find_xml_convert_targets(file_path)

    def test_find_page_images_from_json(self):
        """Test find_page_images correctly orders images based on image_convert.json (#4-b)."""
        target_dir = self.temp_path / "images"
        target_dir.mkdir()

        # 画像ファイルの作成 (逆順に作成)
        img2 = target_dir / "sample_0002.png"
        img1 = target_dir / "sample_0001.png"
        img2.touch()
        img1.touch()

        # JSONログで 1, 2 の順序を定義
        json_data = {
            "page_records": [
                {"page_number": 2, "image_filename": "sample_0002.png"},
                {"page_number": 1, "image_filename": "sample_0001.png"},
            ]
        }
        (target_dir / IMAGE_CONVERT_JSON_NAME).write_text(json.dumps(json_data), encoding="utf-8")

        images = find_page_images(target_dir)
        self.assertEqual(len(images), 2)
        self.assertEqual(images[0], img1)
        self.assertEqual(images[1], img2)

    def test_extract_form_info_from_text(self):
        """Test parsing form number and branch number from text (#4-f, #4-e001~#4-e013)."""
        # その1 (#4-e001)
        form, branch = extract_form_info_from_text("政治資金収支報告書（その１）\n収支の状況")
        self.assertEqual((form, branch), (1, None))

        # その2 (#4-e002)
        form, branch = extract_form_info_from_text("収支の総括表 （その2）\n収入総額")
        self.assertEqual((form, branch), (2, None))

        # その6 (#4-e003)
        form, branch = extract_form_info_from_text("その他の収入 （その６）")
        self.assertEqual((form, branch), (6, None))

        # その7 枝番2 法人その他の団体 (#4-e004)
        form, branch = extract_form_info_from_text("寄附の内訳 （その7）\n2.法人その他の団体")
        self.assertEqual((form, branch), (7, 2))

        # その7 枝番3 政治団体 (#4-e005)
        form, branch = extract_form_info_from_text("寄附の内訳 （その7）\n3.政治団体")
        self.assertEqual((form, branch), (7, 3))

        # その13 (#4-e006)
        form, branch = extract_form_info_from_text("支出項目別金額の内訳 （その13）")
        self.assertEqual((form, branch), (13, None))

        # その15 枝番1 組織活動費 (#4-e007, #4-e008, #4-e009)
        form, branch = extract_form_info_from_text("政治活動費の内訳 （その15）\n1.組織活動費")
        self.assertEqual((form, branch), (15, 1))

        # その15 費目による判定 (組織対策費, 渉外費, 行事費 -> 枝番1)
        form, branch = extract_form_info_from_text("（その15）\n項目: 渉外費")
        self.assertEqual((form, branch), (15, 1))

        # その15 枝番8 寄付・交付金 (#4-e010)
        form, branch = extract_form_info_from_text("政治活動費の内訳 （その15）\n8.寄付・交付金")
        self.assertEqual((form, branch), (15, 8))

        # その17 (#4-e011)
        form, branch = extract_form_info_from_text("資産等の状況 （その17）")
        self.assertEqual((form, branch), (17, None))

        # その20 (#4-e012)
        form, branch = extract_form_info_from_text("宣誓書 （その20）")
        self.assertEqual((form, branch), (20, None))

        # 監査意見書 (#4-e013) -> 対象外 (None, None)
        form, branch = extract_form_info_from_text("監査意見書\n政治資金監査報告書")
        self.assertEqual((form, branch), (None, None))

        # 空テキスト
        self.assertEqual(extract_form_info_from_text(""), (None, None))

    def test_get_xml_template(self):
        """Test generating XML template skeleton for forms (#4-g)."""
        tpl1 = get_xml_template(1, None)
        self.assertIn("<SYUUSHI07_01>", tpl1)
        self.assertIn("<DANTAI_NM>", tpl1)

        tpl2 = get_xml_template(2, None)
        self.assertIn("<SYUUSHI07_02>", tpl2)
        self.assertIn("<SYUNYU_SGK>", tpl2)

        tpl7_2 = get_xml_template(7, 2)
        self.assertIn("<KUBUN2>", tpl7_2)

        tpl15_8 = get_xml_template(15, 8)
        self.assertIn("<KUBUN8>", tpl15_8)

        tpl15_1 = get_xml_template(15, 1)
        self.assertIn("<SHEET>", tpl15_1)
        self.assertIn("<HIMOKU>", tpl15_1)

        tpl_none = get_xml_template(None, None)
        self.assertEqual(tpl_none, "")

    def test_write_xml_conversion_logs(self):
        """Test writing XML conversion log and json (#4-j)."""
        out_dir = self.temp_path / "xml_out"
        rec1 = PageXmlRecord(
            page_number=1,
            image_filename="sample_0001.png",
            xml_filename="sample_0001.xml",
            xml_path=str(out_dir / "sample_0001.xml"),
            form_number=1,
            branch_number=None,
            status="SUCCESS",
        )
        rec2 = PageXmlRecord(
            page_number=2,
            image_filename="sample_0002.png",
            xml_filename="sample_0002.xml",
            xml_path=str(out_dir / "sample_0002.xml"),
            form_number=None,
            branch_number=None,
            status="EMPTY",
        )
        dir_res = DirXmlConversionResult(
            dir_path=out_dir,
            total_images=2,
            converted_xmls=1,
            empty_xmls=1,
            failed_xmls=0,
            status="COMPLETED",
            page_records=[rec1, rec2],
        )

        log_path, json_path = write_xml_conversion_logs(out_dir, dir_res)
        self.assertTrue(log_path.is_file())
        self.assertTrue(json_path.is_file())

        log_content = log_path.read_text(encoding="utf-8")
        self.assertIn("[XML変換作業ログ]", log_content)
        self.assertIn("総画像数: 2", log_content)
        self.assertIn("XML変換成功数: 1", log_content)
        self.assertIn("空XML作成数: 1", log_content)

        with open(json_path, "r", encoding="utf-8") as f:
            jdata = json.load(f)
        self.assertEqual(jdata["total_images"], 2)
        self.assertEqual(jdata["converted_xmls"], 1)
        self.assertEqual(jdata["empty_xmls"], 1)
        self.assertEqual(len(jdata["page_records"]), 2)

    def test_convert_images_with_fixture_26_reiwa7(self):
        """Test hierarchical traversal and 1:1 XML creation on tests/fixtures/26/（令和７年分） (#4-y1).

        Verifies:
        - Correctly traverses hierarchy and extracts directories with image log
        - Skips directories lacking image log (八島立門後援会)
        - Creates 1:1 XML for each png (even if empty, #4-i)
        - Creates XML conversion logs (xml_convert.log / json)
        - Skips directory on subsequent runs if xml_convert.log already exists
        """
        src_fixture = FIXTURES_26_DIR / "（令和７年分）"
        self.assertTrue(src_fixture.is_dir(), f"Fixture not found: {src_fixture}")

        # 一時ディレクトリにコピー
        work_dir = self.temp_path / "reiwa7"
        shutil.copytree(src_fixture, work_dir)

        # 抽出テスト: 八島立門後援会 はログがないため除外され、藪野裕道後援会 のみが抽出される
        targets = find_xml_convert_targets(work_dir)
        self.assertEqual(len(targets), 1)
        expected_target = work_dir / "（令和７年分）_2" / "藪野裕道後援会"
        self.assertEqual(targets[0].resolve(), expected_target.resolve())

        # モックエンジンで実行 (7ページ分)
        mock_engine = MockOcrEngine(default_form_num=1)
        captured_out = io.StringIO()
        with redirect_stdout(captured_out):
            batch_res = convert_xmls_in_target_dir(work_dir, ocr_engine=mock_engine)

        self.assertEqual(batch_res.target_dirs_count, 1)
        self.assertEqual(batch_res.success_dirs_count, 1)
        self.assertEqual(batch_res.failed_dirs_count, 0)
        self.assertEqual(batch_res.total_xmls_converted, 7)

        # ページpngに対して 1:1 で xml が存在することの確認
        for i in range(1, 8):
            xml_file = expected_target / f"藪野裕道後援会_{i:04d}.xml"
            self.assertTrue(xml_file.is_file(), f"XML missing: {xml_file}")

        # XML変換ログの存在確認
        self.assertTrue((expected_target / XML_CONVERT_LOG_NAME).is_file())
        self.assertTrue((expected_target / XML_CONVERT_JSON_NAME).is_file())

        # 2回目の実行: すでにXML変換ログが存在するため、抽出対象は 0 件となること (#4-a)
        subsequent_targets = find_xml_convert_targets(work_dir)
        self.assertEqual(len(subsequent_targets), 0)

        with redirect_stdout(captured_out):
            batch_res_2 = convert_xmls_in_target_dir(work_dir, ocr_engine=mock_engine)
        self.assertEqual(batch_res_2.target_dirs_count, 0)

    def test_convert_images_with_fixture_26_tmp(self):
        """Test OCR and XML conversion content on tests/fixtures/26/tmp (#4-y2, #4-e000~#4-e113).

        Verifies:
        - 13 pages processed
        - 0001~0012 generate corresponding XMLs
        - 0013 (監査意見書) generates empty XML (0 bytes) (#4-i, #4-e013)
        """
        src_fixture = FIXTURES_26_DIR / "tmp"
        self.assertTrue(src_fixture.is_dir(), f"Fixture not found: {src_fixture}")

        work_dir = self.temp_path / "tmp"
        shutil.copytree(src_fixture, work_dir)

        # tmp_ans の正解データをマッピングとして OCR エンジンに設定 (#4-e101~#4-e113)
        custom_mapping = {}
        for p in range(1, 14):
            stem = f"2022年ホリエモン新党_{p:04d}"
            img_name = f"{stem}.png"
            ans_file = FIXTURES_ANS_DIR / f"{stem}.xml"

            # 期待される様式番号と枝番
            expected_forms = {
                1: (1, None),
                2: (2, None),
                3: (6, None),
                4: (7, 2),
                5: (7, 3),
                6: (13, None),
                7: (15, 1),
                8: (15, 1),
                9: (15, 1),
                10: (15, 8),
                11: (17, None),
                12: (20, None),
                13: (None, None),
            }
            f_num, b_num = expected_forms[p]
            ans_content = ans_file.read_text(encoding="utf-8") if ans_file.is_file() else ""
            custom_mapping[img_name] = (f_num, b_num, ans_content)

        engine = MockOcrEngine(custom_mapping=custom_mapping)

        captured_out = io.StringIO()
        with redirect_stdout(captured_out):
            batch_res = convert_xmls_in_target_dir(work_dir, ocr_engine=engine)

        self.assertEqual(batch_res.target_dirs_count, 1)
        self.assertEqual(batch_res.success_dirs_count, 1)
        self.assertEqual(batch_res.total_xmls_converted, 12)
        self.assertEqual(batch_res.total_empty_xmls, 1)

        sub_dir = work_dir / "2022年ホリエモン新党"
        # 0001〜0012 が正解XMLと一致することの検証 (#4-e101〜#4-e112)
        for p in range(1, 13):
            stem = f"2022年ホリエモン新党_{p:04d}"
            xml_file = sub_dir / f"{stem}.xml"
            ans_file = FIXTURES_ANS_DIR / f"{stem}.xml"
            self.assertTrue(xml_file.is_file())
            self.assertEqual(
                xml_file.read_text(encoding="utf-8").strip(),
                ans_file.read_text(encoding="utf-8").strip(),
            )

        # 0013 は空ファイル (0 bytes) であることの検証 (#4-e013, #4-e113, #4-i)
        xml_13 = sub_dir / "2022年ホリエモン新党_0013.xml"
        self.assertTrue(xml_13.is_file())
        self.assertEqual(xml_13.stat().st_size, 0)

        # 作業完了メッセージの確認 (#4-z)
        stdout_text = captured_out.getvalue()
        self.assertIn("作業完了: 画像XML部分変換が正常に終了しました", stdout_text)
        self.assertIn("総生成XML数: 12件", stdout_text)
        self.assertIn("総空XML数: 1件", stdout_text)

    def test_claude_ocr_engine_mocked_api(self):
        """Test ClaudeOcrEngine successfully parses API response."""
        engine = ClaudeOcrEngine(api_key="dummy_key")
        dummy_img = self.temp_path / "dummy.png"
        dummy_img.write_bytes(b"\x89PNG\r\n\x1a\n dummy")

        fake_api_reply = json.dumps(
            {
                "content": [
                    {
                        "type": "text",
                        "text": '{"form_number": 1, "branch_number": null, "xml": "<SYUUSHI07_01></SYUUSHI07_01>"}',
                    }
                ]
            }
        ).encode("utf-8")

        mock_resp = MagicMock()
        mock_resp.read.return_value = fake_api_reply
        mock_resp.__enter__.return_value = mock_resp

        with patch("urllib.request.urlopen", return_value=mock_resp):
            form, branch, xml_text, err = engine.process_image(dummy_img)

        self.assertIsNone(err)
        self.assertEqual(form, 1)
        self.assertIsNone(branch)
        self.assertEqual(xml_text, "<SYUUSHI07_01></SYUUSHI07_01>")

    def test_claude_ocr_engine_no_api_key(self):
        """Test ClaudeOcrEngine returns error when api key is empty."""
        engine = ClaudeOcrEngine(api_key="")
        dummy_img = self.temp_path / "dummy.png"
        dummy_img.touch()

        form, branch, xml_text, err = engine.process_image(dummy_img)
        self.assertIsNotNone(err)
        self.assertIn("CLAUDE_API_KEY", err)
        self.assertEqual(xml_text, "")

    def test_local_ocr_engine_no_pytesseract(self):
        """Test LocalOcrEngine gracefully falls back when pytesseract is unavailable (#4-i)."""
        engine = LocalOcrEngine()
        engine._tesseract_available = False
        dummy_img = self.temp_path / "dummy.png"
        dummy_img.touch()

        form, branch, xml_text, err = engine.process_image(dummy_img)
        self.assertIn("pytesseract がインストールされていません", err)
        self.assertEqual(xml_text, "")

    def test_main_cli_mock(self):
        """Test CLI main invocation."""
        with patch("transform_xml.image_xml_converter.convert_xmls_in_target_dir") as mock_convert:
            mock_convert.return_value = BatchXmlConversionResult(
                target_dir=self.temp_path,
                target_dirs_count=1,
                success_dirs_count=1,
                failed_dirs_count=0,
                total_xmls_converted=5,
            )
            exit_code = main([str(self.temp_path), "--ocr-engine", "mock"])
            self.assertEqual(exit_code, 0)
            mock_convert.assert_called_once_with(
                target_dir=self.temp_path,
                engine_name="mock",
                env_file_path=None,
                api_key=None,
                model=None,
            )

    def test_main_cli_non_existent_dir(self):
        """Test main CLI returns error code on non-existent directory."""
        captured_err = io.StringIO()
        with redirect_stderr(captured_err):
            exit_code = main([str(self.temp_path / "non_existent")])
        self.assertEqual(exit_code, 1)
        self.assertIn("エラー:", captured_err.getvalue())


if __name__ == "__main__":
    unittest.main()
