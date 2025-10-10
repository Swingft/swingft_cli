#!/usr/bin/env python3
"""
debug_symbol_remover.py: 독립 실행 가능한 디버깅 심볼 제거 도구

Swift 프로젝트에서 디버깅용 코드(print, NSLog, assert 등)를 찾아서 
리포트를 생성하고 선택적으로 제거합니다.

사용법:
    python debug_symbol_remover.py <프로젝트경로> [옵션]

옵션:
    --output <파일경로>     리포트 파일 경로 (기본: debug_symbols_report.txt)
    --remove               발견된 디버깅 코드를 실제로 제거 (백업 생성)
    --restore              백업 파일(.debugbak)에서 원본 복구
    --help                 도움말 출력
"""

import argparse
import os
import sys
import shutil
import re
from pathlib import Path
from collections import defaultdict
from typing import Dict, List, Set, Tuple, Union

# ========== 상수 정의 ==========
DEBUG_FUNC_NAMES = [
    "print",
    "debugPrint", 
    "NSLog",
    "assert",
    "assertionFailure",
    "dump",
]

# 디버깅 함수 호출 패턴
PATTERN_MAP = {
    name: re.compile(rf'(?<![\w\.]){name}\s*\(')
    for name in DEBUG_FUNC_NAMES
}

# Swift.<func>() 형태 허용 패턴
SWIFT_PREFIX_PATTERNS = {
    name: re.compile(rf'\bSwift\.{name}\s*\(')
    for name in DEBUG_FUNC_NAMES
}

# Thread.callStackSymbols 패턴
THREAD_STACK_RE = re.compile(r'Thread\.callStackSymbols')

# 디버깅 함수 정의 패턴
DEBUG_FUNC_DEF_RE = re.compile(
    r'^\s*(?:public|internal|private|fileprivate)?\s*'
    r'(?:final\s+)?(?:static\s+)?func\s+('
    + "|".join(DEBUG_FUNC_NAMES)
    + r')\b'
)

# 일반 함수 정의 패턴
FUNC_DEF_RE = re.compile(
    r'^\s*(?:public|internal|private|fileprivate)?\s*'
    r'(?:final\s+)?(?:static\s+)?func\b'
)

MAX_LOOKAHEAD_LINES = 40
BACKUP_EXT = ".debugbak"

EXCLUDE_DIR_NAMES = {
    ".build", "Pods", "Carthage", "Checkouts",
    ".swiftpm", "DerivedData", "Tuist", ".xcodeproj"
}

# ========== 유틸리티 함수 ==========
def _is_external(path: Path) -> bool:
    """외부/생성 디렉토리인지 확인"""
    return any(part in EXCLUDE_DIR_NAMES for part in path.parts)

def _collect_until_balanced(lines: List[str], i: int, col: int, limit: int = MAX_LOOKAHEAD_LINES) -> int:
    """괄호가 균형을 이룰 때까지 라인 수집"""
    depth = 1
    for l in range(i, min(len(lines), i + limit)):
        start = col + 1 if l == i else 0
        for c in lines[l][start:]:
            if c == '(':
                depth += 1
            elif c == ')':
                depth -= 1
                if depth == 0:
                    return l
    return i

def _has_prefix_before(idx: int, line: str) -> bool:
    """이전에 점(.) 접두사가 있는지 확인"""
    j = idx - 1
    while j >= 0 and line[j].isspace():
        j -= 1
    return j >= 0 and line[j] == '.'

def _find_matching_brace(lines: List[str], i: int, col: int = 0, limit: int = MAX_LOOKAHEAD_LINES) -> int:
    """매칭되는 중괄호 찾기"""
    depth = 0
    for l in range(i, min(len(lines), i + limit)):
        for ch in lines[l][col:]:
            if ch == '{':
                depth += 1
            elif ch == '}' and depth > 0:
                return l
    return i

