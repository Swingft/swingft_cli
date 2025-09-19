import os
from typing import Iterable, List, Tuple

# Directories to ignore when collecting project files
EXCLUDE_DIR_NAMES = {
    '.build', 'Pods', 'Carthage', 'Checkouts', '.swiftpm', 'DerivedData', 'Tuist', '.xcodeproj'
}

def iter_swift_files(root_dir: str) -> Iterable[Tuple[str, str]]:
    """Yield (abs_path, rel_path) for all .swift files under root_dir, honoring EXCLUDE_DIR_NAMES."""
    for dirpath, dirnames, filenames in os.walk(root_dir):
        parts = set(dirpath.split(os.sep))
        if parts & EXCLUDE_DIR_NAMES:
            continue
        for filename in filenames:
            if filename.endswith('.swift'):
                abs_path = os.path.join(dirpath, filename)
                rel_path = os.path.relpath(abs_path, root_dir)
                yield abs_path, rel_path

def collect_project_sidecar_files(root_dir: str, exts: Tuple[str, ...]) -> List[str]:
    """Return list of project-related files (by extension) under root_dir, honoring EXCLUDE_DIR_NAMES."""
    results: List[str] = []
    for dirpath, dirnames, filenames in os.walk(root_dir):
        parts = set(dirpath.split(os.sep))
        if parts & EXCLUDE_DIR_NAMES:
            continue
        for filename in filenames:
            if filename.endswith(exts):
                results.append(os.path.join(dirpath, filename))
    return results




