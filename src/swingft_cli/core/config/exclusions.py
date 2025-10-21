from __future__ import annotations

import os
import json
from datetime import datetime
from typing import Any, Dict

def write_feedback_to_output(config: Dict[str, Any], filename: str, content: str) -> str | None:
    try:
        out_dir = str(config.get("project", {}).get("output") or "").strip()
        if not out_dir:
            return None
        base = os.path.join(out_dir, "Obfuscation_Report", "preflight")
        os.makedirs(base, exist_ok=True)
        ts = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
        path = os.path.join(base, f"{filename}_{ts}.txt")
        with open(path, "w", encoding="utf-8") as f:
            f.write(content)
        return path
    except Exception:
        return None

def ast_unwrap(node):
    try:
        if isinstance(node, dict) and isinstance(node.get("node"), dict):
            return node["node"]
    except Exception:
        pass
    return node