def is_comment_line(line: str) -> bool:
    """주석 라인인지 확인"""
    ls = line.lstrip()
    return ls.startswith('//') or ls.startswith('/*') or ls.startswith('*')

def is_func_def_line(line: str) -> bool:
    """함수 정의 라인인지 확인"""
    return bool(FUNC_DEF_RE.match(line.lstrip()))

def detect_layout(project_root: Path) -> Tuple[str, Path]:
    """프로젝트 레이아웃 감지"""
    if project_root.is_file() and project_root.suffix == ".swift":
        return "file", project_root
    if (project_root / "Package.swift").exists():
        return "spm", project_root
    if (project_root / "Project.swift").exists():
        xprojs = list(project_root.rglob("*.xcodeproj"))
        if xprojs:
            return "tuist", xprojs[0] / "project.pbxproj"
        return "tuist", project_root
    xprojs = list(project_root.rglob("*.xcodeproj"))
    if xprojs:
        return "xcode", xprojs[0] / "project.pbxproj"
    return "unknown", project_root

# ========== 디버깅 코드 감지 ==========
def _regex_find_calls(fp: Path, user_defined_names: Set[str], *, fallback: bool) -> List[Tuple[int, int]]:
    """파일에서 디버깅 함수 호출 찾기"""
    try:
        lines = fp.read_text(encoding="utf-8").splitlines()
    except Exception:
        return []
    
    spans: List[Tuple[int, int]] = []
    skip_until = -1
    
    for idx, line in enumerate(lines):
        if idx <= skip_until:
            continue
        
        # 디버깅 함수 정의는 건너뛰기
        if DEBUG_FUNC_DEF_RE.match(line):
            brace = line.find('{')
            if brace != -1:
                skip_until = _find_matching_brace(lines, idx, brace)
            continue
        
        # 주석이나 함수 정의는 건너뛰기
        if is_comment_line(line) or is_func_def_line(line):
            continue
        
        # Thread.callStackSymbols 감지
        if THREAD_STACK_RE.search(line):
            spans.append((idx + 1, idx + 1))
            continue
        
        # 디버깅 함수 호출 패턴 매칭
        for name, pat in PATTERN_MAP.items():
            m = pat.search(line) or SWIFT_PREFIX_PATTERNS[name].search(line)
            swift_allowed = bool(SWIFT_PREFIX_PATTERNS[name].search(line))
            
            if not m:
                continue
            
            # 사용자 정의 함수와 충돌하지 않는 경우만
            if name in user_defined_names and not swift_allowed:
                continue
            
            # 접두사가 있는 경우 건너뛰기 (Swift.<func> 제외)
            if _has_prefix_before(m.start(), line) and not swift_allowed:
                continue
            
            # 한 줄에 완성된 경우
            if line.count('(') == line.count(')'):
                spans.append((idx + 1, idx + 1))
            else:
                # 여러 줄에 걸친 경우
                open_pos = line.find('(', m.start())
                end = _collect_until_balanced(lines, idx, open_pos if open_pos >= 0 else 0)
                spans.append((idx + 1, end + 1))
                skip_until = end
            break
    
    return spans

def _group_entries_for_report(entries: Dict[Path, List[Tuple[int, int]]]) -> List[str]:
    """리포트용 엔트리 그룹화"""
    out: List[str] = []
    for fp, spans in entries.items():
        try:
            orig_lines = fp.read_text(encoding="utf-8").splitlines()
        except Exception:
            continue
        
        # 첫 번째 빈 줄 제거 여부 확인
        if orig_lines and orig_lines[0].strip() == "":
            lines = orig_lines[1:]
            adjust = True
        else:
            lines = orig_lines
            adjust = False
        
        for (s, e) in spans:
            if adjust:
                s_adj = max(1, s - 1)
                e_adj = max(1, e - 1)
            else:
                s_adj = s
                e_adj = e
            
            snippet = lines[s_adj - 1].lstrip().rstrip() if 1 <= s_adj <= len(lines) else ""
            out.append(f"{fp.name}:{s_adj}-{e_adj}: {snippet}")
    
    return out

