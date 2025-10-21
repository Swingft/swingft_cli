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
                print(f"[preflight] analyzer run: {cmd}")
                subprocess.run(cmd, shell=True, cwd=analyzer_root)
            else:
                analyze_py = os.path.join(analyzer_root, "analyze.py")
                if os.path.isfile(analyze_py):
                    cmd_list = ["python3", "analyze.py", project_root]
                    print(f"[preflight] analyzer run (default): {' '.join(cmd_list)}")
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
            print(f"[preflight] AST path autodetect: {ast_path_eff or 'NOT FOUND'}")
        if ast_path_eff and os.path.isfile(ast_path_eff):
            # Always print comparison summary (one/zero/missing) before applying
            zeros_est = None
            try:
                _comp = compare_exclusion_list_vs_ast(analyzer_root, ast_path_eff)
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
                        print(f"[preflight] analyzer → AST 적용: ≈{zeros_est} identifiers (explicit 0→1, apply=ON)")
                    else:
                        print(f"[preflight] analyzer → AST 적용: identifiers (explicit 0→1, apply=ON)")
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


# --- Helper function: Save exclude review JSON ---
def _save_exclude_review_json(approved_identifiers, project_root: str | None, ast_file_path: str | None) -> str | None:
    """Save a minimal review JSON capturing only user-approved exclude targets."""
    try:
        if not approved_identifiers:
            return None
        out_dir = os.path.join(os.getcwd(), ".swingft", "preflight")
        os.makedirs(out_dir, exist_ok=True)
        ts = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
        out_path = os.path.join(out_dir, f"exclude_review_{ts}.json")
        payload = {
            "timestamp": datetime.utcnow().isoformat() + "Z",
            "kind": "exclude_review",
            "project_input": project_root or "",
            "ast_node_path": ast_file_path or "",
            "approved_identifiers": sorted(list({str(x).strip() for x in approved_identifiers if str(x).strip()})),
            "source": "loader._check_exclude_sensitive_identifiers",
            "decision_basis": "user_confirmation_only"
        }
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)
        print(f"[preflight] 사용자 승인 대상 JSON 저장: {out_path}")
        return out_path
    except Exception as e:
        print(f"[preflight] exclude_review JSON 저장 실패: {e}")
        return None

# --- Helper function: Save exclude PENDING JSON (before y/n) ---
def _save_exclude_pending_json(project_root: str | None, ast_file_path: str | None, candidates) -> str | None:
    """Persist the FULL set of identifiers that require user confirmation (pre y/n)."""
    try:
        names = sorted(list({str(x).strip() for x in (candidates or []) if isinstance(x, str) and x.strip()}))
        if not names:
            return None
        out_dir = os.path.join(os.getcwd(), ".swingft", "preflight")
        os.makedirs(out_dir, exist_ok=True)
        ts = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
        out_path = os.path.join(out_dir, f"exclude_pending_{ts}.json")
        payload = {
            "timestamp": datetime.utcnow().isoformat() + "Z",
            "kind": "exclude_pending",
            "project_input": project_root or "",
            "ast_node_path": ast_file_path or "",
            "candidates": names,
            "source": "loader._check_exclude_sensitive_identifiers"
        }
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)
        if _preflight_verbose():
            print(f"[preflight] 사용자 확인 대상(PENDING) JSON 저장: {out_path}")
        return out_path
    except Exception as e:
        if _preflight_verbose():
            print(f"[preflight] exclude_pending JSON 저장 실패: {e}")
        return None

# --- Helper: POST payload as-is to /complete and get raw output ---
from .llm_feedback import post_complete as _post_complete

