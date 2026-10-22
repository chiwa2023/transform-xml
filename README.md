# transform-xml

政治資金収支報告書のウェブ巡回・PDF取得・画像変換から、OCRによる部分XML化および全体成果物XMLへの統合成形までを自動処理するPythonプロジェクトです。

---

## 目次

1. [概要と全体フロー](#1-概要と全体フロー)
2. [動作要件とOCRエンジンの選択（重要）](#2-動作要件とocrエンジンの選択重要)
3. [セットアップとインストール](#3-セットアップとインストール)
4. [実行方法（パイプライン ＆ 個別実行）](#4-実行方法パイプライン--個別実行)
   - [4.1 連続実行パイプライン (推奨運用)](#41-連続実行パイプライン-推奨運用)
   - [4.2 個別PG実行](#42-個別pg実行)
5. [設定ファイル仕様 (`config/settings.env`)](#5-設定ファイル仕様-configsettingsenv)
6. [Claude Vision API の設定と疎通確認](#6-claude-vision-api-の設定と疎通確認)
7. [Tesseract OCR のセットアップ (ローカルOCR選択時のみ)](#7-tesseract-ocr-のセットアップ-ローカルocr選択時のみ)
8. [テスト実行](#8-テスト実行)
9. [ディレクトリ構成 (src-layout)](#9-ディレクトリ構成-src-layout)

---

## 1. 概要と全体フロー

本ツールは以下の5つの工程（#1〜#5）で政治資金収支報告書を処理します。

```text
[#1 サイト巡回]        指定した地方自治体ページを探索し、PDFリンク一覧 (pdf_links.csv) を生成
       │
       ▼
[#2 PDF取得]          リンク一覧からPDFファイルをダウンロード保存
       │
       ▼
[#3 PDF画像変換]      PDFをページごとの画像ファイル (PNG等) に一括変換
       │
       ▼  ======================================================
       ▼  【取得系 (#1〜#3)】 と 【解析系 (#4〜#5)】 の境界
       ▼  ======================================================
       │
[#4 画像XML部分変換]  各ページ画像をOCR解析し、様式番号・枝番を判定して部分XMLを生成
       │
       ▼
[#5 XML部分統合]      全ページの部分XMLをテンプレートに流し込み、提出用1XMLに統合成形
```

日常の運用では、**取得系をひとまとめにした「連続実行取得PG (#1〜#3)」** と、**解析系をひとまとめにした「連続実行解析PG (#4〜#5)」** の2ステップ運用が最も効率的です（全工程の一括通し実行や、各工程の個別実行も可能です）。

---

## 2. 動作要件とOCRエンジンの選択（重要）

本リポジトリを利用するにあたり、**「画像解析（#4）をどのエンジンで実行するか」** を事前にご確認ください。  
**外部バイナリのインストール可否やネットワーク環境に応じて、以下の3方式から自由に選択できます。**

### 2.1 OCRエンジンの比較

| エンジン方式 | 外部ツールのインストール | インターネット接続 | 特徴・向いている環境 |
| :--- | :---: | :---: | :--- |
| **A. Claude Vision API**<br>*(推奨)* | **不要**<br>(pipライブラリのみ) | 必要 | **OSへの外部バイナリ/OCRツール導入が不要。** 高精度な様式判別。APIキーがあれば即座に利用可能。 |
| **B. Tesseract OCR**<br>*(ローカル)* | **必要**<br>(Tesseract本体 + 日本語データ) | 不要<br>(完全オフライン) | **完全オフライン環境で動作。** 外部API通信不可のセキュア環境向け。OSごとのTesseract導入が必要。 |
| **C. モック / ダミー**<br>*(テスト用)* | **不要** | 不要 | ユニットテストやフィクスチャ検証用。環境構築なしで動作確認可能。 |

> 💡 **「Tesseract などの外部プラグイン・バイナリをOSにインストールしたくない／できない環境」の場合**:  
> **方式A（Claude Vision API）** を選択してください。OSへの追加ツールの導入は一切不要で、Python環境とAPIキーのみで動作します。  
> また、万が一どちらの環境も整っていない場合でも、システムは異常終了せず安全に空のXMLスケルトンを作成して後続処理を継続するフォールバック設計（仕様 `#4-i`）を備えています。

### 2.2 システム要件
- **OS**: Windows 10/11, macOS, Linux
- **Python**: 3.10 以上

---

## 3. セットアップとインストール

### 3.1 リポジトリのクローンと仮想環境作成

```bash
git clone https://github.com/your-org/transform-xml.git
cd transform-xml

# 仮想環境の作成と有効化 (推奨)
python -m venv .venv

# Windows (PowerShell)
.venv\Scripts\Activate.ps1

# macOS / Linux (Bash)
source .venv/bin/activate
```

### 3.2 パッケージのインストール

```bash
# 編集可能モードでインストール (基本依存関係: pypdfium2, pillow が導入されます)
pip install -e .

# [方式A: Claude API を利用する場合]
pip install anthropic

# [方式B: ローカル Tesseract OCR を利用する場合]
pip install pytesseract
# ※別途 Tesseract 本体のインストールが必要です (後述の「7. Tesseract OCR のセットアップ」参照)
```

### 3.3 設定ファイルの準備 (`config/settings.env`)

設定サンプル `config/settings.env.example` をコピーして `config/settings.env` を作成します。

```bash
# Windows (PowerShell)
Copy-Item config\settings.env.example config\settings.env

# macOS / Linux (Bash)
cp config/settings.env.example config/settings.env
```

`config/settings.env` を開き、必要に応じて設定を編集します（Claude APIキー、成果物保存ディレクトリ、スリープ秒数など）。

---

## 4. 実行方法（パイプライン ＆ 個別実行）

インストール後は `transform-xml` コマンド、または `python src/transform_xml/...` で直接実行できます。  
引数の初期値（スリープ秒数、タイムアウト、解像度等）は `config/settings.env` の設定が自動適用されます（コマンド実行時の引数指定による上書きも可能）。

### 4.1 連続実行パイプライン (推奨運用)

業務で最もよく使われる連続実行モジュールです。

#### (1) 連続実行取得PG (`fetch_pipeline` / #1 サイト巡回 $\rightarrow$ #2 PDF取得 $\rightarrow$ #3 PDF画像変換)

地方公共団体コード県（例: `24` 三重県、`00` 総務省）を指定するだけで、巡回・PDFダウンロード・画像化までを一括処理します。

```bash
# CLI実行
transform-xml --fetch-pipeline 24

# スクリプト直接実行
python src/transform_xml/fetch_pipeline.py 24

# 待機秒数やタイムアウトを指定して実行
transform-xml --fetch-pipeline 24 --sleep 0.5 --timeout 10.0
```

#### (2) 連続実行解析PG (`analyze_pipeline` / #4 画像XML部分変換 $\rightarrow$ #5 XML部分統合)

処理対象ディレクトリ（または県コード `24`）を指定して、画像からの部分XML生成と全体XMLへの統合・成形を一括処理します。

```bash
# 県コードを指定して実行 (OUTPUT_DIR/24 を自動走査)
transform-xml --analyze-pipeline 24

# ディレクトリパスを直接指定して実行
transform-xml --analyze-pipeline C:\transfer-xml\24

# スクリプト直接実行 (Claude API を指定する例)
python src/transform_xml/analyze_pipeline.py 24 --ocr-engine claude
```

#### (3) 全処理通し実行 (`--all` / #1〜#5 全工程一括実行)

サイト巡回から最終XML成形まで全工程を一気通貫で実行します。

```bash
transform-xml --all 24
```

---

### 4.2 個別PG実行

各工程を単独で実行・検証したい場合は、以下のコマンドを使用します。

#### #1 サイト巡回PG (`site_crawler`)
地方公共団体コード県を指定し、PDFリンクを巡回収集して `pdf_links.csv` を作成します。
```bash
transform-xml --crawl 24
# スクリプト直接実行
python src/transform_xml/site_crawler.py 24
```

#### #2 PDF取得PG (`pdf_downloader`)
`pdf_links.csv` を含むディレクトリを走査し、PDFをダウンロード保存します。
```bash
transform-xml --fetch-pdfs C:\transfer-xml\24
# スクリプト直接実行
python src/transform_xml/pdf_downloader.py C:\transfer-xml\24 --sleep 0.5
```

#### #3 PDF画像変換PG (`pdf_image_converter`)
ディレクトリ内のPDFを走査し、各ページを画像（PNG等）に変換します。
```bash
transform-xml --convert-pdfs C:\transfer-xml\24
# スクリプト直接実行 (解像度300 DPI、JPEG形式の例)
python src/transform_xml/pdf_image_converter.py C:\transfer-xml\24 --dpi 300 --format JPEG
```

#### #4 画像XML部分変換PG (`image_xml_converter`)
変換画像からOCRで様式番号・枝番を判別し、部分XMLを作成します。
```bash
# ローカルOCR (Tesseract) または settings.env の設定を使用
transform-xml --convert-images-to-xml C:\transfer-xml\24

# Claude API を明示指定して実行
transform-xml --convert-images-to-xml C:\transfer-xml\24 --ocr-engine claude
```

#### #5 XML部分統合PG (`xml_integrator`)
各ページの部分XMLを `SYUUSI_least.xml` テンプレートに統合し、提出用XMLを成形します。
```bash
transform-xml --integrate-xml C:\transfer-xml\24
# スクリプト直接実行
python src/transform_xml/xml_integrator.py C:\transfer-xml\24
```

---

## 5. 設定ファイル仕様 (`config/settings.env`)

各種コマンド引数のデフォルト値は、すべて `config/settings.env` に集約されています。

```env
# 成果物保存先ベースディレクトリ
OUTPUT_DIR=C:\transfer-xml

# Claude API設定 (方式Aを利用する場合)
CLAUDE_API_KEY=your_claude_api_key_here
CLAUDE_MODEL=claude-haiku-4-5-20251001

# デフォルトOCRエンジン (local: Tesseract, claude: Claude Vision API)
OCR_ENGINE=local

# ====================================================
# 各PG実行時引数の初期値設定 (コマンドライン引数で上書き可能)
# ====================================================

# 共通スリープ待機秒数 (--sleep のデフォルト)
SLEEP_SEC=1.0

# #1 サイト巡回PG
CRAWLER_SLEEP_SEC=1.0
MAX_CRAWL_DEPTH=7
CRAWLER_CONFIG_PATH=config/site_crawler_config.json

# #2 PDF取得PG
DOWNLOAD_SLEEP_SEC=1.0
TIMEOUT_SEC=15.0

# #3 PDF画像変換PG
PDF_IMAGE_DPI=200
PDF_IMAGE_FORMAT=PNG

# #5 XML部分統合PG
TEMPLATE_DIR=config/template
```

---

## 6. Claude Vision API の設定と疎通確認

**OSにTesseractをインストールせず、高精度なAI解析を利用したい場合の手順です。**

1. [Anthropic Console](https://console.anthropic.com/) にてアカウントを作成し、APIキー（`sk-ant-...`）を発行します。
2. `config/settings.env` に以下を設定します。
   ```env
   CLAUDE_API_KEY=sk-ant-api03-...
   OCR_ENGINE=claude
   CLAUDE_MODEL=claude-haiku-4-5-20251001
   ```
3. **疎通確認ツールの実行**:
   APIキーが有効か、モデルと通信できるかを単独検証スクリプトで即座にテストできます。
   ```bash
   # 基本疎通確認 (settings.env から自動読み込み)
   python verify_claude_api.py

   # 利用可能なモデル一覧の確認 (404エラー対策)
   python verify_claude_api.py --list-models
   ```

---

## 7. Tesseract OCR のセットアップ (ローカルOCR選択時のみ)

**完全オフライン・AI不使用でローカル処理を行いたい場合のみ、以下のOS別手順を実施してください。**  
（※ Claude API 方式を利用する場合は本手順は不要です。）

### 7.1 OS別インストール手順

#### Windows
1. [UB-Mannheim/tesseract (GitHub Wiki)](https://github.com/UB-Mannheim/tesseract/wiki) よりインストーラ（`tesseract-ocr-w64-setup-*.exe`）をダウンロードして実行します。
2. コンポーネント選択画面で以下にチェックを入れます：
   - `Additional script data` $\rightarrow$ **Japanese script**
   - `Additional language data` $\rightarrow$ **Japanese (`jpn`)**
3. インストール先（例: `C:\Program Files\Tesseract-OCR`）をシステムの環境変数 `PATH` に追加します。

#### macOS
```bash
brew install tesseract tesseract-lang
```

#### Linux (Ubuntu / Debian)
```bash
sudo apt-get update
sudo apt-get install -y tesseract-ocr tesseract-ocr-jpn
```

### 7.2 インストール確認
```bash
# バージョン確認
tesseract --version

# 日本語言語データ (jpn) の確認 ("jpn" が含まれていれば準備完了)
tesseract --list-langs
```

---

## 8. テスト実行

```bash
# 全単体テストの実行 (unittest)
python -m unittest discover -s tests -v

# 連続実行パイプラインのテスト
python -m unittest tests/test_pipeline.py -v

# 設定ローダー・引数集約のテスト
python -m unittest tests/test_config.py -v

# 各機能の個別テスト
python -m unittest tests/test_site_crawler.py -v
python -m unittest tests/test_pdf_downloader.py -v
python -m unittest tests/test_pdf_image_converter.py -v
python -m unittest tests/test_image_xml_converter.py -v
python -m unittest tests/test_xml_integrator.py -v
```

---

## 9. ディレクトリ構成 (src-layout)

```text
transform-xml/
├── config/
│   ├── settings.env.example     # 全体設定環境変数サンプル
│   ├── site_crawler_config.json # サイト巡回設定
│   └── template/                # XML成形用テンプレート
│       ├── SYUUSI_least.xml     # 基本骨格XML
│       └── blank/               # 各様式・枝番ブランクXML (01〜49)
├── src/
│   └── transform_xml/
│       ├── __init__.py          # パッケージ定義
│       ├── __main__.py          # モジュール直接実行エントリポイント
│       ├── main.py              # メイン処理 (CLIディスパッチャ & 全処理通し実行)
│       ├── config.py            # 共通設定・環境変数ローダー
│       ├── fetch_pipeline.py    # 連続実行取得PG (#1, #2, #3)
│       ├── analyze_pipeline.py  # 連続実行解析PG (#4, #5)
│       ├── site_crawler.py      # #1 サイト巡回PG
│       ├── pdf_downloader.py    # #2 PDF取得PG
│       ├── pdf_image_converter.py # #3 PDF画像変換PG
│       ├── image_xml_converter.py # #4 画像XML部分変換PG
│       └── xml_integrator.py    # #5 XML部分統合PG
├── tests/
│   ├── fixtures/                # テストフィクスチャ (24〜27, 27_ans, tmp_ans)
│   ├── test_main.py             # メイン処理テスト
│   ├── test_config.py           # 設定ローダー統合テスト
│   ├── test_pipeline.py         # 連続実行パイプラインテスト
│   ├── test_site_crawler.py     # サイト巡回テスト
│   ├── test_pdf_downloader.py   # PDF取得テスト
│   ├── test_pdf_image_converter.py # PDF画像変換テスト
│   ├── test_image_xml_converter.py # 画像XML部分変換テスト
│   └── test_xml_integrator.py   # XML部分統合テスト
├── verify_claude_api.py         # Claude API 疎通確認用単独検証PG
├── pyproject.toml               # プロジェクト設定 (PEP 517/621準拠)
└── README.md
```
