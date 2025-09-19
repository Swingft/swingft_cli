from __future__ import annotations

import io
import json
import os
import sys
import shutil
from datetime import datetime
from typing import Any, Dict

from .schema import (
    MAX_CONFIG_BYTES,
    ALLOWED_TOP_KEYS,
    ALLOWED_SUB_KEYS,
    _warn,
    _print_json_error_and_exit,
    _ensure_str_list,
    _expand_abs_norm,
)

def _is_readable_file(path: str) -> bool:
    try:
        st = os.stat(path)
    except FileNotFoundError:
        print(f"Cannot find the config file: {path}", file=sys.stderr)
        return False
    except OSError as e:
        print(f"Cannot check the config file status: {path}: {e.__class__.__name__}: {e}", file=sys.stderr)
        return False

    if not os.path.isfile(path):
        print(f"The path is not a file: {path}", file=sys.stderr)
        return False
    if st.st_size <= 0:
        print(f"The config file is empty: {path}", file=sys.stderr)
        return False
    if st.st_size > MAX_CONFIG_BYTES:
        print(
            f"The config file is too large ({st.st_size} bytes > {MAX_CONFIG_BYTES} bytes): {path}",
            file=sys.stderr,
        )
        return False
    return True


def _handle_broken_config(config_path: str, error: json.JSONDecodeError) -> None:
    """깨진 config 파일 처리: 백업 생성 + 복구 가이드"""
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_path = f"{config_path}.broken_{timestamp}"
    
    try:
        # 깨진 파일 백업
        shutil.copy2(config_path, backup_path)
        print(f"\n[복구] 깨진 설정 파일을 백업했습니다: {backup_path}", file=sys.stderr)
    except Exception as e:
        print(f"[복구] 백업 생성 실패: {e}", file=sys.stderr)
    
    # 샘플 파일 생성
    sample_path = f"{config_path}.sample"
    try:
        _generate_sample_config(sample_path)
        print(f"[복구] 새 샘플 설정 파일을 생성했습니다: {sample_path}", file=sys.stderr)
    except Exception as e:
        print(f"[복구] 샘플 파일 생성 실패: {e}", file=sys.stderr)
    
    # 오류 정보 표시
    print(f"\n[JSON 오류] {config_path}:", file=sys.stderr)
    print(f"  - 위치: {error.lineno}번째 줄, {error.colno}번째 문자", file=sys.stderr)
    print(f"  - 내용: {error.msg}", file=sys.stderr)
    
    # 복구 가이드
    print(f"\n[복구 가이드]:", file=sys.stderr)
    print(f"1. 백업 파일 확인: {backup_path}", file=sys.stderr)
    print(f"2. 샘플 파일 참고: {sample_path}", file=sys.stderr)
    print(f"3. 수동 편집 후 재시도", file=sys.stderr)
    print(f"4. 또는 새로 시작: python -m swingft_cli.cli --json {config_path}", file=sys.stderr)


def _generate_sample_config(sample_path: str) -> None:
    """샘플 config 파일 생성"""
    sample_config = {
        "_comment_path": "Specify the absolute path to your project. The output path is optional.",
        "project": {
            "input": "/path/to/your/project",
            "output": "/path/to/output",
            "build_target": "YourProject"
        },
        "options": {
            "Obfuscation_classNames": True,
            "Obfuscation_methodNames": True,
            "Obfuscation_variableNames": True,
            "Obfuscation_controlFlow": True,
            "Delete_debug_symbols": True,
            "Encryption_strings": True
        },
        "_comment_exclude": "The following section is optional and can be customized as needed.",
        "exclude": {
            "obfuscation": [
                "exampleIdentifier1",
                "exampleIdentifier2"
            ],
            "encryption": [
                "API_KEY"
            ]
        },
        "_comment_include": "You can explicitly include items to always obfuscate/encrypt, regardless of global settings.",
        "include": {
            "obfuscation": [
                "exampleProperty",
                "exampleMethod"
            ],
            "encryption": [
                "sensitiveString"
            ]
        }
    }
    
    with open(sample_path, "w", encoding="utf-8") as f:
        json.dump(sample_config, f, ensure_ascii=False, indent=2)