# --- Helper function: Generate per-identifier payloads for exclude targets ---
def _generate_payloads_for_excludes(project_root: str | None, identifiers: list[str]) -> None:
    """
    Generate per-identifier payload JSON files ONLY for user-approved exclude targets.
    Prefer calling preflight generator; if unavailable, write minimal payloads.
    """
    try:
        if not identifiers:
            return
        out_dir = os.path.join(os.getcwd(), ".swingft", "preflight", "payloads")
        os.makedirs(out_dir, exist_ok=True)
        # Try to use the preflight module if present
        try:
            from swingft_cli.core.preflight.find_identifiers_and_ast_dual import write_per_identifier_payload_files  # type: ignore
            write_per_identifier_payload_files(project_root or "", identifiers=identifiers, out_dir=out_dir)
            if _preflight_verbose():
                print(f"[preflight] exclude 대상 {len(identifiers)}개에 대한 payload 생성 완료: {out_dir}")
            return
        except Exception as e:
            if _preflight_verbose():
                print(f"[preflight] preflight payload 생성기 사용 불가, 최소 JSON 생성으로 대체: {e}")
        # Fallback: minimal JSON per identifier
        ts = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
        for ident in identifiers:
            name = str(ident).strip()
            if not name:
                continue
            payload = {
                "timestamp": datetime.utcnow().isoformat() + "Z",
                "kind": "exclude_payload",
                "project_input": project_root or "",
                "identifier": name
            }
            fn = f"{name}.payload.json"
            path = os.path.join(out_dir, fn)
            with open(path, "w", encoding="utf-8") as f:
                json.dump(payload, f, ensure_ascii=False, indent=2)
        if _preflight_verbose():
            print(f"[preflight] 최소 payload 생성 완료: {len(identifiers)}개 → {out_dir}")
    except Exception as e:
        if _preflight_verbose():
            print(f"[preflight] exclude payload 생성 실패: {e}")


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

    # Check for conflicts with exception_list.json
    _check_exception_conflicts(path, data)
    
    return data


#
# NOTE: `_no_inherit` is a soft guard to signal later stages not to
# propagate a parent's isException value into its children. It is benign
# if ignored, but tools that support it should respect the flag.
# Matching semantics: a spec without parent path matches ANY node whose A_name equals the leaf; no cascading to children with different names.
def _update_ast_node_exceptions(*args, **kwargs):
    # Backward-compatible wrapper to the refactored implementation.
    from .ast_utils import update_ast_node_exceptions as _impl
    return _impl(*args, **kwargs)

def _remove_from_exception_list(exc_file_path, identifiers_to_remove):
    """Remove specified identifiers from exception_list.json"""
    try:
        with open(exc_file_path, 'r', encoding='utf-8') as f:
            ex_list = json.load(f)
        
        if not isinstance(ex_list, list):
            print(f"[preflight] ERROR: exception_list.json is not a list")
            return
        
        # Filter out identifiers to remove
        original_count = len(ex_list)
        filtered_list = []
        removed_count = 0
        
        for item in ex_list:
            if isinstance(item, dict):
                name = str(item.get("A_name", "")).strip()
                if name in identifiers_to_remove:
                    removed_count += 1
                    print(f"  - 제거: {name}")
                else:
                    filtered_list.append(item)
            else:
                filtered_list.append(item)
        
        # Write back the filtered list
        with open(exc_file_path, 'w', encoding='utf-8') as f:
            json.dump(filtered_list, f, ensure_ascii=False, indent=2)
        
        print(f"[preflight] exception_list.json 업데이트: {original_count} → {len(filtered_list)} (제거: {removed_count}개)")
        
    except Exception as e:
        print(f"[preflight] ERROR: exception_list.json 업데이트 실패: {e}")

