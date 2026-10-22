"""Configuration and environment variables loader for transform_xml."""

import os
from pathlib import Path

# デフォルトの候補設定ファイル一覧
DEFAULT_ENV_CANDIDATES = [
    Path("config") / "settings.env",
    Path(".env"),
    Path("config") / ".env",
]


def load_env_file(env_path: Path | str) -> dict[str, str]:
    """Parse a simple KEY=VALUE env file."""
    p = Path(env_path)
    if not p.is_file():
        return {}

    env_vars: dict[str, str] = {}
    with open(p, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if "=" in line:
                key, val = line.split("=", 1)
                env_vars[key.strip()] = val.strip().strip("'\"")
    return env_vars


def resolve_env_variable(
    var_name: str,
    *alt_keys: str,
    env_file_path: Path | str | None = None,
    default: str | None = None,
) -> str | None:
    """Resolve an environment variable from specified file, candidates, or os.environ.

    Checks keys in the order: var_name, then alt_keys.
    Source priority:
      1. Explicit env_file_path (if provided and exists)
      2. Default candidate files (config/settings.env, .env, config/.env)
      3. os.environ
      4. default value
    """
    keys = [var_name, *alt_keys]

    # 1. Specified env file
    if env_file_path:
        p = Path(env_file_path)
        if p.is_file():
            vars_dict = load_env_file(p)
            for k in keys:
                if k in vars_dict and vars_dict[k]:
                    return vars_dict[k]

    # 2. Candidate env files
    for cp in DEFAULT_ENV_CANDIDATES:
        if cp.is_file():
            vars_dict = load_env_file(cp)
            for k in keys:
                if k in vars_dict and vars_dict[k]:
                    return vars_dict[k]

    # 3. os.environ
    for k in keys:
        if k in os.environ and os.environ[k]:
            return os.environ[k]

    return default


def resolve_env_float(
    var_name: str,
    *alt_keys: str,
    env_file_path: Path | str | None = None,
    default: float,
) -> float:
    """Resolve a float environment variable with fallback."""
    val = resolve_env_variable(var_name, *alt_keys, env_file_path=env_file_path)
    if val is not None:
        try:
            return float(val)
        except ValueError:
            pass
    return default


def resolve_env_int(
    var_name: str,
    *alt_keys: str,
    env_file_path: Path | str | None = None,
    default: int,
) -> int:
    """Resolve an int environment variable with fallback."""
    val = resolve_env_variable(var_name, *alt_keys, env_file_path=env_file_path)
    if val is not None:
        try:
            return int(val)
        except ValueError:
            pass
    return default


def resolve_env_str(
    var_name: str,
    *alt_keys: str,
    env_file_path: Path | str | None = None,
    default: str,
) -> str:
    """Resolve a str environment variable with fallback."""
    val = resolve_env_variable(var_name, *alt_keys, env_file_path=env_file_path)
    return val if val is not None else default


def resolve_env_path(
    var_name: str,
    *alt_keys: str,
    env_file_path: Path | str | None = None,
    default: Path | str,
) -> Path:
    """Resolve a Path environment variable with fallback."""
    val = resolve_env_variable(var_name, *alt_keys, env_file_path=env_file_path)
    return Path(val) if val is not None else Path(default)


def find_env_file_in_argv(argv: list[str] | None = None) -> Path | None:
    """Helper to detect --env-file from argv before full argument parsing."""
    import sys

    args_list = sys.argv[1:] if argv is None else argv
    for i, a in enumerate(args_list):
        if a == "--env-file" and i + 1 < len(args_list):
            return Path(args_list[i + 1])
        if a.startswith("--env-file="):
            return Path(a.split("=", 1)[1])
    return None