# ========== 메인 기능 ==========
def generate_debug_report(project_path: str) -> None:
    """디버깅 심볼 리포트 생성"""
    root = Path(project_path).resolve()
    if not root.exists():
        print(f"오류: 경로를 찾을 수 없습니다: {root}")
        sys.exit(1)
    
    layout, anchor = detect_layout(root)
    
    # 단일 Swift 파일 모드
    if layout == "file":
        target_map = {"(FILE)": {anchor}}
        fallback = False
    else:
        # 모든 Swift 파일 찾기 (간단한 방식)
        all_swift = [p for p in root.rglob("*.swift") if not _is_external(p)]
        target_map = {"(ALL)": set(all_swift)}
        fallback = True
    
    # 사용자 정의 함수 수집
    all_files: Set[Path] = set().union(*target_map.values())
    user_defined: Set[str] = set()
    for fp in all_files:
        try:
            for line in fp.read_text(encoding="utf-8").splitlines():
                if m := DEBUG_FUNC_DEF_RE.match(line):
                    user_defined.add(m.group(1))
        except Exception:
            continue
    
    # 디버깅 코드 감지
    module_entries: Dict[str, Dict[Path, List[Tuple[int, int]]]] = {}
    for module_name, file_set in target_map.items():
        entries: Dict[Path, List[Tuple[int, int]]] = defaultdict(list)
        for fp in file_set:
            spans = _regex_find_calls(fp, user_defined, fallback=fallback)
            if spans:
                entries[fp].extend(spans)
        module_entries[module_name] = entries
    
    # 제거 실행
    remove_debug_symbols(module_entries)

def remove_debug_symbols(module_entries: Dict[str, Dict[Path, List[Tuple[int, int]]]]) -> None:
    """디버깅 심볼 '부분만' 제거 (라인 보존).
    - print / debugPrint / NSLog / assert / assertionFailure / dump 호출 '구간'만 삭제 또는 무해화
    - 동일 라인 뒤쪽 코드와 앞쪽 코드, 세미콜론 등은 최대한 보존
    - 멀티라인 호출도 지원 (최대 MAX_LOOKAHEAD_LINES)
    - 제거 건수는 '호출 단위'로 카운트
    """
    removed_calls = 0

    for module_name, entries in module_entries.items():
        for fp in entries.keys():
            try:
                lines = fp.read_text(encoding="utf-8").splitlines()

                new_lines: List[str] = []
                i = 0
                iter_guard = 0
                max_iter = max(1000, len(lines) * 10)  # safety guard
                while i < len(lines):
                    # watchdog / heartbeat
                    iter_guard += 1
                    if iter_guard > max_iter:
                        print(f"[경고] 반복 한도를 초과했습니다. 파일을 중단합니다: {fp} (i={i}, lines={len(lines)})")
                        break
                    line = lines[i]
                    # 고차함수 trailing-closure 내부의 디버깅 호출은 예외로 스킵
                    skip, end_line = _should_skip_debug_inside_trailing_closure(lines, i)
                    if skip:
                        for k in range(i, end_line + 1):
                            new_lines.append(lines[k])
                        i = end_line + 1
                        continue

                    # 빠른 패스: 디버그 토큰이 전혀 없으면 그대로
                    if not _maybe_contains_debug_token(line):
                        new_lines.append(line)
                        i += 1
                        continue

                    # 구조 보존 여부 결정
                    preserve = _should_preserve_print_structure(line, lines, i)

                    # 시도 1) 동일 라인 내에서 괄호가 닫히는 호출들을 모두 제거/무해화
                    changed, updated, removed = _strip_inline_debug_calls(line, preserve_structure=preserve)
                    if changed:
                        removed_calls += removed
                        new_lines.append(updated)
                        i += 1
                        continue

                    # 시도 2) 멀티라인 호출 시작인지 판단 후, 닫힘까지 병합 처리
                    ml_result = _strip_multiline_debug_call(lines, i, preserve_structure=preserve)
                    if ml_result is not None:
                        updated_line, next_index, removed = ml_result
                        removed_calls += removed
                        new_lines.append(updated_line)
                        i = next_index
                        continue

                    # 여기까지 왔으면 디버깅 호출로 확정되지 않음 → 원본 유지
                    new_lines.append(line)
                    i += 1

                with open(fp, 'w', encoding='utf-8') as f:
                    f.write('\n'.join(new_lines))

            except Exception as e:
                print(f"[오류] {fp}: {e}")


