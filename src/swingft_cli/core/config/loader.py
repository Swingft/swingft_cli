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
def _update_ast_node_exceptions(ast_file_path, identifiers_to_update, is_exception=0, allowed_kinds=None, lock_children=True, quiet: bool = False):
    """Update isException flag for specified identifiers in ast_node.json.

    Supports nested members and optional kind filtering.
    identifiers_to_update can contain:
      - simple names: "rotate"
      - dotted path:  "UIView.rotate"  (parent.A_name + "." + child.A_name)
      - kind hint:    "function:rotate" or "extension:UIView" (kind:name)
      - combined:     "extension:UIView.rotate" (kind:path)

    If allowed_kinds is given (e.g., {"function"}), only those kinds are updated.
    lock_children: If True, prevents isException from cascading to children when a match is found.
    """
    try:
        with open(ast_file_path, 'r', encoding='utf-8') as f:
            ast_list = json.load(f)

        if not isinstance(ast_list, list):
            if not quiet:
                print(f"[preflight] ERROR: ast_node.json is not a list")
            return

        # --- parse target specs ---
        def _parse_spec(spec: str):
            # returns (kind_hint_or_None, parent_path_list, leaf_name)
            if not isinstance(spec, str):
                return (None, [], "")
            s = spec.strip()
            kind_hint = None
            path_part = s

            # kind:name[..] pattern
            if ":" in s:
                k, rest = s.split(":", 1)
                k = k.strip().lower()
                if k:
                    kind_hint = k
                path_part = rest.strip()

            # dotted path
            parts = [p for p in path_part.split(".") if p.strip()]
            if not parts:
                return (kind_hint, [], "")
            if len(parts) == 1:
                return (kind_hint, [], parts[0])
            return (kind_hint, parts[:-1], parts[-1])

        parsed_targets = [ _parse_spec(x) for x in identifiers_to_update if isinstance(x, str) and x.strip() ]
        # Normalize allowed kinds
        if allowed_kinds is not None:
            allowed_kinds = {str(k).strip().lower() for k in allowed_kinds if str(k).strip()}
        else:
            allowed_kinds = None

        updated = 0

        # --- recursive traversal ---
        def _walk(node, parent_stack):
            nonlocal updated
            if not isinstance(node, dict):
                return
            name = str(node.get("A_name", "")).strip()
            kind = str(node.get("B_kind", "")).strip().lower()
            members = node.get("G_members") or []
            if not isinstance(members, list):
                members = []

            matched_here = False
            # Try to match each target spec against current node
            for kind_hint, parent_path, leaf in parsed_targets:
                # parent path must match (if provided)
                parent_names = [str(p).strip() for p in parent_stack]
                if parent_path:
                    if len(parent_path) > len(parent_names):
                        # cannot match if target path deeper than our stack
                        continue
                    # Compare only the last len(parent_path) entries
                    if parent_names[-len(parent_path):] != parent_path:
                        continue

                # leaf name must match current node's A_name
                if leaf and leaf != name:
                    continue

                # kind filter (allowed_kinds global)
                if allowed_kinds and kind not in allowed_kinds:
                    continue

                # kind hint in the spec (optional)
                if kind_hint and kind_hint != kind:
                    continue

                # Match → update isException
                node["isException"] = is_exception
                updated += 1
                #if not quiet:
                    #print(f"  - 업데이트: {'/'.join(parent_names + [name])} ({kind}) (isException: {is_exception})")

                # Prevent inheritance/cascading into children; we still recurse
                # to allow other nodes with the SAME name elsewhere to be updated.
                matched_here = True
                if lock_children:
                    node["_no_inherit"] = True
                # Do NOT modify children here unless they independently match by name.

            # IMPORTANT: Skip children when this node matched by name to avoid cascading changes
            # under a matched node (we still traverse other branches in the tree).
            # Recurse ONLY if we didn't match this node, so children won't be touched
            # unless they independently match elsewhere in the tree traversal.
            if not (lock_children and matched_here):
                for child in members:
                    _walk(child, parent_stack + [name])

        # Traverse all top-level nodes
        for top in ast_list:
            _walk(top, [])

        # Write back if any changes
        if updated > 0:
            with open(ast_file_path, 'w', encoding='utf-8') as f:
                json.dump(ast_list, f, ensure_ascii=False, indent=2)
            if not quiet:
                print(f"[preflight] ast_node.json 업데이트: {updated}개 항목의 isException을 {is_exception}으로 변경")
        else:
            if not quiet:
                print("[preflight] ast_node.json 업데이트: 변경 없음 (대상 미일치)")

    except Exception as e:
        if not quiet:
            print(f"[preflight] ERROR: ast_node.json 업데이트 실패: {e}")

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
        def _walk(node):
            if not isinstance(node, dict):
                return
            name = str(node.get("A_name", "")).strip()
            if name and node.get("isException", 0) == 1:
                collected.add(name)
            members = node.get("G_members") or []
            if isinstance(members, list):
                for ch in members:
                    _walk(ch)
        if isinstance(ast_root, list):
            for top in ast_root:
                _walk(top)
        elif isinstance(ast_root, dict):
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
        _preflight_print(f"\n[preflight] ⚠️  The provided include entries conflict with exclude rules; including them may cause conflicts:")
        sample_all = sorted(list(conflicts))
        sample = sample_all[:10]
        _preflight_print(f"  - Collision identifiers: {len(conflicts)} items (example: {', '.join(sample)})")
        try:
            if _has_ui_prompt():
                sample_one = sample_all[0] if sample_all else ""
                prompt_msg = f"[preflight]\nThe provided include entries conflict with exclude rules.\n  - Collision identifiers: {len(conflicts)} items (e.g., {sample_one})\n\nDo you really want to include these identifiers in obfuscation? [y/N]: "
                ans = str(getattr(_cfg, "PROMPT_PROVIDER")(prompt_msg)).strip().lower()
            else:
                prompt_msg = "Do you really want to include these identifiers in obfuscation? [y/N]: "
                ans = input(prompt_msg).strip().lower()
            if ans in ("y", "yes"):
                # ast_node.json에서 충돌 식별자들의 isException을 0으로 변경
                # noisy prints suppressed under UI
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

    def _build_structured_input(swift_code: str, symbol_info) -> str:
        """
        Build a single 'input' string identical in shape to the example payload:
        
        **Swift Source Code:**
        ```swift
        ...source...
        ```
        
        **AST Symbol Information (JSON):**
        ```
        ...pretty-printed JSON...
        ```
        """
        try:
            if isinstance(symbol_info, (dict, list)):
                pretty = json.dumps(symbol_info, ensure_ascii=False, indent=2)
            elif isinstance(symbol_info, str) and symbol_info.strip():
                # try to prettify if it's a JSON string
                try:
                    pretty = json.dumps(json.loads(symbol_info), ensure_ascii=False, indent=2)
                except Exception:
                    pretty = symbol_info
            else:
                pretty = "[]"
        except Exception:
            pretty = "[]"
        swift = swift_code if isinstance(swift_code, str) else ""
        return (
            "**Swift Source Code:**\n"
            "```swift\n" + swift + "\n```\n\n"
            "**AST Symbol Information (JSON):**\n"
            "```\n" + pretty + "\n```"
        )

    def _call_exclude_server_parsed(identifiers, symbol_info=None, swift_code=None):
        """Call external sensitive server and return list[{name, exclude, reason}].

        Preferred mode:
          - If swift_code or symbol_info is provided and identifiers has exactly one item,
            send a payload that matches the example structure:
                {
                  "instruction": "In the following Swift code, find all identifiers related to sensitive logic. Provide the names and reasoning as a JSON object.",
                  "input": "<markdown with Swift code and AST JSON>"
                }
            to the endpoint `${SWINGFT_SENSITIVE_SERVER_URL_STRUCTURED:-http://localhost:8000/analyze_structured}`.

        Fallback mode:
          - Otherwise, use the previous JSON shape:
                {"identifiers": [...], "symbol_info": {...}, "swift_code": "..."}
            to `${SWINGFT_SENSITIVE_SERVER_URL:-http://localhost:8000/analyze_parsed}`.
        """
        try:
            import requests  # type: ignore
            use_requests = True
        except Exception:
            use_requests = False

        # --- Preferred: structured payload identical to the example ---
        structured_results = None
        try:
            if isinstance(identifiers, (list, tuple)) and len(identifiers) == 1 and (swift_code or symbol_info is not None):
                instr = "In the following Swift code, find all identifiers related to sensitive logic. Provide the names and reasoning as a JSON object."
                input_blob = _build_structured_input(swift_code or "", symbol_info)
                url_struct = os.environ.get("SWINGFT_SENSITIVE_SERVER_URL_STRUCTURED", "").strip() or "http://localhost:8000/analyze_structured"
                payload_struct = {"instruction": instr, "input": input_blob}

                if use_requests:
                    resp = requests.post(url_struct, json=payload_struct, timeout=60)
                    status = resp.status_code
                    body = resp.text or ""
                else:
                    import urllib.request, urllib.error
                    req = urllib.request.Request(
                        url_struct,
                        data=json.dumps(payload_struct).encode("utf-8"),
                        headers={"Content-Type": "application/json"},
                        method="POST",
                    )
                    with urllib.request.urlopen(req, timeout=60) as r:
                        status = r.getcode()
                        body = r.read().decode("utf-8", errors="replace")

                if status == 200 and body:
                    # Accept either {"output": "<json-string>"} or direct JSON object
                    try:
                        j = json.loads(body)
                    except Exception:
                        j = {}

                    parsed_payload = None
                    if isinstance(j, dict) and "output" in j:
                        try:
                            parsed_payload = json.loads(str(j.get("output") or "").strip())
                        except Exception:
                            parsed_payload = None
                    elif isinstance(j, dict) and ("identifiers" in j or "reasoning" in j):
                        parsed_payload = j
                    else:
                        # If the server returned a raw JSON string as the whole body
                        try:
                            parsed_payload = json.loads(body)
                        except Exception:
                            parsed_payload = None

                    if isinstance(parsed_payload, dict):
                        idents = parsed_payload.get("identifiers") or []
                        reason = str(parsed_payload.get("reasoning", "") or "")
                        out = []
                        for nm in idents:
                            nm_s = str(nm).strip()
                            if not nm_s:
                                continue
                            out.append({"name": nm_s, "exclude": True, "reason": reason})
                        structured_results = out
        except Exception as e:
            print(f"  - 경고: structured 분석 호출 실패: {e}")

        if isinstance(structured_results, list):
            return structured_results

        # --- Fallback: legacy parsed mode ---
        url = os.environ.get("SWINGFT_SENSITIVE_SERVER_URL", "http://localhost:8000/analyze_parsed").strip()
        payload = {"identifiers": list(identifiers)}
        if isinstance(symbol_info, dict) or isinstance(symbol_info, list):
            payload["symbol_info"] = symbol_info
        if isinstance(swift_code, str):
            payload["swift_code"] = swift_code

        try:
            if use_requests:
                resp = requests.post(url, json=payload, timeout=60)
                status = resp.status_code
                if status != 200:
                    print(f"  - 경고: sensitive 서버 응답 오류 HTTP {status}")
                    return None
                data = resp.json()
            else:
                import urllib.request, urllib.error
                req = urllib.request.Request(
                    url,
                    data=json.dumps(payload).encode("utf-8"),
                    headers={"Content-Type": "application/json"},
                    method="POST",
                )
                with urllib.request.urlopen(req, timeout=60) as r:
                    status = r.getcode()
                    body = r.read().decode("utf-8", errors="replace")
                if status != 200:
                    print(f"  - 경고: sensitive 서버 응답 오류 HTTP {status}")
                    return None
                try:
                    data = json.loads(body)
                except Exception as je:
                    print(f"  - 경고: sensitive 서버 JSON 파싱 실패: {je}")
                    return None

            results = data.get("results")
            if isinstance(results, list):
                out = []
                for it in results:
                    if isinstance(it, dict):
                        name = str((it.get("name") or it.get("identifier") or "")).strip()
                        ex = bool(it.get("exclude", it.get("sensitive", False)))
                        reason = str(it.get("reason", ""))
                        if name:
                            out.append({"name": name, "exclude": ex, "reason": reason})
                return out
            return None
        except Exception as e:
            print(f"  - 경고: sensitive 서버 호출 실패: {e}")
            return None

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
            if isinstance(ast_list, list):
                for item in ast_list:
                    if isinstance(item, dict):
                        name = str(item.get("A_name", "")).strip()
                        if name:
                            existing_names.add(name)
        except Exception:
            pass
    
    duplicates = exclude_candidates & existing_names
    if duplicates:
        print(f"  - 중복 식별자 발견: {sorted(list(duplicates))}")
        print("  - 이들은 이미 AST에 존재하지만 isException!=1 상태입니다.")
    
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

    # --- 서버 판단: 식별자별로 소스 스니펫을 포함해 개별 호출 ---
    # 서버 비활성화 경로: 사용자 상호작용만으로 결정 (y/n)
    server_results = []
    proj_root = config.get("project", {}).get("input")
    if isinstance(proj_root, str) and os.path.isdir(proj_root):
        for ident in sorted(list(exclude_candidates)):
            # 간단 프롬프트: 식별자를 난독화에서 제외할지 여부만 묻는다 (UI 모드에선 안내 포함 멀티라인)
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
        # 프로젝트 경로 불명 시에도 사용자 상호작용만으로 결정
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
    decided_to_exclude = set()
    if isinstance(server_results, list) and server_results:
        # If all decisions were made by the user already, apply directly without second review
        if all(isinstance(it, dict) and str(it.get("reason", "")) == "user_decision" for it in server_results):
            for it in server_results:
                try:
                    if it.get("exclude"):
                        decided_to_exclude.add(str(it.get("name")).strip())
                except Exception:
                    continue
            print(f"\n[preflight] 사용자 승인 완료: 제외로 반영 {len(decided_to_exclude)}개")
        else:
            if not _has_ui_prompt():
                print("\n[preflight] 서버 판단 결과 검토 단계")
                print("  - 각 항목의 이유를 확인하고 제외 반영 여부를 선택하세요.")
            for item in server_results:
                try:
                    name = str((item.get("name") or item.get("identifier") or "")).strip()
                    ex = bool(item.get("exclude"))
                    reason = str(item.get("reason", "")).strip()
                    if not name:
                        continue
                    if not _has_ui_prompt():
                        mark = "Y" if ex else "N"
                        print(f"\n----------------------------------------")
                        print(f"식별자 : {name}")
                        print(f"모델 판단 : {'EXCLUDE' if ex else 'KEEP'}")
                        if reason:
                            print(f"이유 : {reason}")
                    # 사용자 승인 요청
                    try:
                        if _has_ui_prompt():
                            prompt = (
                                f"[preflight]\n"
                                f"Identifier: {name}\n"
                                f"Model decision: {'EXCLUDE' if ex else 'KEEP'}\n"
                                f"Reason: {reason if reason else '-'}\n\n"
                                f"Apply this as exclude? [y/N]: "
                            )
                            ans = str(getattr(_cfg, "PROMPT_PROVIDER")(prompt)).strip().lower()
                        else:
                            prompt = f"{name}: {'EXCLUDE' if ex else 'KEEP'} — 이 식별자를 제외 대상으로 반영할까요? [y/N]: "
                            ans = input(prompt).strip().lower()
                    except (EOFError, KeyboardInterrupt):
                        print("\n사용자에 의해 취소되었습니다.")
                        sys.exit(1)
                    approve = ans in ("y", "yes") if ans else ex  # 기본은 모델 판단값
                    if approve:
                        decided_to_exclude.add(name)
                except Exception:
                    continue
            print(f"\n[preflight] 사용자 승인 완료: 제외로 반영 {len(decided_to_exclude)}개")

    if not ast_file:
        print("  - 경고: ast_node.json 경로를 찾지 못해 AST 반영을 건너뜁니다.")
        return

    # Update AST
    try:
        _update_ast_node_exceptions(ast_file, sorted(list(decided_to_exclude)), is_exception=1, allowed_kinds=None, lock_children=False)
        print("  - 처리: ast_node.json 반영 완료 (isException=1)")
    except Exception as e:
        print(f"  - 처리 실패: ast_node.json 반영 중 오류 ({e})")

    # Ensure config consistency
    try:
        from swingft_cli.core.config.writer import write_config
    except Exception:
        write_config = None  # type: ignore

    exclude_obj = config.get("exclude")
    if not isinstance(exclude_obj, dict):
        exclude_obj = {}
        config["exclude"] = exclude_obj
    obf_list = exclude_obj.get("obfuscation")
    if not isinstance(obf_list, list):
        obf_list = []
    changed = False
    for name in sorted(list(decided_to_exclude)):
        if name not in obf_list:
            obf_list.append(name)
            changed = True
    exclude_obj["obfuscation"] = obf_list

    if changed:
        try:
            if write_config is not None:
                write_config(config_path, config)
            else:
                with io.open(config_path, "w", encoding="utf-8") as wf:
                    json.dump(config, wf, ensure_ascii=False, indent=2)
            print("  - 처리: config.json 저장 완료 (exclude.obfuscation)")
        except Exception as e:
            print(f"  - 처리 실패: config.json 저장 오류 ({e})")
    else:
        print("  - 처리: config.json 변경 사항 없음 (이미 포함됨)")

    print("[preflight] Exclude 동기화 완료 ✅")


