#!/usr/bin/env python3
# debug_reporter.py (unified)
"""
정밀(Target) 매핑 + 안전한 휴리스틱을 모두 지원하는 단일 실행 파일.

우선순위
  1) SPM:   `swift package dump-package`로 Target ↔ 파일 정밀 매핑
  2) Xcode: `<proj>.xcodeproj/project.pbxproj` 간소 파서로 Target ↔ 파일 매핑
  3) Tuist: `Project.swift` 감지 시 생성된 .xcodeproj를 위 Xcode 방식으로 파싱
  4) 실패/미감지: 전체 .swift 스캔 (fallback)

Fallback 정책 (디렉토리 단위 shadowing 보호)
  - 특정 디렉토리 안에 디버깅 심볼 이름과 동일한 함수 정의가 하나라도 있으면,
    그 디렉토리의 다른 파일에서는 해당 이름의 호출을 "디버깅 호출"로 간주하지 않음
    (즉, 제거/래핑 대상에서 제외) — 안전망.
  - 보수 모드(fallback)에서는 프로젝트 전역에서 재정의가 하나라도 발견된 심볼은 전체 파일에서 보호됩니다.

사용 예
  # 레이아웃 자동 감지 후 리포트만 생성
  python3 debug_reporter.py /path/to/project -o report.txt

  # 탐지된 호출 삭제 (라인 단위, .debugbak 백업 생성)
  python3 debug_reporter.py /path/to/project --remove

  # 탐지된 호출을 #if DEBUG ... #endif 로 래핑
  python3 debug_reporter.py /path/to/project --wrap-in-debug

  # 백업(.debugbak) 복구 (path 생략 가능)
  python3 debug_reporter.py --restore /path/to/project
"""

from __future__ import annotations
import re
import os
import sys
import subprocess
import json
import shutil
from collections import defaultdict
from pathlib import Path
from typing import Dict, List, Set, Tuple

# ---------- 0. 공통 상수 ------------------------------------------------------
DEBUG_FUNC_NAMES = [
    "print", "debugPrint", "NSLog",
    "assert", "assertionFailure", "dump"
]
# 호출 탐지를 위한 정규식 (Swift. 접두 허용 X – 별도 처리)
PATTERN_MAP = {
    name: re.compile(rf'(?<![\w\.]){name}\s*\(')
    for name in DEBUG_FUNC_NAMES
}
# Swift.접두 허용 패턴 (Swift.print(...) 등)
SWIFT_PREFIX_PATTERNS = {
    name: re.compile(rf'\bSwift\.{name}\s*\(')
    for name in DEBUG_FUNC_NAMES
}
THREAD_STACK_RE       = re.compile(r'Thread\.callStackSymbols')
DEBUG_FUNC_DEF_RE     = re.compile(
    r'^\s*(?:public|internal|private|fileprivate)?\s*'
    r'(?:final\s+)?(?:static\s+)?func\s+(' + "|".join(DEBUG_FUNC_NAMES) + r')\b'
)
FUNC_DEF_RE           = re.compile(
    r'^\s*(?:public|internal|private|fileprivate)?\s*(?:final\s+)?'
    r'(?:static\s+)?func\b'
)
MAX_LOOKAHEAD_LINES   = 40
BACKUP_EXT            = ".debugbak"

EXCLUDE_DIR_NAMES = {
    ".build", "Pods", "Carthage", "Checkouts",
    ".swiftpm", "DerivedData", "Tuist", ".xcodeproj"
}

def _is_external(path: Path) -> bool:
    return any(part in EXCLUDE_DIR_NAMES for part in path.parts)

# ---------- 1. 레이아웃/모듈 감지 -------------------------------------------
def _detect_layout(project_root: Path) -> Tuple[str, Path]:
    """
    반환: (layout, anchor_path)
      - layout: "spm" | "xcode" | "tuist" | "unknown"
      - anchor_path:
          spm  → project_root
          xcode/tuist → <something>.xcodeproj/project.pbxproj (가능 시)
          unknown → project_root
    """
    # 단일 Swift 파일 입력 처리
    if project_root.is_file() and project_root.suffix == ".swift":
        # 'file' 레이아웃으로 간주하고, anchor 는 해당 파일 자체
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

