# transform-xml

XMLの変換・処理を行うためのPythonプロジェクトです。

## 1. ディレクトリ構成 (src-layout)

```text
transform-xml/
├── .vscode/
│   ├── extensions.json       # 推奨拡張機能
│   └── settings.json         # VS Code用テスト・Python設定
├── config/
│   ├── settings.env.example  # 全体設定環境変数サンプル
│   └── site_crawler_config.json # サイト巡回設定
├── src/
│   └── transform_xml/
│       ├── __init__.py       # パッケージ定義
│       ├── __main__.py       # モジュール直接実行エントリポイント
│       ├── main.py           # メイン処理 (CLIディスパッチャ)
│       ├── site_crawler.py   # #1 サイト巡回PG
│       ├── pdf_downloader.py # #2 PDF取得PG
│       ├── pdf_image_converter.py # #3 PDF画像変換PG
│       └── image_xml_converter.py # #4 画像XML部分変換PG
├── tests/
│   ├── fixtures/             # テストデータ (フィクスチャ)
│   │   ├── 24/               # 都道府県別テストデータサンプル (PDFダウンロード用)
│   │   ├── 25/               # 都道府県別テストデータサンプル (PDF画像変換用)
│   │   ├── 26/               # 都道府県別テストデータサンプル (画像XML部分変換用)
│   │   └── tmp_ans/          # XML変換の期待値・定数設計書
│   ├── __init__.py
│   ├── test_main.py          # メイン処理テスト
│   ├── test_site_crawler.py  # サイト巡回テスト
│   ├── test_pdf_downloader.py# PDF取得テスト
│   ├── test_pdf_image_converter.py # PDF画像変換テスト
│   └── test_image_xml_converter.py # 画像XML部分変換テスト
├── .gitignore
├── LICENSE
├── verify_claude_api.py      # Claude API 疎通確認用単独検証PG
├── pyproject.toml            # プロジェクト設定 (PEP 517/621準拠)
└── README.md
```

## 2. 各機能の実行コマンド

### 2.1. #2 PDF取得PG (`pdf_downloader`)

指定されたディレクトリおよび全下位ディレクトリ内の `pdf_links.csv` を再帰的に探索し、記載されたURLからPDFをダウンロードしてリンクラベル名で保存します。

#### 2.1.1 スクリプト直接実行

```bash
# 基本実行 (保存作業ごとにデフォルト1秒スリープ)
python src/transform_xml/pdf_downloader.py <対象ディレクトリ>

# 例: tests/fixtures/24 を対象に実行
python src/transform_xml/pdf_downloader.py tests/fixtures/24

# オプション指定例 (待機時間0.5秒、タイムアウト10秒)
python src/transform_xml/pdf_downloader.py C:\transfer-xml\24 --sleep 0.5 --timeout 10.0
```

#### 2.1.2 `main.py` 経由の実行

```bash
python src/transform_xml/main.py --fetch-pdfs <対象ディレクトリ>
```

#### 2.1.3 モジュール実行 (`python -m`) または CLI

```bash
# PowerShell
$env:PYTHONPATH="src"; python -m transform_xml.pdf_downloader <対象ディレクトリ>

# Bash / Linux / macOS
PYTHONPATH=src python -m transform_xml.pdf_downloader <対象ディレクトリ>

# パッケージインストール後 (pip install -e .)
transform-xml --fetch-pdfs <対象ディレクトリ>
```

#### 2.1.4 オプション一覧

| 引数 / オプション |                      説明                      | デフォルト値 |
| :---------------- | :--------------------------------------------- | :----------- |
| `target_dir`      | `pdf_links.csv` を含む対象ディレクトリ（必須） | -            |
| `--sleep`         | 各PDF保存完了後のアクセス待機間隔（秒）        | `1.0`        |
| `--timeout`       | HTTPリクエストのタイムアウト（秒）             | `15.0`       |

---

### 3.1 #1 サイト巡回PG (`site_crawler`)

指定された地方公共団体コード県（00〜47）に基づいて対象ページを巡回し、PDFリンクおよびページ階層を保存します。

