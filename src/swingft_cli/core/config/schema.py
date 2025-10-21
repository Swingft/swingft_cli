from __future__ import annotations

import json
import os
import sys
from typing import Any, Dict, Iterable, List

MAX_CONFIG_BYTES = 5 * 1024 * 1024
ALLOWED_TOP_KEYS = {"project", "options", "exclude", "include", "preflight"}
ALLOWED_SUB_KEYS = {"obfuscation", "encryption"}

EXCLUDED_DIRS = {
    ".git", ".github", ".idea", ".vscode", "DerivedData", ".build", "build",
    ".swiftpm", "Packages", "Package.resolved", "Carthage", "Pods",
    "Documentation", "docs", "node_modules"
}

def _warn(msg: str) -> None:
    print(f"경고: {msg}", file=sys.stderr)

def _print_json_error_and_exit(path: str, err: json.JSONDecodeError) -> None:
    print(f"JSON 파싱 오류: {path}:{err.lineno}:{err.colno}: {err.msg}", file=sys.stderr)
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            lines = f.read().splitlines()
        idx = err.lineno - 1
        if 0 <= idx < len(lines):
            line = lines[idx]
            pointer = " " * (max(err.colno - 1, 0)) + "^"
            print(line, file=sys.stderr)
            print(pointer, file=sys.stderr)
    except Exception:
        pass
    sys.exit(1)

def _expand_abs_norm(p: str) -> str:
    try:
        return os.path.abspath(os.path.expanduser(p))
    except Exception:
        return p

def _dedupe_keep_order(items: Iterable[str]) -> List[str]:
    seen = set()
    out: List[str] = []
    for v in items:
        if v not in seen:
            seen.add(v)
            out.append(v)
    return out

def _ensure_str_list(container: Dict[str, Any], key_path: str) -> List[str]:
    cur: Any = container
    for part in key_path.split("."):
        if not isinstance(cur, dict) or part not in cur:
            return []
        cur = cur[part]
    if cur is None:
        return []
    if isinstance(cur, str):
        vals = [cur]
    elif isinstance(cur, list):
        vals = cur
    else:
        _warn(f"{key_path} 는 배열(또는 문자열)이어야 합니다. 현재 타입: {type(cur).__name__}. 무시합니다.")
        return []
    cleaned: List[str] = []
    for idx, v in enumerate(vals):
        if isinstance(v, str):
            s = v.strip()
            if s == "":
                _warn(f"{key_path}[{idx}] 가 빈 문자열입니다. 무시합니다.")
                continue
            cleaned.append(s)
        else:
            _warn(f"{key_path}[{idx}] 타입이 문자열이 아닙니다({type(v).__name__}). 무시합니다.")
    return _dedupe_keep_order(cleaned)