# ===== 부분 제거(인라인/멀티라인) 유틸 =====

# --- Helper: Fix empty forEach trailing closure after debug-call removal ---
def _fix_empty_foreach_trailing_closure(s: str) -> str:
    """If a trailing closure of .forEach lost its body (e.g., `{ } ),
    insert a dummy parameter `_ in` so the arity matches (Element) -> Void.
    Examples:
      fileURLs.forEach { }          -> fileURLs.forEach { _ in }
      fileURLs.forEach{   }         -> fileURLs.forEach { _ in }
    """
    # normalize minimal spacing first for reliable matching
    s_norm = re.sub(r"\s+", " ", s)
    # apply on the original string using regex with flexible spaces
    return re.sub(r"(\.forEach\s*\{)\s*(\})", r"\1 _ in \2", s)

# Thread.callStackSymbols 무해화 유틸리티
def _neutralize_thread_stack_tokens(s: str) -> Tuple[str, int]:
    """Replace Thread.callStackSymbols with a neutral literal while preserving syntax chains.
    - If it's immediately followed (ignoring spaces) by a dot (e.g. `.forEach`), return `[]` (empty array) to keep chaining valid.
    - Otherwise, return `""` (empty string literal) as a safe placeholder inside arguments/concats.
    Returns: (updated_string, replaced_count)
    """
    cnt = 0
    pattern = re.compile(r"Thread\.callStackSymbols")
    i = 0
    out = []
    while True:
        m = pattern.search(s, i)
        if not m:
            out.append(s[i:])
            break
        # write chunk before match
        out.append(s[i:m.start()])
        j = m.end()
        # skip spaces to peek next significant char
        k = j
        while k < len(s) and s[k].isspace():
            k += 1
        # choose replacement
        if k < len(s) and s[k] == '.':
            repl = '[]'   # allow chaining: [].forEach { }
        else:
            repl = '""'  # inside args/concat
        out.append(repl)
        cnt += 1
        i = j
    return ''.join(out), cnt

# --- High-order functions with trailing closures to skip when containing debug symbols ---
HO_FUNCS = (
    'forEach', 'map', 'compactMap', 'flatMap', 'filter', 'reduce',
    'sorted', 'sort', 'contains', 'first', 'allSatisfy'
)

_TRAILING_CLOSURE_START_RE = re.compile(
    r'\.\s*(?:' + '|'.join(HO_FUNCS) + r')\s*(?:\([^)]*\))?\s*\{'
)

def _find_trailing_closure_block(lines: List[str], start_idx: int, lookahead: int = MAX_LOOKAHEAD_LINES) -> Union[Tuple[int, int], None]:
    """현재 라인부터 최대 lookahead 라인 범위에서
    `.forEach { ... }` 같은 trailing-closure 블록을 찾아 (start_line, end_line) 반환."""
    for i in range(start_idx, min(len(lines), start_idx + lookahead)):
        line = lines[i]
        m = _TRAILING_CLOSURE_START_RE.search(line)
        if not m:
            continue
        # 이 라인의 '{' 위치부터 중괄호 균형 계산해 end_line 찾기
        brace_pos = line.find('{', m.end() - 1)
        if brace_pos == -1:
            continue
        depth = 0
        for j in range(i, min(len(lines), i + lookahead)):
            s = lines[j]
            k_start = brace_pos if j == i else 0
            for ch in s[k_start:]:
                if ch == '{':
                    depth += 1
                elif ch == '}':
                    depth -= 1
                    if depth == 0:
                        return (i, j)
        # 닫힘을 못 찾으면 블록으로 취급하지 않음
        return None
    return None


