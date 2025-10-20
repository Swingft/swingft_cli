#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
find_identifiers_and_ast_dual.py

- 원래 리포트(JSON) 생성 기능 유지
- ✅ 모든 식별자/스니펫/AST를 한 파일(payload.json)로 합쳐서 생성
- ✅ AST Symbol Information을 식별자별로 '정의/참조/호출' 라인 및 코드 일부까지 포함해 LLM 판단에 직결되도록 구성
"""

from __future__ import annotations

import os
import sys
import re
import json
import argparse
from pathlib import Path
from typing import Dict, List, Any, Optional, Tuple

# Support both package execution (-m) and direct script execution
try:
    # When executed as a module within a package
    from .find_identifiers_and_ast import build_report_for_identifiers  # type: ignore
except Exception:
    # Fallback for direct script execution: add repo src root to sys.path
    from pathlib import Path as _P
    import sys as _S
    _FILE = _P(__file__).resolve()
    # .../src/swingft_cli/core/preflight/find_identifiers_and_ast_dual.py -> parents[4] == src
    _SRC_ROOT = _FILE.parents[4]
    if str(_SRC_ROOT) not in _S.path:
        _S.path.insert(0, str(_SRC_ROOT))
    from swingft_cli.core.preflight.find_identifiers_and_ast import build_report_for_identifiers  # type: ignore

INSTRUCTION = (
    "In the following Swift code, find all identifiers related to sensitive logic. Provide the names and reasoning as a JSON object."
)

# -------------------------
# Helpers to enrich symbols
# -------------------------

_DEF_PATTERNS = [
    # struct/class/enum
    (lambda name: re.compile(rf'\bstruct\s+{re.escape(name)}\b')),
    (lambda name: re.compile(rf'\bclass\s+{re.escape(name)}\b')),
    (lambda name: re.compile(rf'\benum\s+{re.escape(name)}\b')),
    # method (allow params)
    (lambda name: re.compile(rf'\bfunc\s+{re.escape(name)}\b')),
    # variable
    (lambda name: re.compile(rf'\b(?:let|var)\s+{re.escape(name)}\b')),
    # @State private var foo
    (lambda name: re.compile(rf'@State\s+private\s+var\s+{re.escape(name)}\b')),
]

def _load_lines(file_path: str) -> List[str]:
    try:
        with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
            return f.readlines()
    except Exception:
        return []

def _is_definition_line(name: str, line: str) -> bool:
    for mk in _DEF_PATTERNS:
        if mk(name).search(line):
            return True
    return False

def _is_call_usage(name: str, line: str) -> bool:
    # foo( ... )  (avoid func definition)
    if re.search(rf'\b{re.escape(name)}\s*\(', line) and not re.search(rf'\bfunc\s+{re.escape(name)}\b', line):
        return True
    return False

def _occurrences_for_symbol(name: str, lines: List[str]) -> List[Dict[str, Any]]:
    """
    Return occurrences across the file:
      - role: definition | reference | call
      - line: 1-based line number
      - code: the exact line text trimmed
    """
    occ: List[Dict[str, Any]] = []
    pat_word = re.compile(rf'\b{re.escape(name)}\b')
    for idx, raw in enumerate(lines):
        if not pat_word.search(raw):
            continue
        code_line = raw.rstrip("\n")
        role = "reference"
        if _is_definition_line(name, raw):
            role = "definition"
        elif _is_call_usage(name, raw):
            role = "call"
        occ.append({
            "role": role,
            "line": idx + 1,
            "code": code_line.strip()
        })
    return occ

def _method_body_range(name: str, lines: List[str]) -> Optional[Tuple[int, int]]:
    """
    If symbol is a method, find its body range by line-wise brace counting.
    Returns (start_line, end_line) 1-based inclusive.
    """
    header_pat = re.compile(rf'\bfunc\s+{re.escape(name)}\b')
    start_idx = None
    for i, ln in enumerate(lines):
        if header_pat.search(ln):
            start_idx = i
            break
    if start_idx is None:
        return None
    # From header line onward, find first '{' then match until depth returns to 0
    depth = 0
    seen_open = False
    end_idx = None
    for i in range(start_idx, len(lines)):
        ln = lines[i]
        for ch in ln:
            if ch == '{':
                depth += 1
                seen_open = True
            elif ch == '}':
                depth -= 1
                if seen_open and depth == 0:
                    end_idx = i
                    break
        if end_idx is not None:
            break
    if end_idx is None:
        return None
    # Convert 0-based to 1-based inclusive
    return (start_idx + 1, end_idx + 1)

def _refs_in_body(name: str, lines: List[str], body_range: Tuple[int, int], candidates: List[str]) -> List[str]:
    s, e = body_range  # 1-based
    body_text = "".join(lines[s-1:e])
    out: List[str] = []
    seen = set()
    for cand in candidates:
        if cand == name:
            continue
        if re.search(rf'\b{re.escape(cand)}\b', body_text):
            if cand not in seen:
                seen.add(cand)
                out.append(cand)
        if len(out) >= 12:
            break
    return out

def _kind_lookup_from_ast_list(ast_list: Any) -> Dict[str, str]:
    """
    From heuristic/external AST (list of {"symbolName","symbolKind"}), produce a name->kind map.
    """
    mp: Dict[str, str] = {}
    if isinstance(ast_list, list):
        for item in ast_list:
            if isinstance(item, dict):
                nm = item.get("symbolName")
                kd = item.get("symbolKind")
                if isinstance(nm, str) and isinstance(kd, str):
                    mp[nm] = kd
    return mp

# -------------------------
# Payload writer
# -------------------------

def write_combined_payload_file(report: dict, out_path: Path, target_ids: List[str]):
    """
    전달된 식별자 목록(target_ids)에 대해서만 payload.json을 생성한다.
    - Swift Source Code 블록: 대상 식별자들이 속한 **각 파일의 전체 본문**을 파일 경계 주석과 함께 연결
    - AST Symbol Information (JSON): 각 파일 기준 **전체 AST**(가능 시 `ast_full`, 없으면 `ast`)를 모두 포함
    """
    all_id_map = report.get("identifiers", {}) or {}

    # 전체 파일 기준으로 코드와 AST를 구성
    unique_files: List[str] = []
    for ident in target_ids:
        info = all_id_map.get(ident, {})
        if not info.get("found"):
            continue
        fpath = info.get("file", "")
        if fpath and fpath not in unique_files:
            unique_files.append(fpath)

    # 코드: 각 파일의 전체 내용을 순서대로 연결. 파일 경계 주석 없이.
    code_sections: List[str] = []
    for fpath in unique_files:
        try:
            with open(fpath, "r", encoding="utf-8", errors="ignore") as f:
                full_text = f.read()
        except Exception:
            full_text = ""
        code_sections.append(full_text.rstrip())
    combined_code = ("\n\n").join(code_sections).strip()

    # AST: 가능하면 각 식별자 엔트리에서 전체 AST를 수집.
    # 우선순위: info['ast_full'] → info['ast'] → []
    ast_aggregate: List[Any] = []
    seen_ast_serialized = set()
    for ident in target_ids:
        info = all_id_map.get(ident, {})
        if not info.get("found"):
            continue
        ast_full = info.get("ast_full")
        ast_any = ast_full if ast_full is not None else info.get("ast")
        if ast_any is None:
            continue
        # ast_any 가 dict 또는 list 모두 가능하므로 직렬화로 중복 제거
        try:
            serialized = json.dumps(ast_any, ensure_ascii=False, sort_keys=True)
        except Exception:
            # 직렬화 실패 시 문자열로 강제
            serialized = str(ast_any)
        if serialized in seen_ast_serialized:
            continue
        seen_ast_serialized.add(serialized)
        ast_aggregate.append(ast_any)

    # 단일 JSON으로 보기 좋게 구성: 파일별 전체 코드 + AST 전체 묶음
    pretty_ast = json.dumps(ast_aggregate, ensure_ascii=False, indent=2)
    payload = {
        "instruction": INSTRUCTION,
        "input": (
            f"**Swift Source Code:**\n```swift\n{combined_code}\n```\n\n"
            f"**AST Symbol Information (JSON):**\n```\n{pretty_ast}\n```"
        )
    }

    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    print(f"  ↳ wrote combined payload: {out_path}")

def _write_per_identifier_payload_files_from_report(report: dict, out_dir: Path, target_ids: List[str], ctx_lines: int):
    """
    각 식별자마다 payload JSON을 별도로 생성한다.
    - 코드: 해당 식별자가 속한 **소스코드 전체 파일**
    - AST: 해당 파일의 **전체 AST** (`ast_full` → `ast` → 빈 배열)
    파일명: <identifier>.payload.json
    """
    all_id_map = report.get("identifiers", {}) or {}
    out_dir.mkdir(parents=True, exist_ok=True)

    def infer_kind_from_text(file_path: str, ident: str) -> str:
        try:
            with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
                text = f.read()
        except Exception:
            return "unknown"
        if re.search(rf'\bfunc\s+{re.escape(ident)}\b', text):
            return "method"
        if re.search(rf'\b(?:let|var)\s+{re.escape(ident)}\b', text):
            return "variable"
        if re.search(rf'\bstruct\s+{re.escape(ident)}\b', text):
            return "struct"
        if re.search(rf'\bclass\s+{re.escape(ident)}\b', text):
            return "class"
        if re.search(rf'\benum\s+{re.escape(ident)}\b', text):
            return "enum"
        if re.search(rf'\bextension\s+{re.escape(ident)}\b', text):
            return "extension"
        return "unknown"

    def find_decl_line_index(ident: str, lines: List[str]) -> Optional[int]:
        # method
        pat_method = re.compile(rf'\bfunc\s+{re.escape(ident)}\b')
        # variable
        pat_var = re.compile(rf'\b(?:let|var)\s+{re.escape(ident)}\b')
        # types
        pat_struct = re.compile(rf'\bstruct\s+{re.escape(ident)}\b')
        pat_class = re.compile(rf'\bclass\s+{re.escape(ident)}\b')
        pat_enum = re.compile(rf'\benum\s+{re.escape(ident)}\b')
        pat_ext = re.compile(rf'\bextension\s+{re.escape(ident)}\b')
        for i, ln in enumerate(lines):
            if pat_method.search(ln) or pat_var.search(ln) or pat_struct.search(ln) or pat_class.search(ln) or pat_enum.search(ln) or pat_ext.search(ln):
                return i
        # fallback: first occurrence line
        pat_any = re.compile(rf'\b{re.escape(ident)}\b')
        for i, ln in enumerate(lines):
            if pat_any.search(ln):
                return i
        return None

    def _block_range(keyword: str, name: str, lines: List[str]) -> Optional[Tuple[int,int]]:
        """
        Generic block detector for struct/class/enum/extension definitions.
        """
        header_pat = re.compile(rf'\b{keyword}\s+{re.escape(name)}\b')
        start_idx = None
        for i, ln in enumerate(lines):
            if header_pat.search(ln):
                start_idx = i
                break
        if start_idx is None:
            return None
        text = "".join(lines[start_idx:])
        open_idx = text.find("{")
        if open_idx < 0:
            return None
        depth = 0
        for j, ch in enumerate(text[open_idx:], start=open_idx):
            if ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    sub = text[: j + 1]
                    end_line = start_idx + sub.count("\n")
                    return (start_idx + 1, end_line)
        return None

    for ident in target_ids:
        info = all_id_map.get(ident, {})
        if not info.get("found"):
            continue

        file_path = info.get("file", "")
        ln = info.get("line_number", "")
        lines = _load_lines(file_path)

        # resolve kind
        kind = info.get("kind")
        if kind is None:
            ast_list = info.get("ast")
            if isinstance(ast_list, list):
                for item in ast_list:
                    if isinstance(item, dict) and item.get("symbolName") == ident:
                        kind = item.get("symbolKind", None)
                        break
        if kind is None:
            kind = infer_kind_from_text(file_path, ident)

        # 전체 파일 내용
        try:
            with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
                full_text = f.read()
        except Exception:
            full_text = ""
        code_block = full_text.rstrip()

        # 전체 AST: 우선 ast_full → ast → 빈 배열
        ast_full = info.get("ast_full")
        ast_any = ast_full if ast_full is not None else info.get("ast")
        if ast_any is None:
            ast_any = []
        pretty_ast = json.dumps(ast_any, ensure_ascii=False, indent=2)

        payload = {
            "instruction": INSTRUCTION,
            "input": (
                f"**Swift Source Code:**\n```swift\n{code_block}\n```\n\n"
                f"**AST Symbol Information (JSON):**\n```\n{pretty_ast}\n```"
            )
        }

        out_file = out_dir / f"{ident}.payload.json"
        with open(out_file, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)
        #print(f"  ↳ wrote per-identifier payload: {out_file}")

def write_per_identifier_payload_files(project_root: str, identifiers, out_dir: str, ctx_lines: int = 30):
    """
    Wrapper for loader usage.
    Builds a report from project_root + identifiers, then writes per-identifier payloads to out_dir.
    Accepts keyword argument `identifiers` as used by loader.py.
    """
    # normalize identifiers
    ids = []
    for x in (identifiers or []):
        try:
            s = str(x).strip()
            if s:
                ids.append(s)
        except Exception:
            continue
    # de-duplicate while preserving order
    ids = list(dict.fromkeys(ids))
    # build report and write payloads
    rpt = build_report_for_identifiers(project_root, ids, ctx_lines=ctx_lines)
    _write_per_identifier_payload_files_from_report(rpt, Path(out_dir), ids, ctx_lines)

# -------------------------
# CLI
# -------------------------

def main():
    ap = argparse.ArgumentParser(description="Find identifiers and produce AST/snippet + single combined payload.json (with occurrences).")
    ap.add_argument("project_root", type=str)
    ap.add_argument("--id", action="append", dest="ids")
    ap.add_argument("--ids-csv", type=str)
    ap.add_argument("--ctx-lines", type=int, default=30)
    ap.add_argument("--output", type=str, default="report.json")
    ap.add_argument("--payload-out", type=str, default="payload.json", help="Single combined payload file path")
    ap.add_argument("--per-id-dir", type=str, default="payloads", help="Directory to write per-identifier payload JSON files")
    args = ap.parse_args()

    ids: List[str] = []
    if args.ids:
        ids.extend(args.ids)
    if args.ids_csv:
        ids.extend([x.strip() for x in args.ids_csv.split(",") if x.strip()])
    if not ids:
        print("No identifiers provided", file=sys.stderr)
        sys.exit(2)
    ids = list(dict.fromkeys(ids))

    report = build_report_for_identifiers(args.project_root, ids, ctx_lines=args.ctx_lines)

    # 전체 리포트 파일
    with open(args.output, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    print(f"✅ wrote main report: {args.output}")

    # 전체를 하나의 payload.json으로 생성 (occurrences 포함)
    write_combined_payload_file(report, Path(args.payload_out), ids)
    print("✅ combined payload generation complete.")

    # 각 식별자별 payload 파일도 생성
    _write_per_identifier_payload_files_from_report(report, Path(args.per_id_dir), ids, args.ctx_lines)

if __name__ == "__main__":
    main()