# ---------- 2-A. SPM 타겟 → 파일 매핑 ---------------------------------------
def _spm_target_map(project_root: Path) -> Dict[str, Set[Path]]:
    """`swift package dump-package` 로부터 {target: {swiftFiles}} dict 반환"""
    try:
        res = subprocess.run(
            ["swift", "package", "dump-package", "--package-path", str(project_root)],
            check=True, capture_output=True, text=True
        )
        pkg = json.loads(res.stdout)
    except Exception as e:
        print(f"[WARN] swift package dump 실패: {e}")
        return {}

    out: Dict[str, Set[Path]] = defaultdict(set)
    for tgt in pkg.get("targets", []):
        if tgt.get("type") in {"test"}:  # 테스트 타겟 제외
            continue
        name = tgt["name"]
        src_path = tgt.get("path") or f"Sources/{name}"
        abs_src = project_root / src_path
        if not abs_src.exists():
            continue
        for p in abs_src.rglob("*.swift"):
            out[name].add(p.resolve())
    return out

# ----- 2-A'. SPM 다중 패키지 탐색 -----------------------------------------
def _spm_target_map_recursive(repo_root: Path) -> Dict[str, Set[Path]]:
    """
    모노레포 등에서 repo_root 하위의 모든 Package.swift를 재귀적으로 탐색하여
    {prefixed_target_name: {swift_files}} 형태로 병합한 매핑을 반환한다.
    타겟 이름 앞에는 패키지 경로(루트 기준 상대)를 붙여 구분한다.
    """
    merged: Dict[str, Set[Path]] = defaultdict(set)
    for pkg_file in repo_root.rglob("Package.swift"):
        pkg_root = pkg_file.parent
        submap = _spm_target_map(pkg_root)
        # 패키지 루트가 repo_root 자체이면 prefix는 생략
        rel_prefix = (
            "" if pkg_root == repo_root
            else f"{pkg_root.relative_to(repo_root)}/"
        )
        for tgt, files in submap.items():
            merged[f"{rel_prefix}{tgt}"].update(files)
    return merged

# ---------- 2-B. pbxproj 파싱 (간소/보수) -----------------------------------
PBX_FILE_REF      = re.compile(r'\s([0-9A-F]{24}) /\* (.+?\.swift) ')
PBX_BUILD_FILE    = re.compile(r'([0-9A-F]{24}) /\* .+ in Sources \*/ = {isa = PBXBuildFile; fileRef = ([0-9A-F]{24})')
PBX_NTV_TARGET    = re.compile(r'(\w{24}) /\* (.+?) \*/ = \{[^}]*?isa\s*=\s*PBXNativeTarget\s*;', re.S)
PBX_TGT_SOURCES   = re.compile(r'buildPhases\s*=\s*\((?:.|\n)*?([0-9A-F]{24}) /\* Sources \*/', re.S)
PBX_PHASE_FILE_IDS= re.compile(r'\b([0-9A-F]{24})\b')


def _resolve_swift_from_comment(pbxproj: Path, name_or_rel: str) -> Path | None:
    """PBX 코멘트/상대경로로부터 실제 Swift 파일 경로 해소.
    파일명이면 프로젝트 루트에서 유일 매칭 시 채택."""
    root = pbxproj.parent.parent  # <proj root>/
    candidate = Path(name_or_rel)
    if "/" in name_or_rel:
        p = (root / candidate).resolve()
        if p.exists():
            return p
    try:
        matches = [p for p in root.rglob(candidate.name) if p.suffix == ".swift" and not _is_external(p)]
    except Exception:
        matches = []
    if len(matches) == 1:
        return matches[0].resolve()
    return None


