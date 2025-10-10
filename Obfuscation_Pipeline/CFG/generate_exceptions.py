#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
generate_exceptions.py (Whitelist approach)

- Swift 프로젝트를 스캔하여 '확실히 안전'하지 않은 모든 것을 찾아 예외 목록을 생성합니다.
- 매우 보수적으로 동작하여 안정성을 극대화합니다.
- 단, 프로토콜/액터/글로벌-액터 기반의 *이름 단위* 제외는 기본 OFF (원하면 플래그로 켜세요). 실제 안전성 판단은 last.py에서 구조적으로 수행됩니다.
"""

import os
import re
import json
import argparse
from pathlib import Path
from typing import Dict, List, Set

# --- Precompiled regex patterns (module-scope) ---
TYPE_DECL_RE = re.compile(r"^\s*(?:public|internal|fileprivate|private)?\s*(?:final|open)?\s*\b(class|struct|enum|actor|protocol|extension)\s+([A-Za-z_][A-Za-z_0-9]*)", re.MULTILINE)
FUNC_DECL_RE = re.compile(r"^\s*(?P<line>(?:@[\w:]+\s*)*\s*(?P<mods>(?:\w+\s+)*)func\s+(?P<name>\w+)\s*(?:<[^>]+>)?\s*\((?P<params>[^)]*)\).*)", re.MULTILINE)
COMPILER_DIRECTIVE_RE = re.compile(r"^\s*#(if|else|elseif|endif)", re.MULTILINE)
NESTED_TYPE_RE = re.compile(r"\{\s*(?:public|internal|fileprivate|private)?\s*\b(class|struct|enum)\s+[A-Za-z_]", re.DOTALL)

# --- Simple helpers to extract protocol requirements (functions only) ---
def _strip_comments(text: str) -> str:
    """
    Remove line ('// ...') and block ('/* ... */') comments to stabilize parsing.
    This is a light scrub; it's sufficient for locating protocol blocks and func signatures.
    """
    # Remove block comments first
    text = re.sub(r"/\*.*?\*/", "", text, flags=re.DOTALL)
    # Remove line comments
    text = re.sub(r"//.*?$", "", text, flags=re.MULTILINE)
    return text

def _find_protocol_blocks(text: str) -> List[Dict[str, str]]:
    """
    Return a list of dicts with {'name': <protocolName>, 'body': <inside braces>}.
    Uses a brace-depth scan starting from 'protocol <Name> ... {' locations.
    """
    results: List[Dict[str, str]] = []
    # Find protocol headers followed by '{'
    for m in re.finditer(r"\bprotocol\s+([A-Za-z_]\w*)\b[^\\{]*\{", text):
        name = m.group(1)
        i = m.end() - 1  # position at '{'
        depth = 0
        start_body = i + 1
        j = i
        while j < len(text):
            ch = text[j]
            if ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    # body is between start_body and j
                    results.append({"name": name, "body": text[start_body:j]})
                    break
            j += 1
    return results

def _find_actor_blocks(text: str) -> List[Dict[str, str]]:
    """Return a list of dicts with {'name': <actorName>, 'body': <inside braces>}.
    Simple brace-depth scan starting from 'actor <Name> {' locations.
    """
    results: List[Dict[str, str]] = []
    for m in re.finditer(r"\bactor\s+([A-Za-z_]\w*)\b[^\\{]*\{", text):
        name = m.group(1)
        i = m.end() - 1
        depth = 0
        start_body = i + 1
        j = i
        while j < len(text):
            ch = text[j]
            if ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    results.append({"name": name, "body": text[start_body:j]})
                    break
            j += 1
    return results

def _find_type_like_blocks(text: str) -> List[Dict[str, str]]:
    """Return a list of dicts with {'kind': kind, 'name': name, 'body': inside} for
    class/struct/enum/actor/extension blocks.
    """
    results: List[Dict[str, str]] = []
    for m in re.finditer(r"\b(class|struct|enum|actor|extension)\s+([A-Za-z_]\w*)\b[^\\{]*\{", text):
        kind = m.group(1)
        name = m.group(2)
        i = m.end() - 1
        depth = 0
        start_body = i + 1
        j = i
        while j < len(text):
            ch = text[j]
            if ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    results.append({"kind": kind, "name": name, "body": text[start_body:j]})
                    break
            j += 1
    return results


def _top_level_func_matches(body: str, func_re: re.Pattern) -> List[re.Match]:
    """Return only those func matches that appear at *top level* of the given body
    (i.e., not nested inside another '{...}' such as a local function/closure).
    Assumes comments were stripped already.
    """
    matches: List[re.Match] = []
    # Precompute simple brace depth per index
    depth = 0
    depth_map = [0] * (len(body) + 1)
    for i, ch in enumerate(body):
        if ch == '{':
            depth += 1
        elif ch == '}':
            depth = max(0, depth - 1)
        depth_map[i] = depth
    for m in func_re.finditer(body):
        # If the depth at the start of the match is 0, it is top-level within the type body
        if depth_map[m.start()] == 0:
            matches.append(m)
    return matches

def _extract_protocol_func_names(proto_body: str) -> List[str]:
    """
    From the inside of a protocol block, extract declared function names.
    We intentionally ignore properties/associatedtypes/subscripts.
    """
    names: List[str] = []
    # Look for 'func <name>('; protocol requirements do not have bodies here.
    for fm in re.finditer(r"\bfunc\s+([A-Za-z_]\w*)\s*(?:<[^>]*>)?\s*\(", proto_body):
        names.append(fm.group(1))
    return names

# --- Helpers: robust default-parameter detection ---

def _split_params_top(params_src: str) -> List[str]:
    """Split a Swift parameter list by top-level commas (ignoring commas inside (), [], <>).
    This lets us examine each parameter segment reliably even when the list spans lines
    or contains function types/tuples/generics.
    """
    parts: List[str] = []
    if not params_src:
        return parts
    buf = []
    d_par = d_brk = d_ang = 0
    i = 0
    while i < len(params_src):
        ch = params_src[i]
        if ch == '(': d_par += 1
        elif ch == ')': d_par = max(0, d_par - 1)
        elif ch == '[': d_brk += 1
        elif ch == ']': d_brk = max(0, d_brk - 1)
        elif ch == '<': d_ang += 1
        elif ch == '>': d_ang = max(0, d_ang - 1)
        if ch == ',' and d_par == 0 and d_brk == 0 and d_ang == 0:
            parts.append(''.join(buf))
            buf = []
        else:
            buf.append(ch)
        i += 1
    if buf:
        parts.append(''.join(buf))
    return parts


def _has_param_default(params_src: str) -> bool:
    """Return True if any top-level parameter has a default value (contains '=' at top level).
    This avoids false positives from nested expressions and works across newlines.
    """
    for seg in _split_params_top(params_src or ""):
        if '=' in seg:
            return True
    return False

def iter_swift_files(root: Path) -> List[Path]:
    return list(root.rglob("*.swift"))

def is_ui_path(file_path: Path) -> bool:
    """
    Swift 프로젝트에서 UI 관련 파일 여부를 판별합니다.
    (UI 파일이면 True 반환 → 난독화/처리에서 제외 가능)
    """
    p = str(file_path).replace("\\", "/").lower()
    base = file_path.name.lower()

    # 경로 기반 (폴더명)
    ui_dirs = ("/view/", "/views/", "/ui/", "/screens/", "/storyboard/", "/xib/")
    if any(seg in p for seg in ui_dirs):
        return True

    # 파일명 패턴 기반
    ui_suffixes = (
        "view.swift",
        "viewcontroller.swift",
        "cell.swift",
        "tableviewcell.swift",
        "collectionviewcell.swift",
        "headerview.swift",
        "footerview.swift",
        "button.swift",
        "imageview.swift",
        "stackview.swift",
        "label.swift"
    )
    if any(base.endswith(suffix) for suffix in ui_suffixes):
        return True

    # UI 유틸/테마 관련
    ui_keywords = ("theme", "color", "font", "style", "uihelper")
    if any(kw in base for kw in ui_keywords):
        return True

    return False

def analyze_and_generate_exceptions(
    project_path: Path,
    *,
    exclude_extensions: bool = False,
    exclude_protocol_requirements: bool = True,
    exclude_actors: bool = True,
    exclude_global_actors: bool = True
) -> List[Dict]:
    swift_files = iter_swift_files(project_path)
    potential_rules: Dict[str, Dict[str, str]] = {}

    # (정규식은 모듈 전역 상수를 사용)

    for file_path in swift_files:
        try:
            content = file_path.read_text(encoding="utf-8")

            # --- Optionally exclude protocol-declared methods ---
            if exclude_protocol_requirements:
                try:
                    scrub = _strip_comments(content)
                    for pb in _find_protocol_blocks(scrub):
                        for fname in _extract_protocol_func_names(pb["body"]):
                            if fname not in potential_rules:
                                potential_rules[fname] = {"kind": "function", "reason": f"Protocol requirement ({file_path.name})"}
                except Exception as _e:
                    # Best-effort only; ignore parsing errors and continue.
                    pass

            # Optionally exclude actor isolated instance methods (lack 'nonisolated' and 'static')
            if exclude_actors:
                try:
                    scrub2 = _strip_comments(content)
                    for ab in _find_actor_blocks(scrub2):
                        for fm in FUNC_DECL_RE.finditer(ab["body"]):
                            fname = fm.group("name")
                            mods = (fm.group("mods") or "").strip()
                            # Skip if explicitly nonisolated or static
                            if re.search(r"\bnonisolated\b", mods) or re.search(r"\bstatic\b", mods):
                                continue
                            if fname not in potential_rules:
                                potential_rules[fname] = {"kind": "function", "reason": f"Actor isolated instance method ({ab['name']})"}
                except Exception as _e:
                    pass

            # Optionally exclude functions annotated with a global actor (e.g., @MainActor)
            if exclude_global_actors:
                try:
                    scrub3 = _strip_comments(content)
                    for fm in re.finditer(r"@\w+Actor\b\s*(?:\r?\n\s*)*func\s+([A-Za-z_]\w*)\s*\(", scrub3):
                        fname = fm.group(1)
                        if fname not in potential_rules:
                            potential_rules[fname] = {"kind": "function", "reason": f"Global-actor isolated function (@...Actor) ({file_path.name})"}
                except Exception as _e:
                    pass

            # Optionally exclude functions declared in `extension` blocks (top-level funcs in the extension body)
            if exclude_extensions:
                try:
                    scrub4 = _strip_comments(content)
                    for tb in _find_type_like_blocks(scrub4):
                        if tb.get("kind") == "extension":
                            for match in _top_level_func_matches(tb["body"], FUNC_DECL_RE):
                                func_name = match.group("name")
                                if func_name not in potential_rules:
                                    potential_rules[func_name] = {"kind": "function", "reason": f"Declared in extension ({file_path.name})"}
                except Exception as _e:
                    pass

            # 1단계: 파일 전체가 복잡한지 판단 (UI 탐지 제거)
            is_complex = False
            reason = ""
            if COMPILER_DIRECTIVE_RE.search(content):
                is_complex, reason = True, f"File with compiler directives ({file_path.name})"
            elif NESTED_TYPE_RE.search(content):
                is_complex, reason = True, f"File with nested types ({file_path.name})"

            if is_complex:
                # 파일 내 모든 타입을 예외 처리
                for match in TYPE_DECL_RE.finditer(content):
                    name, kind = match.group(2), match.group(1)
                    if name not in potential_rules:
                        potential_rules[name] = {"kind": kind, "reason": reason}
                continue

            # 2단계: 타입/익스텐션 본문 내부의 *최상위* 함수만 스캔 (지역 함수 제외)
            scrub_types = _strip_comments(content)
            for tb in _find_type_like_blocks(scrub_types):
                for match in _top_level_func_matches(tb["body"], FUNC_DECL_RE):
                    func_line = match.group("line")
                    func_name = match.group("name")

                    # init, deinit은 항상 제외
                    if func_name in ["init", "deinit"]:
                        potential_rules[func_name] = {"kind": "function", "reason": "Special keyword: Initializer/Deinitializer"}
                        continue

                    # Return type uses '-> Self' is unsafe at file scope
                    if re.search(r"->\s*Self\b", func_line):
                        potential_rules[func_name] = {"kind": "function", "reason": "Unsafe due to return type 'Self'"}
                        continue

                    # Opaque return type 'some ...' is unsafe in function-type casts
                    if re.search(r"->\s*some\b", func_line):
                        potential_rules[func_name] = {"kind": "function", "reason": "Opaque return ('some') not supported"}
                        continue

                    # Context-associated identifiers (e.g., 'Configuration') without qualification are unsafe
                    if re.search(r"\bConfiguration\b", func_line):
                        potential_rules[func_name] = {"kind": "function", "reason": "Context-associated type in signature (e.g., Configuration)"}
                        continue

                    # 위험한 키워드가 포함되어 있으면 예외 처리
                    risky_keywords = [ "override", "@objc", "mutating", "inout", "@escaping", "async", "throws", "=" ]

                    params_part = match.group("params")

                    is_risky = False
                    reason_keyword = ""

                    # 기본 파라미터(default)가 하나라도 있으면 제외
                    if _has_param_default(params_part):
                        is_risky, reason_keyword = True, "default parameter value"
                    else:
                        # 나머지 키워드는 함수 선언 라인 전체에서 확인
                        for keyword in risky_keywords:
                            if keyword in func_line:
                                is_risky, reason_keyword = True, keyword
                                break

                    if is_risky:
                        potential_rules[func_name] = {"kind": "function", "reason": f"Unsafe due to '{reason_keyword}' keyword"}

        except Exception as e:
            print(f"Warning: Could not process file {file_path}: {e}")
            continue
            
    # --- 최종 규칙 생성 ---
    rules = [{"name": name, "kind": data["kind"], "comment": data["reason"]} for name, data in potential_rules.items()]
    
    # 중복 제거 및 이름순 정렬
    final_rules_map = {rule["name"]: rule for rule in rules}
    return sorted(list(final_rules_map.values()), key=lambda x: x['name'])


def main():
    parser = argparse.ArgumentParser(description="Swift 프로젝트를 스캔하여 OBFGen을 위한 예외 목록 JSON을 생성합니다.")
    parser.add_argument("--project", required=True, help="스캔할 Swift 프로젝트의 루트 경로")
    parser.add_argument("--output-json", required=True, help="생성될 예외 목록 JSON 파일의 경로")
    # Conservative name-based exclusions are DANGEROUS; default them OFF and let last.py do structural filtering
    parser.add_argument("--exclude-extensions", action="store_true", help="Exclude functions declared inside extension blocks from obfuscation targets.")
    parser.add_argument("--exclude-protocol-reqs", dest="exclude_protocol_requirements", action="store_true", help="Name-based: exclude protocol requirement names found in protocol declarations (default: OFF)")
    parser.add_argument("--exclude-actors", action="store_true", help="Name-based: exclude actor-isolated instance method names (default: OFF)")
    parser.add_argument("--exclude-global-actors", action="store_true", help="Name-based: exclude functions annotated with global actors (default: OFF)")
    # Defaults: exclude protocol-declared requirement names by default; other name-based exclusions remain OFF
    parser.set_defaults(exclude_protocol_requirements=True, exclude_actors=False, exclude_global_actors=False)
    args = parser.parse_args()

    project_path = Path(args.project).resolve()
    output_path = Path(args.output_json).resolve()

    if not project_path.is_dir():
        print(f"Error: Project path not found or not a directory: {project_path}")
        return

    print(f"Scanning project at: {project_path}")
    rules = analyze_and_generate_exceptions(
        project_path,
        exclude_extensions=args.exclude_extensions,
        exclude_protocol_requirements=args.exclude_protocol_requirements,
        exclude_actors=args.exclude_actors,
        exclude_global_actors=args.exclude_global_actors,
    )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_data = {"rules": rules}
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(output_data, f, indent=2, ensure_ascii=False)
        
    print(f"Successfully generated {len(rules)} exception rules.")
    print(f"Exception list saved to: {output_path}")

if __name__ == "__main__":
    main()