def _check_exception_conflicts(config_path: str, config: Dict[str, Any]) -> None:
    """Check for conflicts between config and ast_node.json"""
    from pathlib import Path
    
    #print(f"[DEBUG] Current working directory: {os.getcwd()}")
    
    # Auto-detect ast_node.json path (env override first)
    env_ast = os.environ.get("SWINGFT_AST_NODE_PATH", "").strip()
    #print(f"[DEBUG] SWINGFT_AST_NODE_PATH: {env_ast}")
    if env_ast and os.path.exists(env_ast):
        ast_file = Path(env_ast)
        #print(f"[DEBUG] Using environment variable path: {ast_file}")
    else:
        # Fallback candidates
        ast_candidates = [
            os.path.join(os.getcwd(), "Obfuscation_Pipeline", "AST", "output", "ast_node.json"),
            os.path.join(os.getcwd(), "AST", "output", "ast_node.json"),
        ]
        #print(f"[DEBUG] Checking fallback paths:")
        for i, path in enumerate(ast_candidates):
            exists = os.path.exists(path)
            #print(f"[DEBUG]   {i+1}. {path} - {'EXISTS' if exists else 'NOT FOUND'}")
        ast_file = next((Path(p) for p in ast_candidates if Path(p).exists()), None)
        #print(f"[DEBUG] Using fallback path: {ast_file}")
    
    if not ast_file:
        print("[preflight] ast_node.json not found - skipping conflict check")
        return
    
    #print(f"[preflight] Using AST node file: {ast_file}")

    # Optionally apply config.exclude.obfuscation to AST before checks
    try:
        apply_cfg = str(os.environ.get("SWINGFT_APPLY_CONFIG_TO_AST", "")).strip().lower() in {"1","true","yes","y","on"}
        if apply_cfg and ast_file and ast_file.exists():
            applied = _apply_config_exclusions_to_ast(str(ast_file), config)
            if applied:
                print(f"[preflight] apply-config → AST: {applied} nodes updated (from exclude.obfuscation)")
        else:
            if _preflight_verbose():
                print("[preflight] apply-config DRY-RUN: not applying to AST (set SWINGFT_APPLY_CONFIG_TO_AST=1 to apply)")
    except Exception:
        pass
    
    try:
        # Load AST node list
        with open(ast_file, 'r', encoding='utf-8') as f:
            ast_list = json.load(f)
    except Exception as e:
        #print(f"[preflight] warning: failed to load ast_node.json for conflict check: {e}")
        return
    
    # Extract identifiers from AST nodes (isException: 1인 것들만) — RECURSIVE
    def _collect_ex_names_rec(ast_root):
        collected = set()
        CONTAINER_KEYS = ("G_members", "children", "members", "extension", "node")

        def _walk(obj):
            if isinstance(obj, dict):
                cur = _ast_unwrap(obj)
                if isinstance(cur, dict):
                    nm = str(cur.get("A_name", "")).strip()
                    if nm and int(cur.get("isException", 0)) == 1:
                        collected.add(nm)
                    # containers on cur
                    for key in CONTAINER_KEYS:
                        ch = cur.get(key)
                        if isinstance(ch, list):
                            for c in ch:
                                _walk(c)
                        elif isinstance(ch, dict):
                            _walk(ch)
                    # sibling containers on wrapper obj
                    if obj is not cur:
                        for key in CONTAINER_KEYS:
                            if key == 'node':
                                continue
                            ch = obj.get(key)
                            if isinstance(ch, list):
                                for c in ch:
                                    _walk(c)
                            elif isinstance(ch, dict):
                                _walk(ch)
                    # conservative descent
                    for v in cur.values():
                        _walk(v)
                    if obj is not cur:
                        for k, v in obj.items():
                            if k not in CONTAINER_KEYS:
                                _walk(v)
                else:
                    for v in obj.values():
                        _walk(v)
            elif isinstance(obj, list):
                for it in obj:
                    _walk(it)

        _walk(ast_root)
        return collected

    ex_names = _collect_ex_names_rec(ast_list)
    
    if not ex_names:
        #print("[preflight] ast_node.json contains no excluded identifiers - skipping conflict check")
        return
    
  #  print(f"[preflight] Loaded {len(ex_names)} excluded identifiers from AST nodes")
    #print(f"[preflight] Sample excluded identifiers: {sorted(list(ex_names))[:5]}")
    
    # Check for '*' patterns and warn user
    wildcard_patterns = []
    for section in ("include", "exclude"):
        for category in ("obfuscation",):
            items = config.get(section, {}).get(category, [])
            if isinstance(items, list):
                for item in items:
                    if isinstance(item, str) and item.strip() == "*":
                        wildcard_patterns.append(f"{section}.{category}")
    
    if wildcard_patterns:
        print(f"\n[preflight] ⚠️  '*' 단독 패턴 사용 감지:")
        for pattern in wildcard_patterns:
            print(f"  - {pattern}: 모든 식별자에 적용됩니다")
        print("  - 이는 의도된 설정인지 확인이 필요합니다.")
        
        try:
            prompt_msg = "계속 진행하시겠습니까? [y/N]: "
            if _has_ui_prompt():
                ans = str(getattr(_cfg, "PROMPT_PROVIDER")(prompt_msg)).strip().lower()
            else:
                ans = input(prompt_msg).strip().lower()
            if ans not in ("y", "yes"):
                print("사용자에 의해 취소되었습니다.")
                sys.exit(1)
        except (EOFError, KeyboardInterrupt):
            print("\n사용자에 의해 취소되었습니다.")
            sys.exit(1)
    
    # Extract only include identifiers (excluding exclude - they're fine to overlap)
    config_names = set()
    for category in ("obfuscation",):
        items = config.get("include", {}).get(category, [])
        if isinstance(items, list):
            for item in items:
                if isinstance(item, str) and item.strip():
                    item = item.strip()
                    if "*" not in item and "?" not in item:
                        # Literal identifier
                        config_names.add(item)
                    else:
                        # Wildcard pattern - expand against exception list
                        import fnmatch
                        for ex_name in ex_names:
                            if fnmatch.fnmatchcase(ex_name, item):
                                config_names.add(ex_name)
    
    # Check for conflicts
    conflicts = config_names & ex_names
    # quiet by default when UI is active
    _preflight_print(f"[preflight] Config include identifiers: {sorted(list(config_names))}")
    _preflight_print(f"[preflight] Conflicts found: {len(conflicts)} items")
    if conflicts:
        # 정책 읽기(통합): preflight.conflict_policy 우선, 없으면 include_conflict_policy, 기본 ask
        _pf = config.get("preflight", {}) if isinstance(config.get("preflight"), dict) else {}
        policy = str(
            _pf.get("conflict_policy")
            or _pf.get("include_conflict_policy")
            or "ask"
        ).strip().lower()
        _preflight_print(f"\n[preflight] ⚠️  The provided include entries conflict with exclude rules; including them may cause conflicts:")
        sample_all = sorted(list(conflicts))
        sample = sample_all[:10]
        _preflight_print(f"  - Collision identifiers: {len(conflicts)} items (example: {', '.join(sample)})")
        try:
            if policy == "force":
                _update_ast_node_exceptions(
                    ast_file, conflicts, is_exception=0,
                    allowed_kinds={"function"}, lock_children=True,
                    quiet=_has_ui_prompt()
                )
            elif policy == "skip":
                print("[preflight] include-conflict policy=skip → 자동 미반영")
                try:
                    fb = [
                        "[preflight] Include conflict skipped by policy",
                        f"Conflicts: {len(conflicts)}",
                        f"Sample: {', '.join(sample_all[:20])}",
                        f"Policy: {policy}",
                    ]
                    _write_feedback_to_output(config, "include_conflict_skipped", "\n".join(fb))
                except Exception:
                    pass
            else:
                if _has_ui_prompt():
                    sample_one = sample_all[0] if sample_all else ""
                    prompt_msg = f"[preflight]\nThe provided include entries conflict with exclude rules.\n  - Collision identifiers: {len(conflicts)} items (e.g., {sample_one})\n\nDo you really want to include these identifiers in obfuscation? [y/N]: "
                    ans = str(getattr(_cfg, "PROMPT_PROVIDER")(prompt_msg)).strip().lower()
                else:
                    prompt_msg = "Do you really want to include these identifiers in obfuscation? [y/N]: "
                    ans = input(prompt_msg).strip().lower()
                if ans in ("y", "yes"):
                    _update_ast_node_exceptions(
                        ast_file, conflicts, is_exception=0,
                        allowed_kinds={"function"}, lock_children=True,
                        quiet=_has_ui_prompt()
                    )
                else:
                    print("[preflight] 사용자가 충돌 항목 제거를 취소했습니다.")
        except (EOFError, KeyboardInterrupt):
            print("\n사용자에 의해 취소되었습니다.")
            sys.exit(1)
    else:
        _preflight_print("[preflight] Include 대상과 제외대상 간 충돌 없음")
    
    # Check exclude identifiers not in AST excluded set
    _check_exclude_sensitive_identifiers(config_path, config, ex_names)