def _pbxproj_target_map(pbxproj: Path) -> Dict[str, Set[Path]]:
    """pbxproj 텍스트만으로 (target → {swift 파일}) 매핑 (단순·보수적 파서)."""
    if not pbxproj.exists():
        return {}
    text = pbxproj.read_text(errors="ignore")
    file_ref_to_path = {m[0]: m[1].strip() for m in PBX_FILE_REF.findall(text)}
    buildfile_to_filerefid = {m[0]: m[1] for m in PBX_BUILD_FILE.findall(text)}

    phase_to_bfiles: Dict[str, List[str]] = defaultdict(list)
    for phase_id, files_blob in re.findall(r'([0-9A-F]{24}) /\* Sources \*/ = {[^}]+?files = \(([^)]+)\)', text, re.S):
        phase_to_bfiles[phase_id] = PBX_PHASE_FILE_IDS.findall(files_blob)

    targets: Dict[str, Set[Path]] = defaultdict(set)
    for m in PBX_NTV_TARGET.finditer(text):
        t_id, t_name = m.group(1), m.group(2)
        if t_name.endswith("Tests") or "Test" in t_name:
            continue
        start = m.start()
        end = text.find("};", start)
        blk = text[start:end+2] if end != -1 else text[start:]
        phase_ids = PBX_TGT_SOURCES.findall(blk)
        if not phase_ids:
            continue
        for source_phase in phase_ids:
            for bfile in phase_to_bfiles.get(source_phase, []):
                fref = buildfile_to_filerefid.get(bfile)
                rel  = file_ref_to_path.get(fref)
                if not rel or not rel.endswith(".swift"):
                    continue
                abs_path = _resolve_swift_from_comment(pbxproj, rel)
                if abs_path:
                    targets[t_name].add(abs_path)
    return targets

# ---------- 3. 보조 유틸 -----------------------------------------------------
def _collect_until_balanced(lines: List[str], i: int, col: int, limit=MAX_LOOKAHEAD_LINES) -> int:
    depth, end = 1, min(len(lines), i + limit)
    for l in range(i, end):
        start = col+1 if l == i else 0
        for c in lines[l][start:]:
            if c == '(':
                depth += 1
            elif c == ')':
                depth -= 1
                if depth == 0:
                    return l
    return i


def _has_prefix_before(idx: int, line: str) -> bool:
    j = idx - 1
    while j >= 0 and line[j].isspace():
        j -= 1
    return j >= 0 and line[j] == '.'


def _find_matching_brace(lines: List[str], i: int, col=0, limit=MAX_LOOKAHEAD_LINES) -> int:
    depth, end = 0, min(len(lines), i + limit)
    l, c = i, col
    open_seen = False
    while l < end:
        for ch in lines[l][c:]:
            if ch == '{':
                depth += 1; open_seen = True
            elif ch == '}':
                depth -= 1
                if open_seen and depth == 0:
                    return l
        l += 1; c = 0
    return i


def is_comment_line(line: str) -> bool:
    ls = line.lstrip()
    return ls.startswith('//') or ls.startswith('///') or ls.startswith('/*') or ls.startswith('*')


def is_func_def_line(line: str) -> bool:
    return bool(FUNC_DEF_RE.match(line.lstrip()))


# ---------- 4. 휴리스틱: 디렉토리 단위 shadowing 맵 -------------------------
def _dir_shadowing_map(files: Set[Path]) -> Dict[Path, Set[str]]:
    """디렉토리별(Parent)로 디버깅 심볼과 동일한 이름의 함수 정의를 수집."""
    by_dir: Dict[Path, Set[str]] = defaultdict(set)
    for fp in files:
        try:
            for ln in fp.read_text(encoding="utf-8").splitlines():
                indent = len(ln) - len(ln.lstrip())
                if indent != 0:        # 무조건 들여쓰기(= 타입/스코프 내부)면 무시
                    continue
                m = DEBUG_FUNC_DEF_RE.match(ln)
                if m:
                    by_dir[fp.parent].add(m.group(1))
        except Exception:
            pass
    return by_dir

# ---------- 4b. 휴리스틱: 전체 프로젝트 전역 shadowing 집합 (fallback-보수)
def _global_shadowing_set(files: Set[Path]) -> Set[str]:
    """
    프로젝트 전체에서 디버깅 심볼과 동일한 이름의 함수 정의가 하나라도 발견되면
    그 심볼 이름을 전역 보호 대상으로 표시한다.
    """
    names: Set[str] = set()
    for fp in files:
        try:
            for ln in fp.read_text(encoding="utf-8").splitlines():
                indent = len(ln) - len(ln.lstrip())
                if indent != 0:        # 무조건 들여쓰기(= 타입/스코프 내부)면 무시
                    continue
                m = DEBUG_FUNC_DEF_RE.match(ln)
                if m:
                    names.add(m.group(1))
        except Exception:
            pass
    return names


