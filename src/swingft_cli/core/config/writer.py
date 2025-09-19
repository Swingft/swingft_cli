from __future__ import annotations

import io
import json
from typing import Any, Dict
# 설정 파일 쓰기
def write_config(path: str, data: Dict[str, Any]) -> None:
    with io.open(path, "w", encoding="utf-8") as wf:
        json.dump(data, wf, ensure_ascii=False, indent=2)




