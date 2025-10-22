from __future__ import annotations

# --- Apply config.exclude.obfuscation directly to AST (no config writes) ---
from typing import Any as _Any, Dict as _Dict  # ensure types available for helper

def _apply_config_exclusions_to_ast(ast_file_path: str, config: _Dict[str, _Any]) -> int:
    """Set isException=1 in AST for names listed in config.exclude.obfuscation.
    - Expands wildcards against existing AST names.
    - Does not modify the config file.
    - Returns updated node count (duplicate names count multiple).
    """
    try:
        with open(ast_file_path, 'r', encoding='utf-8') as f:
            ast_list = json.load(f)
    except Exception:
        return 0

    CONTAINER_KEYS = ("G_members", "children", "members", "extension", "node")

    # collect names present in AST
    names_in_ast = set()
    def _collect(o):
        if isinstance(o, dict):
            cur = _ast_unwrap(o)
            if isinstance(cur, dict):
                nm = str(cur.get("A_name", "")).strip()
                if nm:
                    names_in_ast.add(nm)
                for k in CONTAINER_KEYS:
                    ch = cur.get(k)
                    if isinstance(ch, list):
                        for c in ch: _collect(c)
                    elif isinstance(ch, dict):
                        _collect(ch)
                if o is not cur:
                    for k in CONTAINER_KEYS:
                        if k == 'node':
                            continue
                        ch = o.get(k)
                        if isinstance(ch, list):
                            for c in ch: _collect(c)
                        elif isinstance(ch, dict):
                            _collect(ch)
                for v in cur.values():
                    _collect(v)
                if o is not cur:
                    for k,v in o.items():
                        if k not in CONTAINER_KEYS:
                            _collect(v)
            else:
                for v in o.values():
                    _collect(v)
        elif isinstance(o, list):
            for it in o: _collect(it)
    _collect(ast_list)

    # build targets from config (expand wildcards)
    import fnmatch
    targets = set()
    for s in (config.get("exclude", {}).get("obfuscation", []) or []):
        if not isinstance(s, str):
            continue
        s = s.strip()
        if not s:
            continue
        if any(ch in s for ch in "*?[]"):
            for nm in names_in_ast:
                if fnmatch.fnmatchcase(nm, s):
                    targets.add(nm)
        else:
            if s in names_in_ast:
                targets.add(s)

    if not targets:
        return 0

    # apply to AST
    try:
         _update_ast_node_exceptions(
             ast_file_path,
             sorted(list(targets)),
             is_exception=1,
             allowed_kinds=None,
             lock_children=False,
             quiet=not _preflight_verbose(),
             only_when_explicit_zero=True,
         )
    except Exception:
        return 0

    # recount updated nodes
    try:
        with open(ast_file_path, 'r', encoding='utf-8') as f:
            ast2 = json.load(f)
        cnt = 0
        def _count(o):
            nonlocal cnt
            if isinstance(o, dict):
                cur = _ast_unwrap(o)
                if isinstance(cur, dict):
                    nm = str(cur.get("A_name", "")).strip()
                    if nm in targets and int(cur.get("isException", 0)) == 1:
                        cnt += 1
                    for k in CONTAINER_KEYS:
                        ch = cur.get(k)
                        if isinstance(ch, list):
                            for c in ch: _count(c)
                        elif isinstance(ch, dict):
                            _count(ch)
                    if o is not cur:
                        for k in CONTAINER_KEYS:
                            if k == 'node':
                                continue
                            ch = o.get(k)
                            if isinstance(ch, list):
                                for c in ch: _count(c)
                            elif isinstance(ch, dict):
                                _count(ch)
                    for v in cur.values():
                        _count(v)
                    if o is not cur:
                        for k,v in o.items():
                            if k not in CONTAINER_KEYS:
                                _count(v)
                else:
                    for v in o.values():
                        _count(v)
            elif isinstance(o, list):
                for it in o: _count(it)
        _count(ast2)
        return cnt
    except Exception:
        return 0
 

import io
import json
import os
import sys
import shutil
import requests
from datetime import datetime

# --- Helper: write preflight feedback text into obfuscation target folder ---
from .exclusions import write_feedback_to_output as _write_feedback_to_output
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
import swingft_cli.core.config as _cfg
from .conflicts import check_exception_conflicts as _check_exception_conflicts_ref

def _has_ui_prompt() -> bool:
    try:
        return getattr(_cfg, "PROMPT_PROVIDER", None) is not None
    except Exception:
        return False

