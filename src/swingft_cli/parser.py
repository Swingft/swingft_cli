

"""
parser.py: Project layout detection and target-to-Swift-file mapping for Swift projects.
"""

from pathlib import Path
import re
import subprocess
import json
import glob
from collections import defaultdict
from typing import Dict, Set, Tuple, List, Optional

# Directories to exclude from Swift file scans
EXCLUDE_DIR_NAMES = {
    ".build", "Pods", "Carthage", "Checkouts",
    ".swiftpm", "DerivedData", "Tuist", ".xcodeproj"
}

def _is_external(path: Path) -> bool:
    """Return True if the path is in an external or generated directory."""
    return any(part in EXCLUDE_DIR_NAMES for part in path.parts)

def detect_layout(project_root: Path) -> Tuple[str, Path]:
    """
    Detect project layout.
    Returns (layout, anchor_path) where layout is one of:
      - "file": single Swift file
      - "spm": Swift Package Manager
      - "xcode": Xcode project
      - "tuist": Tuist project
      - "unknown": fallback
    """
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

def _spm_target_map(project_root: Path) -> Dict[str, Set[Path]]:
    """Use `swift package dump-package` to map target names to Swift files."""
    try:
        result = subprocess.run(
            ["swift", "package", "dump-package", "--package-path", str(project_root)],
            check=True, capture_output=True, text=True
        )
        pkg = json.loads(result.stdout)
    except Exception:
        return {}
    mapping: Dict[str, Set[Path]] = defaultdict(set)
    for tgt in pkg.get("targets", []):
        if tgt.get("type") == "test":
            continue
        name = tgt["name"]
        src_dir = project_root / tgt.get("path", f"Sources/{name}")
        if not src_dir.exists():
            continue
        for file in src_dir.rglob("*.swift"):
            mapping[name].add(file.resolve())
    return mapping

def spm_target_map_recursive(repo_root: Path) -> Dict[str, Set[Path]]:
    """
    Recursively scan for Package.swift under repo_root to handle monorepos.
    Prefix target names with relative package path if nested.
    """
    merged: Dict[str, Set[Path]] = defaultdict(set)
    for pkg_file in repo_root.rglob("Package.swift"):
        pkg_root = pkg_file.parent
        submap = _spm_target_map(pkg_root)
        prefix = "" if pkg_root == repo_root else f"{pkg_root.relative_to(repo_root)}/"
        for name, files in submap.items():
            merged[f"{prefix}{name}"].update(files)
    return merged

# Patterns for parsing Xcode project file
PBX_FILE_REF = re.compile(r'\s([0-9A-F]{24}) /\* (.+?\.swift) ')
PBX_BUILD_FILE = re.compile(r'([0-9A-F]{24}) /\* .+ in Sources \*/ = {isa = PBXBuildFile; fileRef = ([0-9A-F]{24})')
PBX_NATIVE_TARGET = re.compile(r'(\w{24}) /\* (.+?) \*/ = {[^}]*?isa = PBXNativeTarget;', re.S)
PBX_SOURCES_PHASE = re.compile(r'buildPhases\s*=\s*\((?:.|\n)*?([0-9A-F]{24}) /\* Sources \*/', re.S)
PBX_PHASE_FILE_IDS = re.compile(r'\b([0-9A-F]{24})\b')

def _resolve_swift_from_comment(pbxproj: Path, name: str) -> Optional[Path]:
    """
    Resolve a Swift file path given the comment or relative path from PBX file reference.
    """
    root = pbxproj.parent.parent
    candidate = Path(name)
    if "/" in name:
        path = (root / candidate).resolve()
        if path.exists():
            return path
    matches = [
        p for p in root.rglob(candidate.name)
        if p.suffix == ".swift" and not _is_external(p)
    ]
    if len(matches) == 1:
        return matches[0].resolve()
    return None

def pbxproj_target_map(pbxproj: Path) -> Dict[str, Set[Path]]:
    """
    Parse project.pbxproj to map target names to Swift file paths.
    """
    if not pbxproj.exists():
        return {}
    text = pbxproj.read_text(errors="ignore")
    file_refs = {m[0]: m[1].strip() for m in PBX_FILE_REF.findall(text)}
    build_refs = {m[0]: m[1] for m in PBX_BUILD_FILE.findall(text)}

    phase_to_files: Dict[str, List[str]] = defaultdict(list)
    for phase_id, blob in re.findall(r'([0-9A-F]{24}) /\* Sources \*/ = {[^}]+?files = \(([^)]+)\)', text, re.S):
        phase_to_files[phase_id] = PBX_PHASE_FILE_IDS.findall(blob)

    targets: Dict[str, Set[Path]] = defaultdict(set)
    for match in PBX_NATIVE_TARGET.finditer(text):
        tid, name = match.group(1), match.group(2)
        if name.endswith("Tests"):
            continue
        block_end = text.find("};", match.start())
        block = text[match.start(): block_end+2]
        for phase in PBX_SOURCES_PHASE.findall(block):
            for bf in phase_to_files.get(phase, []):
                ref = build_refs.get(bf)
                rel = file_refs.get(ref, "")
                if rel.endswith(".swift"):
                    path = _resolve_swift_from_comment(pbxproj, rel)
                    if path:
                        targets[name].add(path)
    return targets

def find_module_roots(root: Path) -> List[Path]:
    """
    Find module roots under a workspace or repo:
      - Use Workspace.swift 'projects' patterns if present
      - Else scan for Package.swift, Project.swift, or .xcodeproj
      - Deduplicate nested paths
    """
    roots = set()
    workspace = root / "Workspace.swift"
    if workspace.exists():
        content = workspace.read_text(errors="ignore")
        patterns = re.findall(r'projects\s*:\s*\[([^\]]*)\]', content)
        if patterns:
            for pat in re.findall(r'["\']([^"\']+)["\']', patterns[0]):
                for match in glob.glob(str(root / pat), recursive=True):
                    path = Path(match)
                    if path.is_dir():
                        roots.add(path.resolve())
    if not roots:
        markers = ("Package.swift", "Project.swift")
        for marker in markers:
            for f in root.rglob(marker):
                roots.add(f.parent.resolve())
        for xp in root.rglob("*.xcodeproj"):
            roots.add(xp.parent.resolve())
    # Eliminate nested paths
    cleaned: List[Path] = []
    for p in sorted(roots, key=lambda x: len(str(x))):
        if not any(p != o and p.is_relative_to(o) for o in cleaned):
            cleaned.append(p)
    return cleaned