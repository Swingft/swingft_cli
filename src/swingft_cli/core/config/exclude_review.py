from __future__ import annotations

import os
import json
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterable
from datetime import datetime

from .exclusions import ast_unwrap as _ast_unwrap
from .exclusions import write_feedback_to_output as _write_feedback_to_output
from .ast_utils import update_ast_node_exceptions as _update_ast_node_exceptions
from .llm_feedback import (
    find_first_swift_file_with_identifier as _find_swift_file_for_ident,
    make_snippet as _make_snippet,
    run_swift_ast_analyzer as _run_ast_analyzer,
    call_exclude_server_parsed as _call_llm_exclude,
    run_local_llm_exclude as _run_local_llm_exclude,
    resolve_ast_symbols as _resolve_ast_symbols,
)


def _preflight_verbose() -> bool:
    try:
        v = os.environ.get("SWINGFT_PREFLIGHT_VERBOSE", "")
        return str(v).strip().lower() in {"1", "true", "yes", "y", "on"}
    except Exception:
        return False


def _append_terminal_log(config: Dict[str, Any], lines: list[str]) -> None:
    try:
        out_dir = str((config.get("project") or {}).get("output") or "").strip()
        if out_dir:
            base = os.path.join(out_dir, "Obfuscation_Report", "preflight")
        else:
            base = os.path.join(os.getcwd(), "Obfuscation_Report", "preflight")
        os.makedirs(base, exist_ok=True)
        path = os.path.join(base, "terminal_preflight.log")
        with open(path, "a", encoding="utf-8") as f:
            f.write(datetime.utcnow().isoformat() + "Z\n")
            for ln in lines:
                f.write(str(ln) + "\n")
            f.write("\n")
    except Exception:
        pass

def _has_ui_prompt() -> bool:
    try:
        import swingft_cli.core.config as _cfg
        return getattr(_cfg, "PROMPT_PROVIDER", None) is not None
    except Exception:
        return False


def save_exclude_review_json(approved_identifiers, project_root: str | None, ast_file_path: str | None) -> str | None:
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
            "source": "exclude_review",
            "decision_basis": "user_confirmation_only",
        }
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)
        if _preflight_verbose():
            print(f"[preflight] 사용자 승인 대상 JSON 저장: {out_path}")
        return out_path
    except Exception as e:
        print(f"[preflight] exclude_review JSON 저장 실패: {e}")
        return None


def save_exclude_pending_json(project_root: str | None, ast_file_path: str | None, candidates) -> str | None:
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
            "source": "exclude_review",
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


