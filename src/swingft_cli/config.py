"""
Facade for config APIs, re-exporting split core modules.
"""
from __future__ import annotations

from typing import Any, Dict, Iterable, List, Tuple

from swingft_cli.core.config.loader import load_config_or_exit
from swingft_cli.core.config.rules import (
    extract_rule_patterns,
    summarize_identifier_presence,
    clear_identifier_cache,
)

# Backwards-compatible APIs
from swingft_cli.core.config.rules import scan_swift_identifiers as scan_swift_identifiers  # re-export

def summarize_risks(config: Dict[str, Any]) -> List[Tuple[str, str]]:
    from swingft_cli.core.config.rules import fnmatch, _match_pattern_set  # type: ignore
    # 재구현 대신, 기존 동작을 유지하기 위해 간단히 동일한 로직을 유지
    ex_obf = list(config.get("exclude", {}).get("obfuscation", []) or [])
    in_obf = list(config.get("include", {}).get("obfuscation", []) or [])
    ex_enc = list(config.get("exclude", {}).get("encryption", []) or [])
    in_enc = list(config.get("include", {}).get("encryption", []) or [])

    def _only_str(xs: Iterable[Any]) -> List[str]:
        out: List[str] = []
        for x in xs:
            if isinstance(x, str):
                s = x.strip()
                if s:
                    out.append(s)
        return out

    ex_obf, in_obf, ex_enc, in_enc = map(_only_str, (ex_obf, in_obf, ex_enc, in_enc))

    risks: List[Tuple[str, str]] = []
    conflict = set(in_obf) & set(ex_obf)
    if conflict:
        risks.append(("obfuscation에서 include와 exclude가 충돌", ", ".join(list(conflict)[:5])))
    conflict = set(in_enc) & set(ex_enc)
    if conflict:
        risks.append(("encryption에서 include와 exclude가 충돌", ", ".join(list(conflict)[:5])))

    for title, arr in (("obfuscation", in_obf + ex_obf), ("encryption", in_enc + ex_enc)):
        if any(p == "*" for p in arr):
            risks.append((f"{title}에 '*' 단독 패턴 사용", "모든 항목을 포괄합니다. 의도된 것인지 확인하세요."))

    return risks

def preflight_and_confirm(config: Dict[str, Any], auto_yes: bool = False) -> bool:
    from swingft_cli.core.config.rules import summarize_identifier_presence as sip
    import sys
    from swingft_cli.core.config.schema import _warn

    risks: List[Tuple[str, str]] = []
    risks.extend(summarize_risks(config))

    project_root = (
        config.get("project", {}).get("input") if isinstance(config.get("project"), dict) else None
    )
    if project_root:
        risks.extend(sip(config, project_root))
    else:
        _warn("project.input 이 지정되지 않았습니다. 식별자 존재 여부 검증을 생략합니다.")

    if not risks:
        return True

    print("프리플라이트 점검 결과 경고가 발견되었습니다:")
    for title, detail in risks:
        if detail:
            print(f" - {title}: {detail}")
        else:
            print(f" - {title}")

    if auto_yes:
        print("auto_yes=True 로 설정되어 자동으로 계속 진행합니다.")
        return True

    try:
        is_tty = sys.stdin.isatty()
    except Exception:
        is_tty = False

    if not is_tty:
        _warn("표준입력이 터미널이 아니므로 기본값(중단)을 적용합니다. --yes 플래그나 auto_yes=True 사용을 고려하세요.")
        return False

    try:
        ans = input("경고가 있습니다. 계속 진행하시겠습니까? [y/N]: ").strip().lower()
    except EOFError:
        _warn("입력을 읽을 수 없습니다(EOF). 기본값(중단)을 적용합니다.")
        return False
    except KeyboardInterrupt:
        print("\n사용자에 의해 취소되었습니다.", file=sys.stderr)
        return False

    return ans in ("y", "yes")

def summarize_risks_and_confirm(config: Dict[str, Any], auto_yes: bool = False) -> bool:
    return preflight_and_confirm(config, auto_yes=auto_yes)





