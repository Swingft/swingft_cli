import os
import plistlib
import re
from typing import Tuple
# plist 파일 텍스트 읽기
def read_plist_as_text(plist_path: str) -> str:
    with open(plist_path, 'rb') as f:
        try:
            data = plistlib.load(f)
            return str(data)
        except Exception:
            f.seek(0)
            return f.read().decode('utf-8', errors='replace')
# 파일 텍스트 읽기
def read_text_fallback(path: str) -> Tuple[str | bytes, str]:
    """Read a file as text; if fails, return bytes. Returns (content, mode)."""
    try:
        with open(path, 'r', encoding='utf-8', errors='replace') as f:
            return f.read(), 'w'
    except Exception:
        with open(path, 'rb') as f:
            return f.read(), 'wb'
# 관련 파일 경로 평탄화
def flatten_relpath_for_sidecar(rel_path: str) -> str:
    return re.sub(r'[\\/]', '_', rel_path) + '.txt'




