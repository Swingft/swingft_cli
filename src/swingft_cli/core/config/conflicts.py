from __future__ import annotations

import os
import json
from pathlib import Path
from datetime import datetime
from typing import Any, Dict, Set

from .ast_utils import update_ast_node_exceptions as _update_ast_node_exceptions
from .exclusions import ast_unwrap as _ast_unwrap
from .exclusions import write_feedback_to_output as _write_feedback_to_output


def _has_ui_prompt() -> bool:
    try:
        import swingft_cli.core.config as _cfg
        return getattr(_cfg, "PROMPT_PROVIDER", None) is not None
    except Exception:
        return False


def _preflight_print(msg: str) -> None:
    if not _has_ui_prompt():
        print(msg)


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


def check_exception_conflicts(config_path: str, config: Dict[str, Any]) -> Set[str]:
    env_ast = os.environ.get("SWINGFT_AST_NODE_PATH", "").strip()
    if env_ast and os.path.exists(env_ast):
        ast_file = Path(env_ast)
    else:
        ast_candidates = [
            os.path.join(os.getcwd(), "Obfuscation_Pipeline", "AST", "output", "ast_node.json"),
            os.path.join(os.getcwd(), "AST", "output", "ast_node.json"),
        ]
        ast_file = next((Path(p) for p in ast_candidates if Path(p).exists()), None)

    if not ast_file:
        # 조용히 스킵 (Stage 1 스킵 시 정상)
        return set()

    try:
        apply_cfg = str(os.environ.get("SWINGFT_APPLY_CONFIG_TO_AST", "")).strip().lower() in {"1", "true", "yes", "y", "on"}
        if apply_cfg and ast_file and ast_file.exists():
            items = []
            try:
                items = config.get("exclude", {}).get("obfuscation", []) or []
            except Exception:
                items = []
            if isinstance(items, list) and items:
                _update_ast_node_exceptions(
                    str(ast_file), items, is_exception=1, lock_children=True, quiet=True
                )
                if _preflight_verbose():
                    print("[preflight] apply-config → AST: applied exclude.obfuscation to isException=1")
        elif _preflight_verbose():
            print("[preflight] apply-config DRY-RUN: not applying to AST (set SWINGFT_APPLY_CONFIG_TO_AST=1 to apply)")
    except Exception:
        pass

    try:
        with open(ast_file, 'r', encoding='utf-8') as f:
            ast_list = json.load(f)
    except Exception:
        return set()

    ex_names: Set[str] = set()
    CONTAINER_KEYS = ("G_members", "children", "members", "extension", "node")

    def _walk(obj):
        if isinstance(obj, dict):
            cur = _ast_unwrap(obj)
            if isinstance(cur, dict):
                nm = str(cur.get("A_name", "")).strip()
                if nm and int(cur.get("isException", 0)) == 1:
                    ex_names.add(nm)
                for key in CONTAINER_KEYS:
                    ch = cur.get(key)
                    if isinstance(ch, list):
                        for c in ch:
                            _walk(c)
                    elif isinstance(ch, dict):
                        _walk(ch)
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

    _walk(ast_list)
    if not ex_names:
        return set()

    # capture buffer for include session logs
    _capture: list[str] = []
    wildcard_patterns = []
    for section in ("include", "exclude"):
        for category in ("obfuscation",):
            items = config.get(section, {}).get(category, [])
            if isinstance(items, list):
                for item in items:
                    if isinstance(item, str) and item.strip() == "*":
                        wildcard_patterns.append(f"{section}.{category}")
    if wildcard_patterns:
        _capture.append("[preflight] ⚠️  '*' 단독 패턴 사용 감지:")
        for pattern in wildcard_patterns:
            _capture.append(f"  - {pattern}: 모든 식별자에 적용됩니다")
        _capture.append("  - 이는 의도된 설정인지 확인이 필요합니다.")
        try:
            prompt_msg = "계속 진행하시겠습니까? [y/N]: "
            if _has_ui_prompt():
                import swingft_cli.core.config as _cfg
                ans = str(getattr(_cfg, "PROMPT_PROVIDER")(prompt_msg)).strip().lower()
            else:
                ans = input(prompt_msg).strip().lower()
            if ans not in ("y", "yes"):
                print("사용자에 의해 취소되었습니다.")
                raise SystemExit(1)
        except (EOFError, KeyboardInterrupt):
            print("\n사용자에 의해 취소되었습니다.")
            raise SystemExit(1)

    config_names = set()
    for category in ("obfuscation",):
        items = config.get("include", {}).get(category, [])
        if isinstance(items, list):
            for item in items:
                if isinstance(item, str) and item.strip():
                    item = item.strip()
                    if "*" not in item and "?" not in item:
                        config_names.add(item)
                    else:
                        import fnmatch
                        for ex_name in ex_names:
                            if fnmatch.fnmatchcase(ex_name, item):
                                config_names.add(ex_name)

    conflicts = config_names & ex_names
    _capture.append(f"[preflight] Config include identifiers: {sorted(list(config_names))}")
    _capture.append(f"[preflight] Conflicts found: {len(conflicts)} items")
    _preflight_print("")  # suppress terminal spam; rely on session logs or ask mode prints
    if conflicts:
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
                    str(ast_file), conflicts, is_exception=0,
                    allowed_kinds={"function"}, lock_children=True,
                    quiet=_has_ui_prompt()
                )
                # Write force action feedback
                try:
                    out_dir = str((config.get("project") or {}).get("output") or "").strip()
                    fb = [
                        "[preflight] Include conflict forced",
                        f"Conflicts: {len(conflicts)}",
                        f"Sample: {', '.join(sample_all[:20])}",
                        f"Policy: {policy}",
                        f"Target output: {out_dir}",
                        f"AST: {str(ast_file)}",
                    ]
                    _write_feedback_to_output(config, "include_conflict_forced", "\n".join(fb))
                    _append_terminal_log(config, fb)
                    # session copy
                    try:
                        _write_feedback_to_output(config, "include_session", "\n".join(_capture + ["", *fb]))
                    except Exception:
                        pass
                except Exception:
                    pass
            elif policy == "skip":
                # 터미널 출력 없이 파일에만 기록
                try:
                    fb = [
                        "[preflight] Include conflict skipped by policy",
                        f"Conflicts: {len(conflicts)}",
                        f"Sample: {', '.join(sample_all[:20])}",
                        f"Policy: {policy}",
                        f"Target output: {str((config.get('project') or {}).get('output') or '').strip()}",
                        f"AST: {str(ast_file)}",
                    ]
                    _write_feedback_to_output(config, "include_conflict_skipped", "\n".join(fb))
                    _append_terminal_log(config, fb)
                    try:
                        _write_feedback_to_output(config, "include_session", "\n".join(_capture + ["", *fb]))
                    except Exception:
                        pass
                except Exception:
                    pass
            else:
                if _has_ui_prompt():
                    import swingft_cli.core.config as _cfg
                    full_list = ""
                    try:
                        if sample_all:
                            full_list = "\n  - " + "\n  - ".join(sample_all)
                    except Exception:
                        full_list = ""
                    prompt_msg = (
                        "[preflight] "
                        "The provided include entries conflict with exclude rules. It may cause conflicts.\n"
                        f"Collision identifiers: {len(conflicts)} items"
                        f"{'' if sample_all else ''}"
                        f"{full_list}\n\n"
                        "Do you really want to include these identifiers in obfuscation? [y/N]: "
                    )
                    ans = str(getattr(_cfg, "PROMPT_PROVIDER")(prompt_msg)).strip().lower()
                    _capture.append("[preflight] The provided include entries conflict with exclude rules. It may cause conflicts.")
                    _capture.append(f"Collision identifiers: {len(conflicts)} items")
                    _capture.extend(["  - " + s for s in sample_all])
                else:
                    full_list = ""
                    try:
                        if sample_all:
                            full_list = "\n  - " + "\n  - ".join(sample_all)
                    except Exception:
                        full_list = ""
                    prompt_msg = (
                        "[preflight]\n"
                        "The provided include entries conflict with exclude rules.\n"
                        f"  - Collision identifiers: {len(conflicts)} items"
                        f"{':' if sample_all else ''}"
                        f"{full_list}\n\n"
                        "Do you really want to include these identifiers in obfuscation? [y/N]: "
                    )
                    ans = input(prompt_msg).strip().lower()
                if ans in ("y", "yes"):
                    _update_ast_node_exceptions(
                        str(ast_file), conflicts, is_exception=0,
                        allowed_kinds={"function"}, lock_children=True,
                        quiet=_has_ui_prompt()
                    )
                try:
                    # save session for ask mode
                    _write_feedback_to_output(config, "include_session", "\n".join(_capture))
                except Exception:
                    pass
                else:
                    print("[preflight] 사용자가 충돌 항목 제거를 취소했습니다.")
        except (EOFError, KeyboardInterrupt):
            print("\n사용자에 의해 취소되었습니다.")
            raise SystemExit(1)
    else:
        _preflight_print("[preflight] Include 대상과 제외대상 간 충돌 없음")

    return ex_names