def _should_skip_debug_inside_trailing_closure(lines: List[str], idx: int) -> Tuple[bool, int]:
    """현재 위치에서 trailing-closure 고차함수 블록을 발견하고,
    그 블록 내부에 디버깅 토큰이 있으면 (True, end_line), 아니면 (False, idx)."""
    block = _find_trailing_closure_block(lines, idx)
    if not block:
        return False, idx
    start, end = block
    segment = '\n'.join(lines[start:end+1])
    if any(re.search(rf"(?<![\w\.])(?:Swift\.)?{name}\s*\(", segment) for name in DEBUG_FUNC_NAMES) or THREAD_STACK_RE.search(segment):
        return True, end
    return False, idx

def _maybe_contains_debug_token(line: str) -> bool:
    s = line
    if THREAD_STACK_RE.search(s):
        return True
    for name in DEBUG_FUNC_NAMES:
        if re.search(rf"(?<![\w\.])(?:Swift\.)?{name}\s*\(", s):
            return True
    return False


def _strip_inline_debug_calls(line: str, preserve_structure: bool = False) -> Tuple[bool, str, int]:
    """동일 라인에서 닫히는 디버그 호출들을 모두 제거/무해화.
    반환: (changed, updated_line, removed_calls)
    preserve_structure: True면 print/NSLog 등은 빈 호출로 대체, assert 계열은 assert(true)로 대체
    """
    s = line
    removed = 0

    # 1) Thread.callStackSymbols 무해화 (완전 삭제 대신 빈 리터럴 유지)
    if THREAD_STACK_RE.search(s):
        s, c = _neutralize_thread_stack_tokens(s)
        removed += c

    # 2) 토큰 단위 position-aware 스캔
    changed = False
    pos = 0
    while True:
        m = re.search(r"(?<![\w\.])(?:(?:Swift\.)?(print|debugPrint|NSLog|assert|assertionFailure|dump))\s*\(", s[pos:])
        if not m:
            break
        name = m.group(1)
        abs_start = pos + m.start()

        # 여는 괄호 위치 찾기
        open_idx = s.find('(', abs_start)
        if open_idx == -1:
            break

        # 동일 라인에서만 닫힘 찾기
        close_idx = _find_matching_paren_in_line(s, open_idx)
        if close_idx == -1:
            # 동일 라인에서 닫히지 않음 → 멀티라인일 수 있음, 여기서는 처리하지 않음
            break

        # 이미 무해화된 패턴은 재처리하지 않음 (무한 루프 방지)
        arg_segment = s[open_idx:close_idx+1].strip()
        if preserve_structure and (arg_segment == '("")' or arg_segment == '(true)'):
            pos = close_idx + 1
            continue

        # 치환문 결정
        if preserve_structure:
            has_swift_prefix = s[abs_start:open_idx].strip().startswith('Swift.')
            token = ("Swift." if has_swift_prefix else "") + name
            if name in ("print", "debugPrint", "NSLog", "dump"):
                replacement = f"{token}(\"\")"
            else:
                replacement = "assert(true)"
        else:
            replacement = ""

        s = s[:abs_start] + replacement + s[close_idx + 1:]
        removed += 1
        changed = True
        pos = abs_start + len(replacement)

    if changed:
        s = _cleanup_semicolons_and_spaces(s)
        s = _fix_empty_foreach_trailing_closure(s)
    return changed or (removed > 0), s, removed