```bash
# スクリプト直接実行 (例: 24 三重県)
python src/transform_xml/site_crawler.py 24

# main.py 経由の実行
python src/transform_xml/main.py --crawl 24
```

---

### 4.1 #3 PDF画像変換PG (`pdf_image_converter`)

指定されたディレクトリおよび全下位ディレクトリ内のPDFファイルを再帰的に探索し、各PDFにつき1つの下位ディレクトリを作成して1ページを1画像（デフォルトPNG、200 DPI）に変換・保存します。また、作業ログ（テキスト `image_convert.log` および JSON `image_convert.json`）を同下位ディレクトリに出力します。

#### 4.1.1 スクリプト直接実行

```bash
# 基本実行 (デフォルト: 200 DPI, PNG形式)
python src/transform_xml/pdf_image_converter.py <対象ディレクトリ>

# 例: tests/fixtures/25 を対象に実行
python src/transform_xml/pdf_image_converter.py tests/fixtures/25

# オプション指定例 (解像度300 DPI、JPEG形式)
python src/transform_xml/pdf_image_converter.py C:\transfer-xml\24 --dpi 300 --format JPEG
```

#### 4.1.2 `main.py` 経由の実行

```bash
python src/transform_xml/main.py --convert-pdfs <対象ディレクトリ>
```

#### 4.1.3 モジュール実行 (`python -m`) または CLI

```bash
# PowerShell
$env:PYTHONPATH="src"; python -m transform_xml.pdf_image_converter <対象ディレクトリ>

# Bash / Linux / macOS
PYTHONPATH=src python -m transform_xml.pdf_image_converter <対象ディレクトリ>

# パッケージインストール後 (pip install -e .)
transform-xml --convert-pdfs <対象ディレクトリ>
```

#### 4.1.4 オプション一覧

| 引数 / オプション |                    説明                     | デフォルト値 |
| :---------------- | :------------------------------------------ | :----------- |
| `target_dir`      | 変換対象のPDFを含むディレクトリ（必須）     | -            |
| `--dpi`           | 画像解像度 DPI                              | `200`        |
| `--format`        | 出力画像フォーマット (`PNG`, `JPEG`, `JPG`) | `PNG`        |

---

### 5. #4 画像XML部分変換PG (`image_xml_converter`)

指定されたディレクトリの下位ディレクトリから画像変換ログ（`image_convert.log` / `image_convert.json`）が存在し、XML変換ログ（`xml_convert.log` / `xml_convert.json`）が存在しないディレクトリを抽出し、画像をページ順にOCR処理して様式番号・様式番号枝番を判定し、対応する部分XML（`{pdfファイル名}_{総ページ番号}.xml`）に変換・保存します。また、作業ログ（テキスト `xml_convert.log` および JSON `xml_convert.json`）を出力します。

#### 5.1.1 スクリプト直接実行

```bash
# 基本実行 (ローカルOCRまたはsettings.envの設定を使用)
python src/transform_xml/image_xml_converter.py <対象ディレクトリ>

# 例: tests/fixtures/26/（令和７年分） を対象に実行
python src/transform_xml/image_xml_converter.py "tests/fixtures/26/（令和７年分）"

# Claude API を使用した実行例
python src/transform_xml/image_xml_converter.py "tests/fixtures/26/tmp" --ocr-engine claude --api-key <CLAUDE_API_KEY>
```

#### 5.1.2 `main.py` 経由の実行

```bash
python src/transform_xml/main.py --convert-images-to-xml <対象ディレクトリ>
# または
python src/transform_xml/main.py --images-to-xml <対象ディレクトリ>
```

#### 5.1.3 モジュール実行 (`python -m`) または CLI

```bash
# PowerShell
$env:PYTHONPATH="src"; python -m transform_xml.image_xml_converter <対象ディレクトリ>

# パッケージインストール後 (pip install -e .)
transform-xml --convert-images-to-xml <対象ディレクトリ>
```

#### 5.1.4 オプション一覧