# ---------- 5. 호출 탐지 -----------------------------------------------------
# global_shadowed: 프로젝트 전역에서 섀도잉된 디버깅 심볼 이름 집합 (fallback-보수용)
def _regex_find_calls(fp: Path,
                      user_defined_names: Set[str],
                      *,
                      fallback: bool,
                      dir_shadowed: Dict[Path, Set[str]] | None = None,
                      global_shadowed: Set[str] | None = None) -> List[Tuple[int,int]]:
    """정규식 기반으로 (startLine, endLine) 범위를 찾는다.
    fallback=True 일 때는 디렉토리 단위 shadowing 보호를 적용한다."""
    try:
        lines = fp.read_text(encoding="utf-8").splitlines()
    except Exception:
        return []

    ranges: List[Tuple[int,int]] = []
    skip_until = -1
    for idx, line in enumerate(lines):
        if idx <= skip_until:
            continue

        if DEBUG_FUNC_DEF_RE.match(line):
            brace = line.find('{')
            if brace != -1:
                skip_until = _find_matching_brace(lines, idx, brace)
            continue

        if is_comment_line(line) or is_func_def_line(line):
            continue

        if THREAD_STACK_RE.search(line):
            ranges.append((idx+1, idx+1))
            continue

        for name, pat in PATTERN_MAP.items():
            m = pat.search(line) or SWIFT_PREFIX_PATTERNS[name].search(line)
            swift_allowed = bool(SWIFT_PREFIX_PATTERNS[name].search(line))
            if not m:
                continue

            # 1) 모듈/파일 단위 사용자 정의 보호
            if name in user_defined_names and not swift_allowed:
                continue

            # 2) fallback 보수 모드: 전역 shadowing 보호
            if fallback and global_shadowed is not None and name in global_shadowed and not swift_allowed:
                continue

            # 3) fallback: 디렉토리 단위 shadowing 보호 (하위 호환)
            if fallback and dir_shadowed is not None:
                shadow = dir_shadowed.get(fp.parent, set())
                if name in shadow and not swift_allowed:
                    continue

            # obj.method() 같은 케이스 제외 (Swift.접두는 허용)
            if _has_prefix_before(m.start(), line) and not swift_allowed:
                continue

            if line.count('(') == line.count(')'):
                ranges.append((idx+1, idx+1))
                break

            open_pos = line.find('(', m.start())
            end = _collect_until_balanced(lines, idx, open_pos if open_pos != -1 else len(line)-1)
            ranges.append((idx+1, end+1))
            skip_until = end
            break
    return ranges


# ---------- 6. 보고/수정 도우미 ---------------------------------------------
def _group_entries_for_report(entries: Dict[Path, List[Tuple[int,int]]]) -> List[str]:
    out: List[str] = []
    for fp, spans in entries.items():
        try:
            lines = fp.read_text(encoding="utf-8").splitlines()
        except Exception:
            continue
        for (s,e) in spans:
            snippet = lines[s-1].rstrip() if 1 <= s <= len(lines) else ""
            out.append(f"{fp}:{s}-{e}: {snippet}")
    return out


def _apply_remove(entries: Dict[Path, List[Tuple[int,int]]]) -> None:
    for fp, spans in entries.items():
        all_lines = fp.read_text(encoding="utf-8").splitlines(True)
        for (s,e) in sorted(spans, key=lambda x: (x[0], x[1]), reverse=True):
            bak = fp.with_suffix(fp.suffix + BACKUP_EXT)
            if not bak.exists():
                shutil.copy2(fp, bak)
            del all_lines[s-1:e]
        with open(fp, "w", encoding="utf-8") as f:
            f.writelines(all_lines)