def _find_matching_paren_in_line(s: str, open_idx: int) -> int:
    depth = 0
    in_quote = False
    esc = False
    for i in range(open_idx, len(s)):
        ch = s[i]
        if in_quote:
            if esc:
                esc = False
            elif ch == '\\':
                esc = True
            elif ch == '"':
                in_quote = False
        else:
            if ch == '"':
                in_quote = True
            elif ch == '(':
                depth += 1
            elif ch == ')':
                depth -= 1
                if depth == 0:
                    return i
    return -1


def _cleanup_semicolons_and_spaces(s: str) -> str:
    # 1) Collapse multiple semicolons like "; ;" or ";   ;" → "; "
    s = re.sub(r"\s*;\s*;\s*", "; ", s)
    # 2) Remove semicolon immediately after an opening brace: "{ ; foo()" → "{ foo()"
    s = re.sub(r"\{\s*;\s*", "{ ", s)
    # 3) Remove semicolon immediately before a closing brace: "foo(); }" → "foo() }"
    s = re.sub(r"\s*;\s*\}", " }", s)
    # 4) Trim semicolons at line start/end
    s = re.sub(r"^\s*;\s*", "", s)
    s = re.sub(r"\s*;\s*$", "", s)
    # 5) Normalize spaces around single semicolons
    s = re.sub(r"\s*;\s*", "; ", s)
    return s.rstrip()


def _strip_multiline_debug_call(lines: List[str], start_idx: int, preserve_structure: bool = False) -> Union[Tuple[str, int, int], None]:
    """start_idx 라인에서 디버그 호출이 시작되지만, 같은 라인에서 닫히지 않는 경우 처리.
    반환: (updated_first_line, next_index, removed_calls) 또는 None
    - next_index 는 병합 후 다음에 처리할 라인의 인덱스
    - 호출 텍스트만 삭제하고, end 라인의 닫는 괄호 뒤 텍스트는 보존/이어붙임
    preserve_structure: True면 print/NSLog 등은 빈 호출로 대체, assert 계열은 assert(true)로 대체
    """
    line = lines[start_idx]
    # 디버그 호출 시작 탐지
    m = re.search(r"(?<![\w\.])(?:(?:Swift\.)?(print|debugPrint|NSLog|assert|assertionFailure|dump))\s*\(", line)
    if not m:
        # Thread.callStackSymbols 같은 토큰만 있는 경우는 인라인 처리에서 끝남
        return None

    open_idx = line.find('(', m.end() - 1)
    if open_idx == -1:
        return None

    # 같은 라인에서 닫히면 인라인 케이스
    close_idx_same = _find_matching_paren_in_line(line, open_idx)
    if close_idx_same != -1:
        return None

    # 멀티라인: 다음 라인들에서 닫는 괄호 탐색
    depth = 1
    in_quote = False
    esc = False
    end_line = start_idx
    end_col = -1

    for j in range(start_idx + 1, min(len(lines), start_idx + 1 + MAX_LOOKAHEAD_LINES)):
        s = lines[j]
        for k, ch in enumerate(s):
            if in_quote:
                if esc:
                    esc = False
                elif ch == '\\':
                    esc = True
                elif ch == '"':
                    in_quote = False
            else:
                if ch == '"':
                    in_quote = True
                elif ch == '(':
                    depth += 1
                elif ch == ')':
                    depth -= 1
                    if depth == 0:
                        end_line = j
                        end_col = k
                        break
        if end_col != -1:
            break
    if end_col == -1:
        # 닫는 괄호를 못 찾은 경우 처리 불가 → None 반환
        return None

    # 호출 텍스트만 삭제: 앞부분 + 뒷부분 연결
    prefix = line[:m.start()]
    suffix = lines[end_line][end_col + 1:]

    if preserve_structure:
        # Swift. 접두사 보존
        has_swift_prefix = line[m.start():open_idx].strip().startswith('Swift.')
        name = m.group(1)
        token = ("Swift." if has_swift_prefix else "") + name
        if name in ("print", "debugPrint", "NSLog", "dump"):
            middle = f"{token}(\"\")"
        else:
            middle = "assert(true)"
        merged = prefix + middle + suffix
    else:
        merged = prefix + suffix
    merged = _cleanup_semicolons_and_spaces(merged)
    merged = _fix_empty_foreach_trailing_closure(merged)

    return merged, end_line + 1, 1

