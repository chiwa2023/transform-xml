# transform-xml

XMLの変換・処理を行うためのPythonプロジェクトです。

## ディレクトリ構成 (src-layout)

```text
transform-xml/
├── .vscode/
│   ├── extensions.json       # 推奨拡張機能
│   └── settings.json         # VS Code用テスト・Python設定
├── src/
│   └── transform_xml/
│       ├── __init__.py       # パッケージ定義
│       ├── __main__.py       # モジュール直接実行エントリポイント
│       └── main.py           # メイン処理 (hello_world, main)
├── tests/
│   ├── __init__.py
│   └── test_main.py          # 単体テスト (unittest)
├── .gitignore
├── LICENSE
├── pyproject.toml            # プロジェクト設定 (PEP 517/621準拠)
└── README.md
```

## 動作確認・実行方法

### 1. VS Code 上での実行
- **テスト実行**:
  - `test_main.py` を右クリック ➔ **「Run Tests」**
  - またはエディタ内のテスト関数横の **▶ (再生ボタン)** をクリック
  - サイドバーの **Testing (ビーカーアイコン)** から実行
- **直接実行**:
  - `src/transform_xml/main.py` または `tests/test_main.py` を右クリック ➔ **「Run Python File in Terminal」**

### 2. コマンドラインでのテスト実行

```bash
# 環境変数の事前指定なしでそのまま実行可能
python -m unittest discover -s tests -v
```

### 3. モジュール実行 (Hello World)

```bash
# PowerShell
$env:PYTHONPATH="src"; python -m transform_xml

# Bash / Linux / macOS
PYTHONPATH=src python -m transform_xml
```

### 4. パッケージのインストール (編集可能モード)

```bash
pip install -e .
# インストール後は直接CLIコマンドとして実行可能
transform-xml
```