def _check_exclude_sensitive_identifiers(config_path: str, config, ex_names):
    """Ensure exclude.obfuscation identifiers are reflected in ast_node.json.

    If an identifier is listed in exclude.obfuscation but not yet excluded (isException=1) in ast_node.json,
    automatically set isException=1 for that identifier without calling the LLM server or asking user confirmation.
    """
    from swingft_cli.core.config.rules import scan_swift_identifiers
    from pathlib import Path

    project_root = config.get("project", {}).get("input")
    if not project_root or not os.path.isdir(project_root):
        print("[preflight] project.input 경로가 없어 프로젝트 식별자 스캔을 건너뜁니다.")
        return

    project_identifiers = set(scan_swift_identifiers(project_root))
    if not project_identifiers:
        print("[preflight] 프로젝트에서 식별자를 찾지 못했습니다.")
        return

    # Collect exclude identifiers that exist in project but not yet excluded in AST
    exclude_candidates = set()
    for category in ("obfuscation",):
        items = config.get("exclude", {}).get(category, [])
        if isinstance(items, list):
            for item in items:
                if isinstance(item, str) and item.strip():
                    name = item.strip()
                    if "*" not in name and "?" not in name:
                        if name in project_identifiers:
                            exclude_candidates.add(name)
                    else:
                        import fnmatch
                        for proj_id in project_identifiers:
                            if fnmatch.fnmatchcase(proj_id, name):
                                exclude_candidates.add(proj_id)

    if not exclude_candidates:
        print("[preflight] Exclude(obfuscation) 후보 중 AST(excluded) 기준으로 새로 반영할 식별자 없음 ✅")
        return

    print(f"\n[preflight] Exclude 대상 중 AST(excluded)에 없는 식별자 {len(exclude_candidates)}개 발견")

    # 정책 읽기(통합): preflight.conflict_policy 우선, 없으면 exclude_candidate_policy, 기본 ask
    _pf = config.get("preflight", {}) if isinstance(config.get("preflight"), dict) else {}
    ex_policy = str(
        _pf.get("conflict_policy")
        or _pf.get("exclude_candidate_policy")
        or "ask"
    ).strip().lower()

    from .llm_feedback import build_structured_input as _build_structured_input

    from .llm_feedback import call_exclude_server_parsed as _call_exclude_server_parsed

    # Locate ast_node.json (중복 확인 및 이후 반영을 위해 선행)
    env_ast = os.environ.get("SWINGFT_AST_NODE_PATH", "").strip()
    if env_ast and os.path.exists(env_ast):
        ast_file = Path(env_ast)
    else:
        ast_candidates = [
            os.path.join(os.getcwd(), "Obfuscation_Pipeline", "AST", "output", "ast_node.json"),
            os.path.join(os.getcwd(), "AST", "output", "ast_node.json"),
        ]
        ast_file = next((Path(p) for p in ast_candidates if Path(p).exists()), None)

    # 중복 확인
    existing_names = set()
    if ast_file and ast_file.exists():
        try:
            with open(ast_file, 'r', encoding='utf-8') as f:
                ast_list = json.load(f)

            CONTAINER_KEYS = ("G_members", "children", "members", "extension", "node")

            def _collect_names(obj):
                if isinstance(obj, dict):
                    cur = _ast_unwrap(obj)
                    if isinstance(cur, dict):
                        nm = str(cur.get("A_name", "")).strip()
                        if nm:
                            existing_names.add(nm)
                        # containers on cur
                        for key in CONTAINER_KEYS:
                            ch = cur.get(key)
                            if isinstance(ch, list):
                                for c in ch:
                                    _collect_names(c)
                            elif isinstance(ch, dict):
                                _collect_names(ch)
                        # sibling containers on wrapper obj
                        if obj is not cur:
                            for key in CONTAINER_KEYS:
                                if key == 'node':
                                    continue
                                ch = obj.get(key)
                                if isinstance(ch, list):
                                    for c in ch:
                                        _collect_names(c)
                                elif isinstance(ch, dict):
                                    _collect_names(ch)
                        # conservative descent
                        for v in cur.values():
                            _collect_names(v)
                        if obj is not cur:
                            for k, v in obj.items():
                                if k not in CONTAINER_KEYS:
                                    _collect_names(v)
                    else:
                        for v in obj.values():
                            _collect_names(v)
                elif isinstance(obj, list):
                    for it in obj:
                        _collect_names(it)

            _collect_names(ast_list)
        except Exception:
            pass
    
    duplicates = exclude_candidates & existing_names
    if duplicates:
        print(f"  - 중복 식별자 발견: {sorted(list(duplicates))}")
        print("  - 이들은 이미 AST에 존재하지만 isException!=1 상태입니다.")
    # Persist the full confirmation set BEFORE asking y/n
    try:
        _save_exclude_pending_json(project_root, str(ast_file) if ast_file else None, sorted(list(exclude_candidates)))
    except Exception as _e:
        print(f"[preflight] exclude_pending JSON 저장 경고: {_e}")
    # --- Generate per-identifier payloads for ALL pending candidates BEFORE y/n ---
    if ex_policy != "skip":
        try:
            from swingft_cli.core.preflight.find_identifiers_and_ast_dual import write_per_identifier_payload_files  # type: ignore
            _pending_payloads_dir = os.path.join(os.getcwd(), ".swingft", "preflight", "payloads", "pending")
            os.makedirs(_pending_payloads_dir, exist_ok=True)
            write_per_identifier_payload_files(
                project_root or "",
                identifiers=sorted(list(exclude_candidates)),
                out_dir=_pending_payloads_dir,
            )
            if _preflight_verbose():
                print(f"[preflight] PENDING payloads 생성 완료: {len(exclude_candidates)}개 → {_pending_payloads_dir}")
        except Exception as _e:
            print(f"[preflight] PENDING payloads 생성 경고: {_e}")

    # --- LLM raw suggestions using /complete with pending payload (pre y/n) ---
    server_results = []
    # LLM 호출 단계 비활성화: 서버 호출을 완전히 건너뜀 (임시)
    server_results = []
    
    # 1) 원격 서버에 판단 요청 시도(가능하면 심볼 정보/코드 전달)
    #    현재 컨텍스트에서는 프로젝트 전체 심볼 요약만 제공될 수 있어 identifiers만 전달
    # --- 소스 코드 스니펫 수집 유틸 ---
    def _find_first_swift_file_with_identifier(project_dir: str, ident: str):
        try:
            for root, dirs, files in os.walk(project_dir):
                # Skip hidden dirs and common build dirs
                dirs[:] = [d for d in dirs if not d.startswith(".") and d not in {"build", "DerivedData"}]
                for fn in files:
                    if not fn.lower().endswith(".swift"):
                        continue
                    fp = os.path.join(root, fn)
                    try:
                        with open(fp, "r", encoding="utf-8", errors="ignore") as f:
                            text = f.read()
                        if ident in text:
                            return fp, text
                    except Exception:
                        continue
        except Exception:
            return None
        return None

    def _make_snippet(text: str, ident: str, ctx_lines: int = 30) -> str:
        try:
            lines = text.splitlines()
            # find first occurrence line index
            hit = None
            for i, ln in enumerate(lines):
                if ident in ln:
                    hit = i
                    break
            if hit is None:
                # fallback: truncate whole text
                s = text[:8000]
                return s
            lo = max(0, hit - ctx_lines)
            hi = min(len(lines), hit + ctx_lines + 1)
            snippet = "\n".join(lines[lo:hi])
            # cap length
            if len(snippet) > 8000:
                snippet = snippet[:8000] + "\n... [truncated]"
            return snippet
        except Exception:
            return text[:8000]

    def _run_swift_ast_analyzer(swift_file_path: str):
        """Run ast_analyzers/sensitive/SwiftASTAnalyzer and return parsed JSON (dict) or None.

        Mirrors BaseAnalyzer.run_swift_analyzer: executes binary, extracts JSON from stdout.
        """
        try:
            from pathlib import Path
            analyzer_path = Path(os.getcwd()) / "ast_analyzers" / "sensitive" / "SwiftASTAnalyzer"
            if not analyzer_path.exists():
                print(f"Warning: AST analyzer not found at {analyzer_path}")
                return None
            import subprocess
            command_str = f'"{str(analyzer_path)}" "{swift_file_path}"'
            proc = subprocess.run(
                command_str,
                shell=True,
                capture_output=True,
                text=True,
                encoding="utf-8",
                timeout=60,
            )
            if proc.returncode != 0:
                err = (proc.stderr or "").strip()
                print(f"Warning: AST analyzer failed for {swift_file_path}. Error: {err}")
                return None
            out = (proc.stdout or "").strip()
            if not out:
                return None
            lb = out.find("[")
            lb2 = out.find("{")
            if lb == -1 and lb2 == -1:
                return None
            json_start = lb if (lb != -1 and (lb < lb2 or lb2 == -1)) else lb2
            json_part = out[json_start:]
            try:
                data = json.loads(json_part)
                return data
            except json.JSONDecodeError:
                return None
        except subprocess.TimeoutExpired:
            print(f"Warning: AST analysis timed out for {swift_file_path}")
            return None
        except Exception as e:
            print(f"Warning: AST analysis failed for {swift_file_path}: {e}")
            return None

    # --- 정책 적용: force/skip/ask ---
    decided_to_exclude = set()
    if ex_policy == "skip":
        print("[preflight] exclude-candidate policy=skip → 자동 미반영")
        try:
            fb = [
                "[preflight] Exclude candidates skipped by policy",
                f"Candidates: {len(exclude_candidates)}",
                f"Sample: {', '.join(sorted(list(exclude_candidates))[:20])}",
                f"Policy: {ex_policy}",
            ]
            _write_feedback_to_output(config, "exclude_candidates_skipped", "\n".join(fb))
        except Exception:
            pass
        return
    elif ex_policy == "force":
        decided_to_exclude = set(exclude_candidates)
        print(f"[preflight] exclude-candidate policy=force → {len(decided_to_exclude)}개 자동 반영")
    else:
        # --- 서버 판단: LLM 제안이 없을 때만 사용자 y/n로 최초 결정 ---
        if not server_results:
            proj_root = config.get("project", {}).get("input")
            if isinstance(proj_root, str) and os.path.isdir(proj_root):
                for ident in sorted(list(exclude_candidates)):
                    try:
                        if _has_ui_prompt():
                            prompt = (
                                f"[preflight]\n"
                                f"Exclude candidate detected.\n"
                                f"  - identifier: {ident}\n\n"
                                f"Exclude this identifier from obfuscation? [y/N]: "
                            )
                            ans = str(getattr(_cfg, "PROMPT_PROVIDER")(prompt)).strip().lower()
                        else:
                            ans = input(f"식별자 '{ident}'를 난독화에서 제외할까요? [y/N]: ").strip().lower()
                    except (EOFError, KeyboardInterrupt):
                        print("\n사용자에 의해 취소되었습니다.")
                        sys.exit(1)
                    exclude_flag = ans in ("y", "yes")
                    server_results.append({"name": ident, "exclude": exclude_flag, "reason": "user_decision"})
            else:
                for ident in sorted(list(exclude_candidates)):
                    try:
                        if _has_ui_prompt():
                            prompt = (
                                f"[preflight]\n"
                                f"Exclude candidate detected.\n"
                                f"  - identifier: {ident}\n\n"
                                f"Exclude this identifier from obfuscation? [y/N]: "
                            )
                            ans = str(getattr(_cfg, "PROMPT_PROVIDER")(prompt)).strip().lower()
                        else:
                            ans = input(f"식별자 '{ident}'를 난독화에서 제외할까요? [y/N]: ").strip().lower()
                    except (EOFError, KeyboardInterrupt):
                        print("\n사용자에 의해 취소되었습니다.")
                        sys.exit(1)
                    exclude_flag = ans in ("y", "yes")
                    server_results.append({"name": ident, "exclude": exclude_flag, "reason": "user_decision"})

    # Normalize: de-duplicate server results by name
    if isinstance(server_results, list):
        uniq, out = set(), []
        for it in server_results:
            if not isinstance(it, dict):
                continue
            nm = str((it.get("name") or it.get("identifier") or "")).strip()
            if not nm or nm in uniq:
                continue
            uniq.add(nm)
            out.append(it)
        server_results = out
    if ex_policy == "force":
        pass  # already set decided_to_exclude
    elif isinstance(server_results, list) and server_results:
        # If all decisions were made by the user already, apply directly without second review
        if all(isinstance(it, dict) and str(it.get("reason", "")) == "user_decision" for it in server_results):
            for it in server_results:
                try:
                    if it.get("exclude"):
                        decided_to_exclude.add(str(it.get("name")).strip())
                except Exception:
                    continue
            print(f"\n[preflight] 사용자 승인 완료: 제외로 반영 {len(decided_to_exclude)}개")
            # --- Save exclude review JSON after user approval ---
            try:
                _save_exclude_review_json(sorted(list(decided_to_exclude)), project_root, str(ast_file) if ast_file else None)
            except Exception as _e:
                print(f"[preflight] exclude_review JSON 저장 경고: {_e}")
            try:
                _generate_payloads_for_excludes(project_root, sorted(list(decided_to_exclude)))
            except Exception as _e:
                print(f"[preflight] exclude payload 생성 경고: {_e}")
        else:
            # 배치 승인 모드: 한 번의 y/N로 전체 후보를 제외로 반영
            try:
                names = [str((it.get("name") or it.get("identifier") or "")).strip() for it in server_results]
                names = [n for n in names if n]
                preview = ", ".join(names[:10]) + (" ..." if len(names) > 10 else "")
                if _has_ui_prompt():
                    prompt = (
                        f"[preflight]\n"
                        f"총 {len(names)}개 식별자 후보가 있습니다.\n"
                        f"예시: {preview}\n\n"
                        f"모든 항목을 난독화 제외로 반영할까요? [y/N]: "
                    )
                    ans = str(getattr(_cfg, "PROMPT_PROVIDER")(prompt)).strip().lower()
                else:
                    ans = input(f"총 {len(names)}개 후보(ex: {preview})를 모두 제외로 반영할까요? [y/N]: ").strip().lower()
            except (EOFError, KeyboardInterrupt):
                print("\n사용자에 의해 취소되었습니다.")
                sys.exit(1)
            if ans in ("y", "yes"):
                decided_to_exclude.update(names)
            print(f"\n[preflight] 사용자 승인 완료: 제외로 반영 {len(decided_to_exclude)}개")
            # --- Save exclude review JSON after user approval ---
            try:
                _save_exclude_review_json(sorted(list(decided_to_exclude)), project_root, str(ast_file) if ast_file else None)
            except Exception as _e:
                print(f"[preflight] exclude_review JSON 저장 경고: {_e}")
            try:
                _generate_payloads_for_excludes(project_root, sorted(list(decided_to_exclude)))
            except Exception as _e:
                print(f"[preflight] exclude payload 생성 경고: {_e}")

    if not ast_file:
        print("  - 경고: ast_node.json 경로를 찾지 못해 AST 반영을 건너뜁니다.")
        return

    # Update AST
    try:
        _update_ast_node_exceptions(ast_file, sorted(list(decided_to_exclude)), is_exception=1, allowed_kinds=None, lock_children=False)
        print("  - 처리: ast_node.json 반영 완료 (isException=1)")
    except Exception as e:
        print(f"  - 처리 실패: ast_node.json 반영 중 오류 ({e})")