def _preflight_print(msg: str) -> None:
    """Print preflight messages only when no UI prompt provider is active."""
    if not _has_ui_prompt():
        print(msg)

def _preflight_verbose() -> bool:
    """Return True if verbose preflight logs should be emitted."""
    try:
        v = os.environ.get("SWINGFT_PREFLIGHT_VERBOSE", "")
        return str(v).strip().lower() in {"1", "true", "yes", "y", "on"}
    except Exception:
        return False

# --- External analyzer integration -----------------------------------------
from .exclusions import ast_unwrap as _ast_unwrap
from .ast_utils import update_ast_node_exceptions as _update_ast_node_exceptions
from .ast_utils import compare_exclusion_list_vs_ast as _compare_exclusion_list_vs_ast

# removed: compare_exclusion_list_vs_ast is now provided by ast_utils.compare_exclusion_list_vs_ast

def _apply_analyzer_exclusions_to_ast_and_config(
    analyzer_root: str,
    project_root: str | None,
    ast_file_path: str | None,
    config_path: str,
    config: Dict[str, Any],
) -> None:
    """Run external analyzer and reflect results into AST only (no config writes)."""
    try:
        if not project_root or not os.path.isdir(project_root):
            return
        if not analyzer_root or not os.path.isdir(analyzer_root):
            return

        # Run analyzer with live logs (stdout/stderr not captured)
        try:
            import subprocess
            run_cmd = os.environ.get("SWINGFT_ANALYZER_CMD", "").strip()
            if run_cmd:
                cmd = run_cmd.format(project=project_root, root=analyzer_root)
                #print(f"[preflight] analyzer run: {cmd}")
                subprocess.run(cmd, shell=True, cwd=analyzer_root)
            else:
                analyze_py = os.path.join(analyzer_root, "analyze.py")
                if os.path.isfile(analyze_py):
                    cmd_list = ["python3", "analyze.py", project_root]
                    #print(f"[preflight] analyzer run (default): {' '.join(cmd_list)}")
                    subprocess.run(cmd_list, cwd=analyzer_root)
        except Exception as e:
            print(f"[preflight] analyzer run warning: {e}")

        # Read exclusion list
        out_file = os.path.join(analyzer_root, "analysis_output", "exclusion_list.txt")
        if not os.path.isfile(out_file):
            return
        names: list[str] = []
        try:
            with open(out_file, "r", encoding="utf-8", errors="ignore") as f:
                for raw in f:
                    s = str(raw).strip()
                    if not s or s.startswith("#"):
                        continue
                    names.append(s)
        except Exception:
            return
        if not names:
            return

        # Detect AST path if not provided, then update isException=1 for listed names
        ast_path_eff = ast_file_path
        if not ast_path_eff or not os.path.isfile(ast_path_eff):
            candidates = [
                os.path.join(os.getcwd(), "Obfuscation_Pipeline", "AST", "output", "ast_node.json"),
                os.path.join(os.getcwd(), "AST", "output", "ast_node.json"),
            ]
            ast_path_eff = next((p for p in candidates if os.path.isfile(p)), None)

        if ast_path_eff and os.path.isfile(ast_path_eff):
            # Always print comparison summary (one/zero/missing) before applying
            zeros_est = None
            try:
                _comp = _compare_exclusion_list_vs_ast(analyzer_root, ast_path_eff)
                if isinstance(_comp, dict):
                    zeros_est = int(_comp.get("zero", 0))
            except Exception:
                zeros_est = None
            # 기본값: 적용(ON). 명시적으로 0/false/no/off일 때만 비적용.
            _flag_raw = str(os.environ.get("SWINGFT_APPLY_ANALYZER_TO_AST", "")).strip().lower()
            apply_flag = _flag_raw not in {"0", "false", "no", "n", "off"}
            if apply_flag:
                try:
                    if zeros_est is not None:
                        #print(f"[preflight] analyzer → AST 적용: ≈{zeros_est} identifiers (explicit 0→1, apply=ON)")
                        pass
                    else:
                        #print(f"[preflight] analyzer → AST 적용: identifiers (explicit 0→1, apply=ON)")
                        pass
                    _update_ast_node_exceptions(
                        ast_path_eff,
                        names,
                        is_exception=1,
                        allowed_kinds=None,
                        lock_children=False,
                        quiet=False,
                        only_when_explicit_zero=True,
                    )
                except Exception as e:
                    print(f"[preflight] analyzer → AST 반영 경고: {e}")
            else:
                if zeros_est is not None:
                    print(f"[preflight] analyzer DRY-RUN: would set isException=1 for ≈{zeros_est} identifiers (explicit 0→1). Set SWINGFT_APPLY_ANALYZER_TO_AST=1 to apply")
                else:
                    print(f"[preflight] analyzer DRY-RUN: would set isException=1 for identifiers (explicit 0→1). Set SWINGFT_APPLY_ANALYZER_TO_AST=1 to apply")
    except Exception:
        pass

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
    
    # 샘플 파일 생성 (공용 커맨드 사용)
    sample_path = f"{config_path}.sample"
    try:
        from swingft_cli.commands.json_cmd import handle_generate_json
        handle_generate_json(sample_path)
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