def _apply_wrap_debug(entries: Dict[Path, List[Tuple[int,int]]]) -> None:
    for fp, spans in entries.items():
        all_lines = fp.read_text(encoding="utf-8").splitlines(True)
        for (s,e) in sorted(spans, key=lambda x: (x[0], x[1]), reverse=True):
            pre = "".join(all_lines[max(0, s-3):s-1])
            post = "".join(all_lines[e:min(len(all_lines), e+2)])
            if "#if DEBUG" in pre and "#endif" in post:
                continue
            indent = re.match(r"\s*", all_lines[s-1]).group(0) if s-1 < len(all_lines) else ""
            bak = fp.with_suffix(fp.suffix + BACKUP_EXT)
            if not bak.exists():
                shutil.copy2(fp, bak)
            all_lines.insert(e, indent + "#endif\n")
            all_lines.insert(s-1, indent + "#if DEBUG\n")
        with open(fp, "w", encoding="utf-8") as f:
            f.writelines(all_lines)


# ---------- 7. 메인 -----------------------------------------------------------
def generate_debug_report(project_path: str,
                          out_path: str,
                          *,
                          apply_removal: bool=False,
                          wrap_in_debug: bool=False) -> None:
    root = Path(project_path).resolve()
    if not root.exists():
        sys.exit(f"경로 없음: {root}")

    layout, anchor = _detect_layout(root)

    # 단일 Swift 파일 모드
    if layout == "file":
        target_map = {"(FILE)": {anchor.resolve()}}
        fallback = False
    else:
        # 1) 정밀 매핑 시도
        if layout == "spm":
            # 루트 + 하위 모든 Package.swift 재귀 탐색
            target_map = _spm_target_map_recursive(root)
        elif layout == "xcode":
            pbx = anchor if anchor.suffix == ".pbxproj" else None
            if pbx is None:
                xprojs = list(root.rglob("*.xcodeproj"))
                pbx = xprojs[0] / "project.pbxproj" if xprojs else None
            target_map = _pbxproj_target_map(pbx) if pbx else {}
        elif layout == "tuist":
            # Try pbxproj parser first for Tuist-generated xcodeproj
            pbx = anchor if anchor.suffix == ".pbxproj" else None
            if pbx and pbx.exists():
                target_map = _pbxproj_target_map(pbx)
                fallback = False
            else:
                target_map = {}
                fallback = False
            # If pbx parsing succeeded, skip Project.swift logic
            if target_map:
                pass
            else:
                # --- Tuist precise project detection ---
                tuist_root = root
                # If anchor is a pbxproj, use its parent.parent as root
                if anchor.suffix == ".pbxproj":
                    tuist_root = anchor.parent.parent
                workspace_file = tuist_root / "Workspace.swift"
                project_dirs: List[Path] = []
                if workspace_file.exists():
                    # Parse Workspace.swift for projects: [ ... ]
                    try:
                        ws_text = workspace_file.read_text(encoding="utf-8")
                        # regex to extract projects: ["Projects/*", ...]
                        # Accepts let workspace = Workspace(..., projects: [ ... ], ...)
                        projects_line = None
                        for line in ws_text.splitlines():
                            if re.search(r'\bprojects\s*:', line):
                                projects_line = line
                                break
                        patterns = []
                        if projects_line:
                            # Try to extract the list of patterns in [ ... ]
                            m = re.search(r'projects\s*:\s*\[([^\]]*)\]', projects_line)
                            if m:
                                inner = m.group(1)
                                # Accept both "foo", 'foo'
                                patterns = re.findall(r'["\']([^"\']+)["\']', inner)
                        if not patterns:
                            # fallback: look for all Project.swift
                            project_swift_files = list(tuist_root.rglob("Project.swift"))
                        else:
                            import glob
                            # Resolve patterns relative to tuist_root
                            project_swift_files = []
                            for pat in patterns:
                                for match in glob.glob(str(tuist_root / pat), recursive=True):
                                    d = Path(match)
                                    # If it's a directory, look for Project.swift inside it or its subdirs
                                    if d.is_dir():
                                        project_swift_files.extend(d.rglob("Project.swift"))
                                    elif d.name == "Project.swift":
                                        project_swift_files.append(d)
                        project_swift_files = [Path(p).resolve() for p in project_swift_files]
                    except Exception as ex:
                        print(f"[WARN] Workspace.swift 파싱 실패: {ex}")
                        project_swift_files = list(tuist_root.rglob("Project.swift"))
                else:
                    # No Workspace.swift: fallback to all Project.swift
                    project_swift_files = list(tuist_root.rglob("Project.swift"))
                # Build map: use Project.swift parent as module name, collect all .swift files under it
                target_map = {}
                for pj in project_swift_files:
                    mod_name = str(pj.parent.relative_to(tuist_root))
                    swift_files = set(p for p in pj.parent.rglob("*.swift") if not _is_external(p))
                    if swift_files:
                        target_map[mod_name] = swift_files
        else:
            target_map = {}

        # 2) 타겟 매핑 실패 → fallback
        fallback = False
        if not target_map or not any(target_map.values()):
            print("[INFO] Target 매핑 실패/미감지 — 전체 Swift 파일 대상으로 스캔을 진행합니다.")
            all_swift_files = [p.resolve() for p in root.rglob("*.swift") if not _is_external(p)]
            target_map = {"(ALL)": set(all_swift_files)}
            fallback = True

        # 3) 외부 SDK 디렉터리 필터링
        target_map = {
            tgt: {p for p in files if not _is_external(p)}
            for tgt, files in target_map.items()
        }

    print(f"[DEBUG] Detected layout: {layout}")
    for tgt, files in target_map.items():
        print(f"  Target: {tgt}, Files: {len(files)}")

    # 4) 사용자 정의 디버깅 함수 수집 (정밀 모드: 타겟 전체 / Fallback: 전체)
    user_defined: Set[str] = set()
    all_files = set().union(*target_map.values()) if target_map else set()
    for fp in all_files:
        try:
            for line in Path(fp).read_text(encoding="utf-8").splitlines():
                indent = len(line) - len(line.lstrip())
                if indent != 0:      # 타입/클래스 내부 메서드는 전역 오버라이드로 보지 않음
                    continue
                m = DEBUG_FUNC_DEF_RE.match(line)
                if m:
                    user_defined.add(m.group(1))
        except Exception:
            pass

    # 5) Fallback 전용: 보수 정책 — 전역 shadowing 집합 + (선택) 디렉토리 맵
    global_shadowed = _global_shadowing_set(all_files) if 'fallback' in locals() and fallback else None
    dir_shadowed = _dir_shadowing_map(all_files) if 'fallback' in locals() and fallback else None

    # 6) 호출 탐지
    per_file_hits: Dict[Path, List[Tuple[int,int]]] = defaultdict(list)
    for fp in all_files:
        spans = _regex_find_calls(
            fp,
            user_defined,
            fallback='fallback' in locals() and fallback,
            dir_shadowed=dir_shadowed,
            global_shadowed=global_shadowed,
        )
        if spans:
            per_file_hits[fp].extend(spans)

    # 7) 리포트 출력
    lines_for_report = _group_entries_for_report(per_file_hits)
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(f"# Layout: {layout}\n")
        f.write("# --------------------------------------\n")
        if lines_for_report:
            f.write("\n".join(lines_for_report))
        else:
            f.write("No debug symbols found.\n")
    print(f"[완료] 보고서 생성: {out_path} (총 {sum(len(v) for v in per_file_hits.values())}개 항목)")

    # 8) 수정 모드
    if apply_removal and wrap_in_debug:
        print("[WARN] --remove 와 --wrap-in-debug 은 동시에 사용할 수 없습니다. 리포트만 생성합니다.")
        return
    if apply_removal:
        if per_file_hits:
            _apply_remove(per_file_hits)
            print("[삭제] 디버깅 호출 라인을 소스에서 제거했습니다.")
    elif wrap_in_debug:
        _apply_wrap_debug(per_file_hits)
        print("[래핑] 디버깅 호출을 #if DEBUG ... #endif 로 감쌌습니다.")