def _is_multiline_print_start(line: str) -> bool:
    """멀티라인 print 문의 시작인지 확인"""
    stripped = line.strip()
    
    # print(로 시작하지만 닫는 괄호가 없는 경우
    if re.match(r'print\s*\(', stripped) and ')' not in stripped:
        return True
    
    # print("""로 시작하는 경우 (멀티라인 문자열)
    if re.match(r'print\s*\(\s*"""', stripped):
        return True
    
    return False

def _is_debug_line(line: str) -> bool:
    """해당 라인이 디버깅 코드인지 확인"""
    stripped = line.strip()
    
    # print, NSLog, assert 등 디버깅 함수 호출 확인
    for name in DEBUG_FUNC_NAMES:
        if re.search(rf'(?<![\w\.]){name}\s*\(', stripped):
            return True
    
    # Thread.callStackSymbols 확인
    if THREAD_STACK_RE.search(stripped):
        return True
    
    return False

def _clear_print_content(line: str) -> str:
    """print 문의 내용만 지우고 빈 print()로 변경"""
    stripped = line.strip()
    indent = line[:len(line) - len(line.lstrip())]
    
    # print("content") -> print("")
    # NSLog("content") -> NSLog("")
    # assert(condition) -> assert(true)
    # 멀티라인 문자열도 처리
    
    for name in DEBUG_FUNC_NAMES:
        pattern = rf'(\s*{name}\s*)(\([^)]*\))'
        match = re.search(pattern, stripped)
        if match:
            if name == 'assert':
                # assert는 true로 변경
                return indent + match.group(1) + "(true)"
            else:
                # print, NSLog 등은 빈 문자열로 변경
                return indent + match.group(1) + '("")'
    
    # Thread.callStackSymbols의 경우
    if THREAD_STACK_RE.search(stripped):
        return indent + 'Thread.callStackSymbols'
    
    return line  # 매칭되지 않으면 원본 반환

def _clear_multiline_print_content(lines: List[str], start_idx: int) -> Tuple[str, int]:
    """멀티라인 print 블록을 빈 print(\"\") 1줄로 치환하고, 블록의 마지막 라인 인덱스를 반환."""
    if start_idx >= len(lines):
        return "", start_idx

    line = lines[start_idx]
    indent = line[:len(line) - len(line.lstrip())]

    # 시작 라인이 print( 로 보이지 않으면 원본 라인을 그대로 반환
    if not re.search(r'\bprint\s*\(', line):
        return line, start_idx

    # 종료 지점 탐색: 이후 라인 중 ')' 등장하는 첫 라인까지를 블록으로 간주
    end_idx = start_idx
    for i in range(start_idx + 1, len(lines)):
        if ')' in lines[i]:
            end_idx = i
            break
    else:
        end_idx = start_idx  # 닫는 괄호를 못 찾으면 시작 라인만 치환

    # 단일 치환 라인만 반환 (중간 라인들은 호출부에서 건너뜀)
    return indent + 'print("")', end_idx

def _fix_broken_multiline_prints(lines: List[str]) -> List[str]:
    """깨진 멀티라인 print 문들을 수정"""
    fixed_lines: List[str] = []
    i = 0
    while i < len(lines):
        line = lines[i]
        # 패턴: 라인이 `print("""` 로 시작하고 같은 라인에 닫힘이 없는 경우
        if re.match(r'^\s*print\s*\(\s*"""\s*$', line.strip()):
            indent = line[:len(line) - len(line.lstrip())]
            # 닫는 괄호를 찾을 때까지 스킵
            j = i + 1
            while j < len(lines) and ')' not in lines[j]:
                j += 1
            # 한 줄로 정리
            fixed_lines.append(indent + 'print("")')
            i = j + 1  # 닫는 괄호가 있는 라인 다음으로 이동
            continue
        else:
            fixed_lines.append(line)
            i += 1
    return fixed_lines

