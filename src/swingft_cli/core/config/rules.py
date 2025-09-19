from __future__ import annotations

from typing import Any, Dict, Iterable, List, Tuple
import os
import re
import fnmatch

from .schema import _warn, EXCLUDED_DIRS

_SWIFT_NAME = r"[A-Za-z_][A-Za-z0-9_]*"
# idf.py와 완전히 동일한 Swift 식별자 패턴
patterns = [
    # 타입 선언: class, struct, enum, protocol, actor, extension
    re.compile(r'\b(class|struct|enum|protocol|actor|extension)\s+([A-Za-z_][A-Za-z0-9_]*)'),
    # 함수 선언: func name() 또는 func name(param: Type)
    re.compile(r'\bfunc\s+([A-Za-z_][A-Za-z0-9_]*)'),
    # 변수/상수 선언: var name, let name
    re.compile(r'\b(var|let)\s+([A-Za-z_][A-Za-z0-9_]*)'),
    # 타입 별칭: typealias
    re.compile(r'\btypealias\s+([A-Za-z_][A-Za-z0-9_]*)'),
]

_IDENT_CACHE: Dict[str, List[str]] = {}
# 식별자 캐시 초기화
def clear_identifier_cache() -> None:
    _IDENT_CACHE.clear()
# 대상 프로젝트 내의 모든 식별자 수집
def scan_swift_identifiers(root: str) -> List[str]:
    cached = _IDENT_CACHE.get(root)
    if cached is not None:
        return list(cached)
    names: List[str] = []
    seen = set()
    if not root or not os.path.isdir(root):
        _IDENT_CACHE[root] = []
        return []
    for dirpath, dirnames, filenames in os.walk(root, followlinks=True):
        dirnames[:] = [d for d in dirnames if d not in EXCLUDED_DIRS]
        for fn in filenames:
            if fn.endswith(".swift"):
                path = os.path.join(dirpath, fn)
                try:
                    with open(path, "r", encoding="utf-8", errors="ignore") as f:
                        text = f.read()
                except OSError:
                    continue
                for pattern in patterns:
                    for m in pattern.findall(text):
                        if isinstance(m, tuple):
                            name = m[1]  # 두 번째 그룹 (실제 이름)
                        else:
                            name = m   # 단일 그룹
                        if name and name not in seen:
                            seen.add(name)
                            names.append(name)
    _IDENT_CACHE[root] = list(names)
    return names
# 와일드카드 패턴 확인
def _is_wildcard(pattern: str) -> bool:
    return any(ch in pattern for ch in ("*", "?"))
# 패턴 매칭
def _match_pattern_set(pattern: str, identifiers: Iterable[str]) -> List[str]:
    return [idn for idn in identifiers if fnmatch.fnmatchcase(idn, pattern)]

def summarize_identifier_presence(config: Dict[str, Any], project_root: str) -> List[Tuple[str, str]]:
    risks: List[Tuple[str, str]] = []
    if not project_root or not os.path.isdir(project_root):
        _warn("project.input 경로가 없거나 디렉터리가 아닙니다. 식별자 스캔을 건너뜁니다.")
        return risks
    identifiers = scan_swift_identifiers(project_root)
    id_set = set(identifiers)
    if not identifiers:
        has_subdirs = False
        has_swift = False
        for _dp, _dns, _fns in os.walk(project_root, followlinks=True):
            if _dns:
                has_subdirs = True
            if any(fn.endswith('.swift') for fn in _fns):
                has_swift = True
                break
        detail = "경로와 소스 파일 존재 여부를 확인하세요."
        if has_subdirs and not has_swift:
            detail += " 상위 폴더만 가리키는 경우가 많습니다. 실제 코드가 있는 모듈 루트(예: Sources/<ModuleName> 또는 App 소스 디렉터리)를 지정하세요."
        risks.append(("프로젝트에서 Swift 식별자를 찾지 못했습니다", detail))
        return risks

    def _check_arr(sec: str, key: str):
        arr = config.get(sec, {}).get(key, []) or []
        if isinstance(arr, str):
            arr = [arr]
        missing_literals: List[str] = []
        empty_wildcards: List[str] = []
        broad_patterns: List[str] = []
        for raw in arr:
            if not isinstance(raw, str):
                continue
            p = raw.strip()
            if not p:
                continue
            if p == "*":
                broad_patterns.append(p)
                continue
            if _is_wildcard(p):
                matches = _match_pattern_set(p, id_set)
                if not matches:
                    empty_wildcards.append(p)
            else:
                if p not in id_set:
                    missing_literals.append(p)
        if broad_patterns:
            risks.append((f"{sec}.{key}: '*' 단독 패턴 사용", "모든 식별자에 적용됩니다. 의도 여부를 재확인하세요."))
        if empty_wildcards:
            risks.append((f"{sec}.{key}: 와일드카드가 어떠한 식별자와도 매칭되지 않음", ", ".join(empty_wildcards[:5]) + (" ..." if len(empty_wildcards) > 5 else "")))
        if missing_literals:
            risks.append((f"{sec}.{key}: 프로젝트에 존재하지 않는 리터럴 식별자", ", ".join(missing_literals[:5]) + (" ..." if len(missing_literals) > 5 else "")))

    _check_arr("exclude", "obfuscation")
    _check_arr("include", "obfuscation")
    _check_arr("exclude", "encryption")
    _check_arr("include", "encryption")
    return risks

def extract_rule_patterns(config: Dict[str, Any]) -> Dict[str, List[str]]:
    def _ls(sec: str, key: str) -> List[str]:
        val = config.get(sec, {}).get(key, [])
        if isinstance(val, list):
            return [str(v) for v in val if isinstance(v, (str,)) and v.strip()]
        elif isinstance(val, str):
            s = val.strip()
            return [s] if s else []
        return []
    return {
        "obfuscation_exclude": _ls("exclude", "obfuscation"),
        "obfuscation_include": _ls("include", "obfuscation"),
        "encryption_exclude": _ls("exclude", "encryption"),
        "encryption_include": _ls("include", "encryption"),
    }




