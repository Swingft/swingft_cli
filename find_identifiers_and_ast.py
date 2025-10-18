#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
find_identifiers_and_ast.py

사용법:
  # 여러 식별자를 콤마로
  python3 find_identifiers_and_ast.py /path/to/project --ids-csv apiKey,authToken,processPayment

  # 또는 --id를 반복해서
  python3 find_identifiers_and_ast.py /path/to/project --id apiKey --id authToken --id processPayment

옵션:
  --ctx-lines N   : 스니펫 앞뒤 문맥 줄 수 (기본 30)
  --output FILE   : 결과를 파일로 저장(기본은 stdout 출력)

동작:
  - 프로젝트에서 .swift 파일을 모두 찾되, 빌드/서브모듈 폴더는 스킵
  - 각 식별자에 대해 "처음 등장하는 파일"만 기록
  - 스니펫은 등장 라인 기준 ±N줄
  - AST는 로컬 분석기가 있으면 실행:
      ./ast_analyzers/sensitive/SwiftASTAnalyzer
      ./ast_analyzers/sensitive/swift_ast_analyzer
      ./ast_analyzers/SwiftASTAnalyzer
    실행 실패/부재 시 간단한 정규식 휴리스틱으로 추출
"""

from __future__ import annotations

import os
import sys
import re
import json
import argparse
import subprocess
from pathlib import Path
from typing import List, Dict, Any, Optional, Tuple

# 스킵할 디렉토리
SKIP_DIRS = {".build", "build", "Pods", "Carthage", "DerivedData", "node_modules", ".git"}

def find_swift_files(root: str) -> List[str]:
    root_p = Path(root)
    out: List[str] = []
    for p in root_p.rglob("*.swift"):
        if any(part in SKIP_DIRS for part in p.parts):
            continue
        out.append(str(p))
    return out

def first_match_snippet(path: str, identifier: str, ctx_lines: int = 30, max_chars: int = 8000) -> Optional[Dict[str, Any]]:
    """파일에서 식별자 첫 등장 위치 주변 스니펫(±ctx_lines)을 반환"""
    try:
        with open(path, 'r', encoding='utf-8', errors='ignore') as f:
            lines = f.readlines()
    except Exception:
        return None

    pattern = re.compile(r"\b" + re.escape(identifier) + r"\b")
    for idx, line in enumerate(lines):
        if pattern.search(line):
            start = max(0, idx - ctx_lines)
            end = min(len(lines), idx + ctx_lines + 1)
            snippet = "".join(lines[start:end])
            if len(snippet) > max_chars:
                snippet = snippet[:max_chars] + "\n... [truncated]"
            return {
                "file": path,
                "line_number": idx + 1,          # 1-based
                "context_start_line": start + 1, # 1-based
                "context_end_line": end,         # 1-based inclusive
                "snippet": snippet
            }
    return None

def run_external_swift_ast_analyzer(swift_file: str) -> Optional[Any]:
    """
    외부 Swift AST 분석기 실행 시도.
    stdout이 JSON이면 파싱해서 반환, 아니면 raw 텍스트로 감싸서 반환.
    실패하면 None.
    """
    base = Path(__file__).parent
    candidates = [
        base / "ast_analyzers" / "sensitive" / "SwiftASTAnalyzer",
        base / "ast_analyzers" / "sensitive" / "swift_ast_analyzer",
        base / "ast_analyzers" / "SwiftASTAnalyzer",
    ]
    for cand in candidates:
        exe = str(cand)
        if os.path.isfile(exe) and os.access(exe, os.X_OK):
            try:
                proc = subprocess.run([exe, swift_file], capture_output=True, text=True, timeout=20)
                if proc.returncode == 0 and proc.stdout:
                    try:
                        return json.loads(proc.stdout)
                    except Exception:
                        return {"raw": proc.stdout}
            except Exception:
                continue
    return None

def heuristic_extract_ast(swift_file: str) -> List[Dict[str, Any]]:
    """
    외부 분석기가 없을 때를 위한 간단한 휴리스틱 AST 추출.
    몇 가지 선언 패턴을 정규식으로 찾아 symbolName/Kind 목록을 만든다.
    """
    symbols: List[Dict[str, Any]] = []
    try:
        text = Path(swift_file).read_text(encoding='utf-8', errors='ignore')
    except Exception:
        return symbols

    patterns = [
        (r'\bstruct\s+([A-Za-z_][A-Za-z0-9_]*)', "struct"),
        (r'\bclass\s+([A-Za-z_][A-Za-z0-9_]*)', "class"),
        (r'\benum\s+([A-Za-z_][A-Za-z0-9_]*)', "enum"),
        (r'\bfunc\s+([A-Za-z_][A-Za-z0-9_]*(?:\([^\)]*\))?)', "method"),
        (r'@State\s+private\s+var\s+([A-Za-z_][A-Za-z0-9_]*)', "variable"),
        (r'\b(?:let|var)\s+([A-Za-z_][A-Za-z0-9_]*)', "variable"),
    ]

    seen = set()
    for pat, kind in patterns:
        for m in re.finditer(pat, text):
            name = m.group(1)
            if not name:
                continue
            key = (name, kind)
            if key in seen:
                continue
            seen.add(key)
            symbols.append({"symbolName": name, "symbolKind": kind})

    return symbols

def build_report_for_identifiers(project_root: str, identifiers: List[str], ctx_lines: int = 30) -> Dict[str, Any]:
    """
    프로젝트 전체에서 각 식별자가 포함된 첫 Swift 파일, 스니펫, AST(있는 경우)를 모아 리포트 생성.
    """
    swift_files = find_swift_files(project_root)
    report: Dict[str, Any] = {
        "project_root": project_root,
        "files_searched": len(swift_files),
        "identifiers": {}
    }

    for ident in identifiers:
        ident = ident.strip()
        if not ident:
            continue

        found_info = None
        for f in swift_files:
            snippet = first_match_snippet(f, ident, ctx_lines=ctx_lines)
            if snippet:
                found_info = snippet
                ast_result = run_external_swift_ast_analyzer(f)
                if ast_result is None:
                    ast_result = heuristic_extract_ast(f)
                report["identifiers"][ident] = {
                    "found": True,
                    "file": snippet["file"],
                    "line_number": snippet["line_number"],
                    "context_start_line": snippet["context_start_line"],
                    "context_end_line": snippet["context_end_line"],
                    "snippet": snippet["snippet"],
                    "ast": ast_result
                }
                break

        if not found_info:
            report["identifiers"][ident] = {"found": False}

    return report

def main(argv: Optional[List[str]] = None):
    ap = argparse.ArgumentParser(description="Find identifiers in a Swift project and produce AST/snippet for the containing file.")
    ap.add_argument("project_root", type=str, help="Project root path")
    ap.add_argument("--id", action="append", dest="ids", help="Identifier to search for (can be repeated)")
    ap.add_argument("--ids-csv", type=str, help="Comma-separated list of identifiers")
    ap.add_argument("--ctx-lines", type=int, default=30, help="Snippet context lines (default 30)")
    ap.add_argument("--output", type=str, help="Output JSON file (if omitted prints to stdout)")
    args = ap.parse_args(argv)

    ids: List[str] = []
    if args.ids:
        ids.extend(args.ids)
    if args.ids_csv:
        ids.extend([x.strip() for x in args.ids_csv.split(",") if x.strip()])

    if not ids:
        print("No identifiers provided. Use --id or --ids-csv", file=sys.stderr)
        sys.exit(2)

    project_root = args.project_root
    if not os.path.isdir(project_root):
        print(f"Project root not found: {project_root}", file=sys.stderr)
        sys.exit(2)

    report = build_report_for_identifiers(project_root, ids, ctx_lines=args.ctx_lines)
    out_json = json.dumps(report, ensure_ascii=False, indent=2)

    if args.output:
        with open(args.output, 'w', encoding='utf-8') as f:
            f.write(out_json)
        print(f"Wrote report to {args.output}")
    else:
        print(out_json)

if __name__ == "__main__":
    main()