def _fix_all_multiline_issues(lines: List[str]) -> List[str]:
    """모든 멀티라인 관련 문제를 수정"""
    fixed_lines = []
    i = 0
    while i < len(lines):
        line = lines[i]
        
        # 1. print("""만 있는 라인
        if re.match(r'^\s*print\s*\(\s*"""\s*$', line.strip()):
            indent = line[:len(line) - len(line.lstrip())]
            fixed_lines.append(indent + 'print("")')
            
            # 다음 라인들에서 닫는 괄호 찾기
            j = i + 1
            while j < len(lines) and ')' not in lines[j]:
                j += 1
            i = j
        # 2. print("""내용""" 형태
        elif re.match(r'^\s*print\s*\(\s*""".*"""\s*\)\s*$', line.strip()):
            indent = line[:len(line) - len(line.lstrip())]
            fixed_lines.append(indent + 'print("")')
            i += 1
        # 3. print("""내용만 있는 라인
        elif re.match(r'^\s*print\s*\(\s*""".*$', line.strip()):
            indent = line[:len(line) - len(line.lstrip())]
            fixed_lines.append(indent + 'print("")')
            
            # 다음 라인들에서 닫는 괄호 찾기
            j = i + 1
            while j < len(lines) and ')' not in lines[j]:
                j += 1
            i = j
        # 4. """만 있는 라인 (멀티라인 문자열 닫기)
        elif re.match(r'^\s*"""\s*\)\s*$', line.strip()):
            # 이 라인은 건너뛰기
            i += 1
        # 5. """만 있는 라인
        elif re.match(r'^\s*"""\s*$', line.strip()):
            # 이 라인은 건너뛰기
            i += 1
        else:
            fixed_lines.append(line)
            i += 1
    
    return fixed_lines

def _is_inside_case_block(lines: List[str], line_index: int) -> bool:
    """해당 라인이 case 블록 내부에 있는지 확인"""
    # 현재 라인부터 위로 올라가면서 case 패턴 찾기
    for i in range(line_index - 1, -1, -1):
        line = lines[i].strip()
        
        # case 패턴 발견
        if re.match(r'^\s*case\s+', line) or re.match(r'^\s*@unknown\s+default\s*:', line):
            return True
        
        # 함수나 클래스 정의 발견 시 case 블록이 아님
        if re.match(r'^\s*(func|class|struct|enum|protocol|extension)\s+', line):
            return False
            
        # 중괄호로 시작하는 블록 발견 시 case 블록이 아님
        if line.startswith('{'):
            return False
    
    return False

def _is_inside_guard_else_block(lines: List[str], line_index: int) -> bool:
    """해당 라인이 guard 문의 else 블록 내부에 있는지 확인"""
    # 현재 라인부터 위로 올라가면서 guard 패턴 찾기
    for i in range(line_index - 1, -1, -1):
        line = lines[i].strip()
        
        # guard 패턴 발견
        if re.match(r'^\s*guard\s+', line):
            return True
        
        # 함수나 클래스 정의 발견 시 guard 블록이 아님
        if re.match(r'^\s*(func|class|struct|enum|protocol|extension)\s+', line):
            return False
            
        # 중괄호로 시작하는 블록 발견 시 guard 블록이 아님
        if line.startswith('{'):
            return False
    
    return False

def _should_preserve_print_structure(line: str, lines: List[str], line_index: int) -> bool:
    """print 문의 구조를 보존해야 하는지 확인 (case 블록이나 guard else 블록 내부)"""
    return (_is_inside_case_block(lines, line_index) or 
            _is_inside_guard_else_block(lines, line_index))


def remove_debug_symbol(project_dir):
    generate_debug_report(project_dir)