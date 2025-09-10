#!/usr/bin/env python3
# module_debug_runner.py
"""
루트에서 모듈 루트를 자동으로 탐지하고,
각 모듈별로 last_version.py 의 generate_debug_report 를 호출해
모듈 단위 보고서를 생성하는 스크립트입니다.
"""

import sys
import subprocess
import re
import os
from pathlib import Path

# last_version.py 가 src 폴더에 있다고 가정
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
from last_version import generate_debug_report

# 어떤 파일/디렉터리를 모듈 루트로 볼지 정의
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
            # find projects: [...] line
            m = re.search(r'projects\s*:\s*\[([^\]]*)\]', text)
            if m:
                inner = m.group(1)
                # extract quoted patterns
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
        # 1) Package.swift, Project.swift
        for marker in MODULE_MARKERS:
            for f in root.rglob(marker):
                roots.add(f.parent.resolve())
        # 2) *.xcodeproj
        for xp in root.rglob(f"*{XCODEPROJ}"):
            roots.add(xp.parent.resolve())

    # 3) Fallback: if still none and workspace exists, add root
    if not roots and workspace_file.exists():
        roots.add(root)

    # 4) Remove nested duplicates
    cleaned = set()
    for candidate in sorted(roots, key=lambda p: len(str(p))):
        if not any(other != candidate and candidate.is_relative_to(other) for other in cleaned):
            cleaned.add(candidate)
    return sorted(cleaned)

def main():
    if len(sys.argv) != 2:
        print(f"Usage: {sys.argv[0]} /path/to/project_root")
        sys.exit(1)

    project_root = Path(sys.argv[1]).resolve()
    if not project_root.is_dir():
        print(f"Error: {project_root} is not a directory.")
        sys.exit(2)

    module_roots = find_module_roots(project_root)
    if not module_roots:
        print("No modules found under", project_root)
        sys.exit(0)

    print("Detected modules:")
    for m in module_roots:
        print("  -", m.relative_to(project_root))

    # 통합 보고서 파일 초기화
    combined_file = project_root / "debug_report_all.txt"
    # Clear existing combined report
    with open(combined_file, "w", encoding="utf-8") as cf:
        cf.write("# Combined Debug Symbol Report\n\n")

    # 각 모듈 별로 보고서 생성하여 통합 파일에 append
    for mod in module_roots:
        # 모듈 이름: project_root 로부터 상대경로, 디렉터리 구분자는 '_'
        mod_name = str(mod.relative_to(project_root)).replace("/", "_") or "root"
        print(f"\n>>> Generating report for module '{mod_name}' → debug_report_{mod_name}.txt")
        try:
            temp_out = str(project_root / f".tmp_debug_{mod_name}.txt")
            generate_debug_report(
                str(mod),
                temp_out,
                apply_removal=False,
                wrap_in_debug=False
            )
            # Append to combined report
            with open(combined_file, "a", encoding="utf-8") as cf, open(temp_out, "r", encoding="utf-8") as tf:
                cf.write(f"## Module: {mod_name}\n")
                cf.write(tf.read())
                cf.write("\n\n")
            # Optionally remove temporary file
            os.remove(temp_out)
        except Exception as e:
            print(f"[ERROR] module {mod_name} failed:", e)

    print(f"\n[완료] 통합 보고서 생성: {combined_file}")

if __name__ == "__main__":
    main()