def _add_to_exception_list(identifiers):
    """Add identifiers to exception_list.json"""
    from pathlib import Path
    
    # Find exception_list.json
    exc_candidates = [
        os.path.join(os.getcwd(), "exception_list.json"),
        os.path.join(os.getcwd(), "ID_Obfuscation", "output", "exception_list.json"),
        os.path.join(os.getcwd(), "identifier_obfuscation", "exception_list.json"),
    ]
    exc_file = next((Path(p) for p in exc_candidates if Path(p).exists()), None)
    
    if not exc_file:
        # Create new exception_list.json
        exc_file = Path("exception_list.json")
    
    try:
        # Load existing exception list
        if exc_file.exists():
            with open(exc_file, 'r', encoding='utf-8') as f:
                ex_list = json.load(f)
        else:
            ex_list = []
        
        # Add new identifiers
        existing_names = {item.get("A_name", "") for item in ex_list if isinstance(item, dict)}
        added_count = 0
        for identifier in sorted(identifiers):
            if identifier not in existing_names:
                ex_list.append({
                    "A_name": identifier,
                    "A_type": "identifier",
                    "A_comment": "Auto-added by preflight check"
                })
                added_count += 1
        
        # Save updated exception list
        with open(exc_file, 'w', encoding='utf-8') as f:
            json.dump(ex_list, f, ensure_ascii=False, indent=2)
        
        print(f"[preflight] {added_count}개 식별자를 exception_list.json에 추가했습니다: {exc_file}")
        
    except Exception as e:
        print(f"[preflight] exception_list.json 업데이트 실패: {e}")
        print("수동으로 식별자를 추가해주세요.")