# ---------- 8. 백업 복구 ------------------------------------------------------
def restore_debug_files(root_dir: str | None = None) -> None:
    base = Path(root_dir).resolve() if root_dir else Path.cwd()
    restored = 0
    for bak in base.rglob(f"*{BACKUP_EXT}"):
        orig = bak.with_suffix(bak.suffix[:-len(BACKUP_EXT)])
        try:
            shutil.move(bak, orig)
            restored += 1
            print(f"[RESTORED] {orig}")
        except Exception as e:
            print(f"[WARN] {bak} → {orig}: {e}")
    if restored == 0:
        print("No backups found.")
    else:
        print(f"✔ Restored {restored} file(s).")



# ---------- 모듈 루트 탐지 (module_debug_runner.py에서 병합) -----------------------
MODULE_MARKERS = ("Workspace.swift", "Package.swift", "Project.swift")
XCODEPROJ = ".xcodeproj"

def find_module_roots(root: Path):
    """
    1) If Workspace.swift exists at root, parse its projects patterns and resolve those directories.
    2) Otherwise, scan for Package.swift, Project.swift, *.xcodeproj.
    3) If still none, fall back to root as module.
    4) Remove nested duplicates.
    """
    roots = set()
    workspace_file = root / "Workspace.swift"
    patterns = []
    if workspace_file.exists():
        try:
            text = workspace_file.read_text(encoding="utf-8")
            m = re.search(r'projects\s*:\s*\[([^\]]*)\]', text)
            if m:
                inner = m.group(1)
                patterns = re.findall(r'["\']([^"\']+)["\']', inner)
        except Exception:
            patterns = []

    if patterns:
        import glob
        for pat in patterns:
            for match in glob.glob(str(root / pat), recursive=True):
                path = Path(match)
                if path.is_dir():
                    roots.add(path.resolve())
    else:
        for marker in MODULE_MARKERS:
            for f in root.rglob(marker):
                roots.add(f.parent.resolve())
        for xp in root.rglob(f"*{XCODEPROJ}"):
            roots.add(xp.parent.resolve())

    if not roots and workspace_file.exists():
        roots.add(root)

    cleaned = set()
    for candidate in sorted(roots, key=lambda p: len(str(p))):
        if not any(other != candidate and candidate.is_relative_to(other) for other in cleaned):
            cleaned.add(candidate)
    return sorted(cleaned)