| 引数 / オプション |                      説明                       |            デフォルト値             |
| :---------------- | :---------------------------------------------- | :---------------------------------- |
| `target_dir`      | 画像変換ログが存在するディレクトリ（必須）      | -                                   |
| `--ocr-engine`    | 使用するOCRエンジン (`claude`, `local`, `mock`) | `settings.env` の指定または `local` |
| `--api-key`       | Claude APIキー                                  | `CLAUDE_API_KEY` 環境変数           |
| `--model`         | Claude Vision モデル名                          | `claude-3-5-sonnet-20241022`        |
| `--env-file`      | 全体設定ファイルパス                            | `config/settings.env` または `.env` |

---

## 6. テスト実行

```bash
# 全テストの実行 (unittest)
python -m unittest discover -s tests -v

# 画像XML部分変換機能のテストのみ実行
python -m unittest tests/test_image_xml_converter.py -v

# PDF取得機能のテストのみ実行
python -m unittest tests/test_pdf_downloader.py -v

# メイン処理テストの実行
python -m unittest tests/test_main.py -v
```

## 7. パッケージのインストール (編集可能モード)

```bash
pip install -e .

# インストール後は transform-xml コマンドが利用可能
transform-xml              # Hello, World!
transform-xml --crawl <地方公共団体コード県>
transform-xml --fetch-pdfs <対象ディレクトリ>
transform-xml --convert-pdfs <対象ディレクトリ>
transform-xml --convert-images-to-xml <対象ディレクトリ>
```

## 8. OCRエンジン

本プロジェクトの画像XML変換（`image_xml_converter`）では、環境や目的に応じて **AI不使用（Tesseract OCR）** と **AI使用（Claude Vision API）** の2種類のOCRエンジンを利用できます。

- コマンドライン引数 `--ocr-engine local` または `--ocr-engine claude` で明示的に切り替え可能です。
- 未指定の場合は `config/settings.env` の `OCR_ENGINE` 設定、またはAPIキーの設定状況に基づき自動判定されます。

---

### 8.1 AI不使用 (Tesseract OCR)

ローカル環境で動作するオープンソースのOCRエンジンです。Pythonライブラリ `pytesseract` および Tesseract OCR 本体を使用します。

#### 8.1.1. Pythonパッケージのインストール

PythonからTesseractを呼び出すためのラッパーライブラリをインストールします。

```bash
pip install pytesseract
```

> **Note**: 画像処理に必要な `Pillow` は本パッケージの通常依存関係に含まれているため、`pip install -e .` 実行時に自動的にインストールされます。

#### 8.1.2. Tesseract OCR 本体のインストール

政治資金収支報告書（日本語文書）の読み取りには、**Tesseract本体** に加えて **日本語学習済みデータ (`jpn`)** が必須となります。ご利用のOSに合わせてインストールしてください。

##### 8.1.2.1 Windows