def load_config_or_exit(path: str) -> Dict[str, Any]:
    if not _is_readable_file(path):
        sys.exit(1)

    try:
        with io.open(path, "r", encoding="utf-8-sig", errors="strict") as f:
            raw = f.read()
    except UnicodeDecodeError as e:
        print(
            f"문자 디코딩 오류: {path}: position={e.start}..{e.end}: {e.reason}",
            file=sys.stderr,
        )
        sys.exit(1)
    except OSError as e:
        print(f"설정 파일을 열 수 없습니다: {path}: {e.__class__.__name__}: {e}", file=sys.stderr)
        sys.exit(1)

    try:
        data = json.loads(raw)
    except json.JSONDecodeError as e:
        _handle_broken_config(path, e)
        sys.exit(1)

    if not isinstance(data, dict):
        print("설정 파일의 최상위 구조는 객체여야 합니다.", file=sys.stderr)
        sys.exit(1)

    # 알 수 없는 최상위 키 경고(언더스코어 시작 키는 주석으로 간주)
    unknown_top = {k for k in data.keys() if not k.startswith("_") and k not in ALLOWED_TOP_KEYS}
    if unknown_top:
        _warn(f"알 수 없는 최상위 키 감지: {', '.join(sorted(unknown_top))}")

    # 섹션 기본값 보정 및 타입 강제
    for sec in ("options", "exclude", "include"):
        val = data.get(sec)
        if val is None:
            data[sec] = {}
        elif not isinstance(val, dict):
            _warn(f"{sec} 섹션은 객체여야 합니다. 기본값 {{}} 로 대체합니다.")
            data[sec] = {}

    # project 섹션 검증(존재 시)
    proj = data.get("project")
    if proj is not None and not isinstance(proj, dict):
        _warn("project 섹션은 객체여야 합니다. 무시합니다.")
        data["project"] = {}

    # exclude/include 내부 키 처리
    for sec in ("exclude", "include"):
        sec_obj = data.get(sec, {})
        unknown_sub = set(sec_obj.keys()) - ALLOWED_SUB_KEYS
        if unknown_sub:
            _warn(f"{sec}.* 에 알 수 없는 키 감지: {', '.join(sorted(unknown_sub))}. 무시합니다.")
            for k in list(unknown_sub):
                del sec_obj[k]
        for key in ("obfuscation", "encryption"):
            key_path = f"{sec}.{key}"
            vals = _ensure_str_list(data, key_path)
            sec_obj[key] = vals

    # --- 환경변수 기반 project 경로 오버라이드 및 저장 옵션 ---
    try:
        override_in = os.environ.get("SWINGFT_PROJECT_INPUT")
        override_out = os.environ.get("SWINGFT_PROJECT_OUTPUT")
        write_back = str(os.environ.get("SWINGFT_WRITE_BACK", "")).strip().lower() in {"1", "true", "yes", "y"}

        if override_in or override_out:
            # project 섹션 보장
            proj = data.get("project")
            if not isinstance(proj, dict):
                proj = {}
                data["project"] = proj

            changed = False
            if override_in:
                new_in = _expand_abs_norm(override_in)
                proj["input"] = new_in
                changed = True
                if not os.path.isdir(new_in):
                    _warn(f"SWINGFT_PROJECT_INPUT 경로가 디렉터리가 아닙니다: {new_in} (계속 진행)")

            if override_out:
                new_out = _expand_abs_norm(override_out)
                proj["output"] = new_out
                changed = True

            if changed:
                print(
                    f"환경변수에 의해 project 경로가 업데이트되었습니다: input={proj.get('input', '')!s}, output={proj.get('output', '')!s}",
                    file=sys.stderr,
                )

            if write_back:
                try:
                    with io.open(path, "w", encoding="utf-8") as wf:
                        json.dump(data, wf, ensure_ascii=False, indent=2)
                except Exception as e:
                    _warn(f"구성 저장 실패: {e.__class__.__name__}: {e}")
    except Exception as e:
        _warn(f"환경변수 기반 project 경로 업데이트 처리 중 예외 발생: {e.__class__.__name__}: {e}")

    return data




