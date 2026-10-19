"""Claude API 疎通確認用単独検証プログラム.

環境変数 (ANTHROPIC_API_KEY / CLAUDE_API_KEY) または config/settings.env
からAPIキーを読み込み、Claude API との疎通およびモデルの応答を検証します。
"""

import argparse
import os
import sys
from pathlib import Path


def load_env_file(env_path: Path) -> dict[str, str]:
    """settings.env 形式のファイルを読み込む."""
    env_vars: dict[str, str] = {}
    if not env_path.exists():
        return env_vars
    try:
        with open(env_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                if "=" in line:
                    key, val = line.split("=", 1)
                    env_vars[key.strip()] = val.strip().strip("\"'")
    except Exception:
        pass
    return env_vars


def get_api_key_and_model(
    arg_api_key: str | None = None,
    arg_model: str | None = None,
    env_file_path: str = "config/settings.env",
) -> tuple[str, str]:
    """APIキーとモデル名を取得する."""
    env_vars = load_env_file(Path(env_file_path))

    # APIキーの優先順位:
    # 1. コマンドライン引数
    # 2. 環境変数 ANTHROPIC_API_KEY
    # 3. 環境変数 CLAUDE_API_KEY
    # 4. settings.env の ANTHROPIC_API_KEY
    # 5. settings.env の CLAUDE_API_KEY
    api_key = (
        arg_api_key
        or os.environ.get("ANTHROPIC_API_KEY")
        or os.environ.get("CLAUDE_API_KEY")
        or env_vars.get("ANTHROPIC_API_KEY")
        or env_vars.get("CLAUDE_API_KEY")
        or ""
    )

    # モデル名の優先順位:
    # 1. コマンドライン引数
    # 2. 環境変数 CLAUDE_MODEL / ANTHROPIC_MODEL
    # 3. settings.env の CLAUDE_MODEL / ANTHROPIC_MODEL
    # 4. デフォルト (claude-haiku-4-5-20251001)
    model = (
        arg_model
        or os.environ.get("CLAUDE_MODEL")
        or os.environ.get("ANTHROPIC_MODEL")
        or env_vars.get("CLAUDE_MODEL")
        or env_vars.get("ANTHROPIC_MODEL")
        or "claude-haiku-4-5-20251001"
    )

    return api_key, model


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Claude API 疎通確認用単独検証プログラム"
    )
    parser.add_argument(
        "--api-key",
        default=None,
        help="Claude APIキー (未指定時は環境変数または config/settings.env から取得)",
    )
    parser.add_argument(
        "--model",
        default=None,
        help="検証に使用するモデル名 (未指定時は settings.env またはデフォルト: claude-haiku-4-5-20251001)",
    )
    parser.add_argument(
        "--env-file",
        default="config/settings.env",
        help="設定ファイルのパス (デフォルト: config/settings.env)",
    )
    parser.add_argument(
        "--list-models",
        action="store_true",
        help="利用可能なモデル一覧を取得して表示します",
    )
    args = parser.parse_args()

    try:
        import anthropic
    except ImportError:
        print("[エラー] anthropic ライブラリがインストールされていません。")
        print("以下のコマンドでインストールしてください:")
        print("    pip install anthropic")
        return 1

    api_key, model = get_api_key_and_model(args.api_key, args.model, args.env_file)

    if not api_key:
        print("[エラー] APIキーが見つかりません。")
        print("以下のいずれかの方法でAPIキーを設定してください:")
        print("  1. config/settings.env に CLAUDE_API_KEY=your_key を設定")
        print("  2. 環境変数 ANTHROPIC_API_KEY または CLAUDE_API_KEY を設定")
        print("  3. コマンドライン引数 --api-key <KEY> を指定")
        return 1

    # キーの先頭・末尾のみ表示（安全のため完全なキーは隠蔽）
    masked_key = (
        f"{api_key[:7]}...{api_key[-4:]}" if len(api_key) > 15 else "*** (short)"
    )
    print(f"APIキーを確認しました: {masked_key} (長さ: {len(api_key)})")

    client = anthropic.Anthropic(api_key=api_key)

    # モデル一覧表示モード
    if args.list_models:
        print("\n--- 利用可能なモデル一覧を取得中 ---")
        try:
            models_resp = client.models.list()
            print(f"取得成功 (計 {len(models_resp.data)} 件):")
            for m in models_resp.data:
                print(f"  - {m.id}")
            return 0
        except Exception as e:
            print(f"[エラー] モデル一覧の取得に失敗しました: {e}")
            return 1

    # メッセージ送信による疎通検証
    print(f"\n--- Claude API 疎通テスト開始 (モデル: {model}) ---")
    try:
        response = client.messages.create(
            model=model,
            max_tokens=50,
            messages=[
                {"role": "user", "content": "Hello, Claude! Please reply with 'OK'."}
            ],
        )
        print("疎通成功！ レスポンス:")
        reply_text = "".join(
            block.text for block in response.content if hasattr(block, "text")
        )
        print(reply_text)
        print("\n[OK] APIキーおよび指定モデルとの通信は正常です。")
        return 0

    except anthropic.AuthenticationError:
        print("\n[認証エラー] APIキーが無効であるか、正しく設定されていません。")
        print("APIキーが正しいか、Anthropic Console で確認してください。")
        return 1

    except anthropic.NotFoundError as e:
        print(f"\n[404 Not Found エラー] 指定されたモデル '{model}' が見つかりません。")
        print(f"詳細: {e}")
        print("\n旧世代のモデル (例: claude-3-5-sonnet-20241022 や claude-3-7-sonnet-20250219) は")
        print("提供終了または名称変更されている可能性があります。")
        print("以下のコマンドで現在利用可能なモデル一覧を確認できます:")
        print("    python verify_claude_api.py --list-models")
        return 1

    except anthropic.APIError as e:
        print(f"\n[APIエラー] APIエラーが発生しました (status={getattr(e, 'status_code', None)}): {e}")
        return 1

    except Exception as e:
        print(f"\n[予期せぬエラー] 予期せぬエラーが発生しました: {e}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