def generate_payloads_for_excludes(project_root: str | None, identifiers: list[str]) -> None:
    try:
        if not identifiers:
            return
        out_dir = os.path.join(os.getcwd(), ".swingft", "preflight", "payloads")
        os.makedirs(out_dir, exist_ok=True)
        try:
            from swingft_cli.core.preflight.find_identifiers_and_ast_dual import write_per_identifier_payload_files  # type: ignore
            write_per_identifier_payload_files(project_root or "", identifiers=identifiers, out_dir=out_dir)
            if _preflight_verbose():
                print(f"[preflight] exclude 대상 {len(identifiers)}개에 대한 payload 생성 완료: {out_dir}")
            return
        except Exception as e:
            if _preflight_verbose():
                print(f"[preflight] preflight payload 생성기 사용 불가, 최소 JSON 생성으로 대체: {e}")
        ts = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
        for ident in identifiers:
            name = str(ident).strip()
            if not name:
                continue
            payload = {
                "timestamp": datetime.utcnow().isoformat() + "Z",
                "kind": "exclude_payload",
                "project_input": project_root or "",
                "identifier": name,
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


def process_exclude_sensitive_identifiers(config_path: str, config: Dict[str, Any], ex_names) -> None:
    """Orchestrate exclude candidates check/review and reflect to AST (isException=1)."""
    from swingft_cli.core.config.rules import scan_swift_identifiers
    project_root = config.get("project", {}).get("input")
    if not project_root or not os.path.isdir(project_root):
        print("[preflight] project.input 경로가 없어 프로젝트 식별자 스캔을 건너뜁니다.")
        return

    project_identifiers = set(scan_swift_identifiers(project_root))
    if not project_identifiers:
        print("[preflight] 프로젝트에서 식별자를 찾지 못했습니다.")
        return

    # Build candidates from config.exclude.obfuscation
    exclude_candidates = set()
    items = (config.get("exclude", {}) or {}).get("obfuscation", []) or []
    if isinstance(items, list):
        for item in items:
            if not isinstance(item, str) or not item.strip():
                continue
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
        #print("[preflight] Exclude(obfuscation) 후보 중 AST(excluded) 기준으로 새로 반영할 식별자 없음 ✅")
        return

    #print(f"\n[preflight] Exclude(obfuscation) candidates found: {len(exclude_candidates)}")

    # Policy
    _pf = config.get("preflight", {}) if isinstance(config.get("preflight"), dict) else {}
    ex_policy = str(
        _pf.get("conflict_policy")
        or _pf.get("exclude_candidate_policy")
        or "ask"
    ).strip().lower()

    # Locate ast_node.json
    env_ast = os.environ.get("SWINGFT_AST_NODE_PATH", "").strip()
    if env_ast and os.path.exists(env_ast):
        ast_file = Path(env_ast)
    else:
        ast_candidates = [
            os.path.join(os.getcwd(), "Obfuscation_Pipeline", "AST", "output", "ast_node.json"),
            os.path.join(os.getcwd(), "AST", "output", "ast_node.json"),
        ]
        ast_file = next((Path(p) for p in ast_candidates if Path(p).exists()), None)

    # Collect existing names in AST
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
                        for key in CONTAINER_KEYS:
                            ch = cur.get(key)
                            if isinstance(ch, list):
                                for c in ch:
                                    _collect_names(c)
                            elif isinstance(ch, dict):
                                _collect_names(ch)
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

    # capture buffer for external session log
    _capture: list[str] = []

    duplicates = exclude_candidates & existing_names
    if duplicates:
        _list = sorted(list(duplicates))
        _capture.append("[preflight] Exclude candidates overlap with existing AST identifiers. It may cause conflicts.")
        _capture.append(f"Candidates: {len(_list)} items")
        for nm in _list:
            _capture.append(f"  - {nm}")
        # 터미널 출력은 ask 모드에서만 노출
        if (ex_policy == "ask"):
            print("[preflight] Exclude candidates overlap with existing AST identifiers. It may cause conflicts.")
            print(f"Candidates: {len(_list)} items")
            for nm in _list:
                print(f"  - {nm}")

    # Persist pending set
    try:
        save_exclude_pending_json(project_root, str(ast_file) if ast_file else None, sorted(list(exclude_candidates)))
    except Exception as _e:
        print(f"[preflight] exclude_pending JSON 저장 경고: {_e}")

    # Create PENDING payloads before y/N
    if ex_policy != "skip":
        try:
            from swingft_cli.core.preflight.find_identifiers_and_ast_dual import write_per_identifier_payload_files  # type: ignore
            _pending_dir = os.path.join(os.getcwd(), ".swingft", "preflight", "payloads", "pending")
            os.makedirs(_pending_dir, exist_ok=True)
            write_per_identifier_payload_files(
                project_root or "",
                identifiers=sorted(list(exclude_candidates)),
                out_dir=_pending_dir,
            )
            if _preflight_verbose():
                print(f"[preflight] PENDING payloads 생성 완료: {len(exclude_candidates)}개 → {_pending_dir}")
        except Exception as _e:
            print(f"[preflight] PENDING payloads 생성 경고: {_e}")

    # Decision gathering (LLM off; use y/N)
    decided_to_exclude = set()
    if ex_policy == "skip":
        # 터미널 출력 없이 파일에만 기록
        try:
            fb = [
                "[preflight] Exclude candidates skipped by policy",
                f"Candidates: {len(exclude_candidates)}",
                f"Sample: {', '.join(sorted(list(exclude_candidates))[:20])}",
                f"Policy: {ex_policy}",
                f"Target output: {str((config.get('project') or {}).get('output') or '').strip()}",
                f"AST: {str(ast_file)}",
            ]
            _write_feedback_to_output(config, "exclude_candidates_skipped", "\n".join(fb))
            _append_terminal_log(config, fb)
            # 세션 로그로도 남김
            try:
                _write_feedback_to_output(config, "exclude_session", "\n".join(_capture + ["", *fb]))
            except Exception:
                pass
        except Exception:
            pass
        return
    elif ex_policy == "force":
        decided_to_exclude = set(exclude_candidates)
        # 터미널 출력 없이 파일에만 기록
        # Write force action feedback (with terminal snapshot placeholder)
        try:
            fb = [
                "[preflight] Exclude candidates forced",
                f"Candidates: {len(exclude_candidates)}",
                f"Sample: {', '.join(sorted(list(exclude_candidates))[:20])}",
                f"Policy: {ex_policy}",
                f"Target output: {str((config.get('project') or {}).get('output') or '').strip()}",
                f"AST: {str(ast_file)}",
            ]
            _write_feedback_to_output(config, "exclude_candidates_forced", "\n".join(fb))
            _append_terminal_log(config, fb)
            try:
                _write_feedback_to_output(config, "exclude_session", "\n".join(_capture + ["", *fb]))
            except Exception:
                pass
        except Exception:
            pass
    else:
        # ask 모드에서 LLM 판정과 사용자 확인을 함께 수행 (환경변수로 온/오프)
        use_llm = str(os.environ.get("SWINGFT_PREFLIGHT_EXCLUDE_USE_LLM", "1")).strip().lower() in {"1","true","yes","y","on"}
        prefer_local = str(os.environ.get("SWINGFT_EXCLUDE_LLM_LOCAL", "1")).strip().lower() in {"1","true","yes","y","on"}
        for ident in sorted(list(exclude_candidates)):
            try:
                if _has_ui_prompt():
                    import swingft_cli.core.config as _cfg
                    llm_note = ""
                    if use_llm and isinstance(project_root, str) and project_root.strip():
                        # 스니펫 및 AST 심볼 정보 수집
                        found = _find_swift_file_for_ident(project_root, ident)
                        swift_path, swift_text = (found or (None, None)) if isinstance(found, tuple) else (None, None)
                        snippet = _make_snippet(swift_text or "", ident) if swift_text else ""
                        ast_info = _resolve_ast_symbols(project_root, swift_path, ident)
                        # LLM 호출
                        try:
                            if prefer_local:
                                llm_res = _run_local_llm_exclude(ident, snippet, ast_info)
                            else:
                                llm_res = _call_llm_exclude([ident], symbol_info=ast_info, swift_code=snippet)
                        except Exception as _llm_e:
                            llm_res = None
                        # 판정 요약
                        if isinstance(llm_res, list) and llm_res:
                            first = llm_res[0]
                            is_ex = bool(first.get("exclude", True))
                            reason = str(first.get("reason", "")).strip()
                            # LLM이 비민감(keep)으로 판단 시 사용자 프롬프트 생략
                            if not is_ex:
                                _capture.append(f"[preflight] LLM auto-skip (keep): {ident}")
                                if reason:
                                    _capture.append(f"  - reason: {reason[:200]}")
                                # 이 항목은 제외하지 않음 → 다음 식별자로 진행
                                continue
                            llm_note = f"\n  - LLM suggests: {'exclude' if is_ex else 'keep'}\n    reason: {reason[:200]}"
                    prompt = (
                        f"[preflight]\n"
                        f"Exclude candidate detected.\n"
                        f"  - identifier: {ident}{llm_note}\n\n"
                        f"Exclude this identifier from obfuscation? [y/N]: "
                    )
                    _capture.append("[preflight]")
                    _capture.append(f"Exclude candidate detected.\n  - identifier: {ident}")
                    if llm_note:
                        _capture.append(llm_note.strip())
                    ans = str(getattr(_cfg, "PROMPT_PROVIDER")(prompt)).strip().lower()
                else:
                    ans = input(f"식별자 '{ident}'를 난독화에서 제외할까요? [y/N]: ").strip().lower()
            except (EOFError, KeyboardInterrupt):
                print("\n사용자에 의해 취소되었습니다.")
                raise SystemExit(1)
            if ans in ("y", "yes"):
                decided_to_exclude.add(ident)

    if decided_to_exclude:
        #print(f"\n[preflight] 사용자 승인 완료: 제외로 반영 {len(decided_to_exclude)}개")
        #_capture.append(f"[preflight] 사용자 승인 완료: 제외로 반영 {len(decided_to_exclude)}개")
        try:
            save_exclude_review_json(sorted(list(decided_to_exclude)), project_root, str(ast_file) if ast_file else None)
        except Exception as _e:
            print(f"[preflight] exclude_review JSON 저장 경고: {_e}")
        try:
            generate_payloads_for_excludes(project_root, sorted(list(decided_to_exclude)))
        except Exception as _e:
            print(f"[preflight] exclude payload 생성 경고: {_e}")

    # ask 모드 세션 로그 저장
    try:
        if ex_policy == "ask":
            _write_feedback_to_output(config, "exclude_session", "\n".join(_capture))
    except Exception:
        pass

    if not ast_file:
        # 조용히 스킵 (Stage 1 스킵 시 정상)
        return

    try:
        _update_ast_node_exceptions(str(ast_file), sorted(list(decided_to_exclude)), is_exception=1, allowed_kinds=None, lock_children=False)
        #print("  - 처리: ast_node.json 반영 완료 (isException=1)")
    except Exception as e:
        print(f"  - 처리 실패: ast_node.json 반영 중 오류 ({e})")