def _call_llm_server(identifiers):
    """Call LLM server for sensitivity analysis - 식별자별 개별 호출"""
    import requests
    import json
    
    results = []
    
    for i, identifier in enumerate(identifiers):
        print(f"[preflight] LLM 분석 중 ({i+1}/{len(identifiers)}): {identifier}")
        
        try:
            response = requests.post(
                "http://localhost:8000/analyze",
                json={"identifiers": [identifier]},  # 개별 호출
                timeout=30  # 타임아웃 단축
            )
            
            if response.status_code == 200:
                result = response.json()
                results.append({
                    "identifier": identifier,
                    "raw_output": result
                })
                print(f"[preflight] ✅ {identifier} 분석 완료")
            else:
                print(f"[preflight] ❌ {identifier} 분석 실패: {response.status_code}")
                results.append({
                    "identifier": identifier,
                    "raw_output": None,
                    "error": f"HTTP {response.status_code}"
                })
                
        except requests.exceptions.ConnectionError:
            print(f"[preflight] ❌ {identifier} 서버 연결 실패")
            results.append({
                "identifier": identifier,
                "raw_output": None,
                "error": "Connection failed"
            })
        except requests.exceptions.Timeout:
            print(f"[preflight] ❌ {identifier} 응답 시간 초과")
            results.append({
                "identifier": identifier,
                "raw_output": None,
                "error": "Timeout"
            })
        except Exception as e:
            print(f"[preflight] ❌ {identifier} 호출 오류: {e}")
            results.append({
                "identifier": identifier,
                "raw_output": None,
                "error": str(e)
            })
    
    return results


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