# ---------- CLI ----------------------------------------------------------------
if __name__ == "__main__":
    import argparse

    ap = argparse.ArgumentParser(
        description="Module-aware Swift debug symbol reporter",
        formatter_class=argparse.RawTextHelpFormatter,
    )
    ap.add_argument("path", help="프로젝트 루트 디렉터리")
    ap.add_argument("-o", "--output", default="debug_report_all.txt",
                    help="통합 보고서 출력 파일명")
    g = ap.add_mutually_exclusive_group()
    g.add_argument("--remove", action="store_true", help="탐지된 호출 삭제")
    g.add_argument("--wrap-in-debug", action="store_true", help="탐지된 호출 래핑")
    args = ap.parse_args()

    project_root = Path(args.path).resolve()
    if not project_root.is_dir():
        sys.exit(f"Error: {project_root} is not a directory.")

    # Find module roots
    module_roots = find_module_roots(project_root)
    if not module_roots:
        sys.exit("No modules found under given path.")

    print("Detected modules:")
    for m in module_roots:
        print("  -", m.relative_to(project_root))

    # Initialize combined report
    combined_file = project_root / args.output
    with open(combined_file, "w", encoding="utf-8") as cf:
        cf.write("# Combined Debug Symbol Report\n\n")

    # For each module, generate report and append
    for mod in module_roots:
        mod_name = str(mod.relative_to(project_root)).replace("/", "_") or "root"
        print(f"\n>>> Generating for module: {mod_name}")
        tmp = project_root / f".tmp_debug_{mod_name}.txt"
        try:
            generate_debug_report(
                str(mod),
                str(tmp),
                apply_removal=args.remove,
                wrap_in_debug=args.wrap_in_debug
            )
            with open(combined_file, "a", encoding="utf-8") as cf, open(tmp, "r", encoding="utf-8") as tf:
                cf.write(f"## Module: {mod_name}\n")
                cf.write(tf.read())
                cf.write("\n\n")
            os.remove(tmp)
        except Exception as e:
            print(f"[ERROR] Module {mod_name} failed: {e}")

    print(f"\n[완료] 통합 보고서 생성: {combined_file}")