# (중복 제거) 샘플 config 생성은 json_cmd.handle_generate_json을 사용합니다.


# --- Helper function: Save exclude review JSON ---
def _save_exclude_review_json(approved_identifiers, project_root: str | None, ast_file_path: str | None) -> str | None:
    from .exclude_review import save_exclude_review_json as __impl
    return __impl(approved_identifiers, project_root, ast_file_path)

# --- Helper function: Save exclude PENDING JSON (before y/n) ---
def _save_exclude_pending_json(project_root: str | None, ast_file_path: str | None, candidates) -> str | None:
    from .exclude_review import save_exclude_pending_json as __impl
    return __impl(project_root, ast_file_path, candidates)

# --- Helper: POST payload as-is to /complete and get raw output ---
from .llm_feedback import post_complete as _post_complete
from .exclude_review import save_exclude_review_json as _save_exclude_review_json
from .exclude_review import save_exclude_pending_json as _save_exclude_pending_json
from .exclude_review import generate_payloads_for_excludes as _generate_payloads_for_excludes

# --- Helper function: Generate per-identifier payloads for exclude targets ---
def _generate_payloads_for_excludes(project_root: str | None, identifiers: list[str]) -> None:
    from .exclude_review import generate_payloads_for_excludes as __impl
    __impl(project_root, identifiers)


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
                    #f"환경변수에 의해 project 경로가 업데이트되었습니다: input={proj.get('input', '')!s}, output={proj.get('output', '')!s}",
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

    # Check for conflicts with exception_list.json (refactored)
    try:
        _check_exception_conflicts(path, data)
    except SystemExit:
        raise
    except Exception:
        pass
    
    return data


#
# NOTE: `_no_inherit` is a soft guard to signal later stages not to
# propagate a parent's isException value into its children. It is benign
# if ignored, but tools that support it should respect the flag.
# Matching semantics: a spec without parent path matches ANY node whose A_name equals the leaf; no cascading to children with different names.
from .ast_utils import update_ast_node_exceptions as _update_ast_node_exceptions

def _check_exception_conflicts(*args, **kwargs):
    # legacy shim (kept for import/back-compat); logic moved to preflight.conflicts
    from .conflicts import check_exception_conflicts as _impl

    # extract config for gating
    _config_path = None
    _config = None
    if isinstance(args, tuple) and len(args) >= 2:
        _config_path = args[0]
        _config = args[1]
    else:
        _config_path = kwargs.get("config_path")
        _config = kwargs.get("config")

    # If identifier obfuscation is disabled, skip preflight (include/exclude) entirely
    try:
        def _to_bool(v, default=True):
            if isinstance(v, bool):
                return v
            if isinstance(v, str):
                return v.strip().lower() in {"1", "true", "yes", "y", "on"}
            if isinstance(v, (int, float)):
                return bool(v)
            return default
        identifiers_on = True
        if isinstance(_config, dict):
            src = _config.get("options") if isinstance(_config.get("options"), dict) else _config
            identifiers_on = _to_bool((src or {}).get("Obfuscation_identifiers", True), True)
        if not identifiers_on:
            return set()
    except Exception:
        pass

    res = _impl(*args, **kwargs)
    try:
        if _config_path is not None and _config is not None:
            _check_exclude_sensitive_identifiers(_config_path, _config, res or set())
    except Exception:
        pass


def _check_exclude_sensitive_identifiers(config_path: str, config, ex_names):
    from .exclude_review import process_exclude_sensitive_identifiers as __impl
    __impl(config_path, config, ex_names)
