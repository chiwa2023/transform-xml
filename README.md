# transform-xml

XMLの変換・処理を行うためのPythonプロジェクトです。

## ディレクトリ構成 (src-layout)

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
│       └── pdf_downloader.py # #2 PDF取得PG
├── tests/
│   ├── fixtures/             # テストデータ (フィクスチャ)
│   │   └── 24/               # 都道府県別テストデータサンプル
│   ├── __init__.py
│   ├── test_main.py          # メイン処理テスト
│   ├── test_site_crawler.py  # サイト巡回テスト
│   └── test_pdf_downloader.py# PDF取得テスト
├── .gitignore
├── LICENSE
├── pyproject.toml            # プロジェクト設定 (PEP 517/621準拠)
└── README.md
```

## 各機能の実行コマンド

### 1. #2 PDF取得PG (`pdf_downloader`)
指定されたディレクトリおよび全下位ディレクトリ内の `pdf_links.csv` を再帰的に探索し、記載されたURLからPDFをダウンロードしてリンクラベル名で保存します。

#### スクリプト直接実行
```bash
# 基本実行 (保存作業ごとにデフォルト1秒スリープ)
python src/transform_xml/pdf_downloader.py <対象ディレクトリ>

# 例: tests/fixtures/24 を対象に実行
python src/transform_xml/pdf_downloader.py tests/fixtures/24

# オプション指定例 (待機時間0.5秒、タイムアウト10秒)
python src/transform_xml/pdf_downloader.py C:\transfer-xml\24 --sleep 0.5 --timeout 10.0
```

#### `main.py` 経由の実行
```bash
python src/transform_xml/main.py --fetch-pdfs <対象ディレクトリ>
```

#### モジュール実行 (`python -m`) または CLI
```bash
# PowerShell
$env:PYTHONPATH="src"; python -m transform_xml.pdf_downloader <対象ディレクトリ>

# Bash / Linux / macOS
PYTHONPATH=src python -m transform_xml.pdf_downloader <対象ディレクトリ>

# パッケージインストール後 (pip install -e .)
transform-xml --fetch-pdfs <対象ディレクトリ>
```

#### オプション一覧
| 引数 / オプション | 説明 | デフォルト値 |
| :--- | :--- | :--- |
| `target_dir` | `pdf_links.csv` を含む対象ディレクトリ（必須） | - |
| `--sleep` | 各PDF保存完了後のアクセス待機間隔（秒） | `1.0` |
| `--timeout` | HTTPリクエストのタイムアウト（秒） | `15.0` |

---

### 2. #1 サイト巡回PG (`site_crawler`)
指定された地方公共団体コード県（00〜47）に基づいて対象ページを巡回し、PDFリンクおよびページ階層を保存します。

```bash
# スクリプト直接実行 (例: 24 三重県)
python src/transform_xml/site_crawler.py 24

# main.py 経由の実行
python src/transform_xml/main.py --crawl 24
```

---

## テスト実行

```bash
# 全テストの実行 (unittest)
python -m unittest discover -s tests -v

# PDF取得機能のテストのみ実行
python -m unittest tests/test_pdf_downloader.py -v
```

## パッケージのインストール (編集可能モード)

```bash
pip install -e .

# インストール後は transform-xml コマンドが利用可能
transform-xml              # Hello, World!
transform-xml --fetch-pdfs <対象ディレクトリ>
transform-xml --crawl <地方公共団体コード県>
```