1. [UB-Mannheim/tesseract (GitHub Wiki)](https://github.com/UB-Mannheim/tesseract/wiki) 等からインストーラ（`tesseract-ocr-w64-setup-*.exe`）をダウンロードして実行します。
2. インストールウィザードのコンポーネント選択（Choose Components）画面で、以下にチェックを入れます。
   - `Additional script data` → **Japanese script**
   - `Additional language data` → **Japanese** (`jpn`)
3. インストール完了後、インストール先ディレクトリ（デフォルト: `C:\Program Files\Tesseract-OCR`）をシステムの環境変数 `PATH` に追加します。
   - 参考: Qiita記事 [Tesseractを利用したPythonによるOCR処理](https://qiita.com/saurus12/items/3e365ecf1a2e99f869e3)

##### 8.1.2.2 macOS

Homebrew を使用して本体と日本語言語パックをインストールします。

```bash
brew install tesseract tesseract-lang
```

##### 8.1.2.3 Linux (Ubuntu / Debian)

APT パッケージマネージャを使用して本体と日本語言語パックをインストールします。

```bash
sudo apt-get update
sudo apt-get install -y tesseract-ocr tesseract-ocr-jpn
```

#### 8.1.3. インストールと日本語データの確認

ターミナルまたはPowerShellで以下を実行し、バージョンおよび対応言語に `jpn` が含まれていることを確認します。

```bash
# バージョン確認
tesseract --version

# インストール済み言語一覧の確認 ("jpn" が表示されれば利用可能)
tesseract --list-langs
```

> **フォールバック設計について**:
> Tesseract 本体や `pytesseract` が未インストールの環境であっても、プログラムはエラー中断せず安全に空のXMLスケルトンを生成して処理を継続するフォールバック設計（仕様 `#4-i`）となっています。

---

### 8.2 AI使用 (Claude Vision API)

Anthropic社の Claude Vision API を活用して高精度に様式番号・枝番の判定およびXML構造の抽出を行います。

#### 8.2.1. Pythonパッケージのインストール

Claude APIとの通信および疎通検証を行うための公式SDKをインストールします。

```bash
pip install anthropic
```

#### 8.2.2. インストールとバージョンの確認

ターミナルまたはPowerShellで以下を実行し、ライブラリが正常にインストールされていることおよびバージョンを確認します。

```bash
python -c "import anthropic; print(anthropic.__version__)"
```

#### 8.2.3. 事前準備: APIキーの取得

事前に [Claude APIキーを取得する](https://platform.claude.com/docs/ja/get-api-key) または [Anthropic Console](https://console.anthropic.com/) にアクセスし、アカウント作成とAPIキー（`sk-ant-...`）の発行を行ってください。

#### 8.2.4. APIキーと設定の適用方法

以下のいずれかの方法で設定・指定が可能です。

##### 方法A: 設定ファイル (`config/settings.env`) に記述 (推奨)

`config/settings.env.example` を参考に `config/settings.env` を作成し、以下を設定します。

```env
# Claude APIキー
CLAUDE_API_KEY=your_claude_api_key_here

# デフォルトOCRエンジンにClaudeを指定する場合 (任意)
OCR_ENGINE=claude

# 使用モデル (例: claude-haiku-4-5-20251001, claude-sonnet-4-6 等)
CLAUDE_MODEL=claude-haiku-4-5-20251001
```

> **404 (Not Found) エラーについて**:
> Anthropic API では、旧世代のモデル（`claude-3-5-sonnet-20241022` や `claude-3-7-sonnet-20250219` など）が提供終了または未提供の場合、API呼び出し時に `404 status (NotFoundError)` が返されます。404エラーが発生した場合は、後述の `verify_claude_api.py --list-models` で現在利用可能なモデル名を確認し、`CLAUDE_MODEL` または `--model` に設定してください。

##### 8.3. 方法B: OSの環境変数に設定

```bash
# Linux / macOS (Bash / Zsh)
export CLAUDE_API_KEY="your_claude_api_key_here"

# Windows (PowerShell)
$env:CLAUDE_API_KEY="your_claude_api_key_here"
```

##### 8.2.4 方法C: コマンドライン引数で直接指定

コマンド実行時に `--api-key` 引数で直接渡すことも可能です。

#### 8.2.5. API疎通確認 (検証専用単独PG)

APIキーが正常に設定されているか、およびClaude APIと通信できるかを検証するための単独プログラム `verify_claude_api.py` が用意されています。

```bash
# 基本実行 (settings.env または環境変数からAPIキーを自動読み込みして疎通テスト)
python verify_claude_api.py

# 現在利用可能なモデル一覧の確認 (404エラー時の確認に便利です)
python verify_claude_api.py --list-models

# モデルを指定して疎通テスト
python verify_claude_api.py --model claude-haiku-4-5-20251001

# APIキーを直接指定してテスト
python verify_claude_api.py --api-key <CLAUDE_API_KEY>
```

#### 8.2.6. 実行コマンド例

```bash
# settings.env または環境変数にAPIキー設定済みの実行
python src/transform_xml/image_xml_converter.py <対象ディレクトリ> --ocr-engine claude

# モデルを明示指定して実行
python src/transform_xml/image_xml_converter.py <対象ディレクトリ> --ocr-engine claude --model claude-haiku-4-5-20251001

# APIキーを直接コマンドライン引数で指定して実行
python src/transform_xml/image_xml_converter.py <対象ディレクトリ> --ocr-engine claude --api-key <CLAUDE_API_KEY>

# main.py や CLI経由での実行
transform-xml --convert-images-to-xml <対象ディレクトリ> --ocr-engine claude
```
