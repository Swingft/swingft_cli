"""
utils.py: Shared constants and patterns for debug-symbol detection.
"""

import re
from typing import List, Set

# Debug function names to detect
DEBUG_FUNC_NAMES: List[str] = [
    "print",
    "debugPrint",
    "NSLog",
    "assert",
    "assertionFailure",
    "dump",
]

# Mapping from function name to regex for unprefixed calls
PATTERN_MAP = {
    name: re.compile(rf'(?<![\w\.]){name}\s*\(')
    for name in DEBUG_FUNC_NAMES
}

# Allow Swift.<func>() calls even if shadowed
SWIFT_PREFIX_PATTERNS = {
    name: re.compile(rf'\bSwift\.{name}\s*\(')
    for name in DEBUG_FUNC_NAMES
}

# Thread.callStackSymbols detection
THREAD_STACK_RE = re.compile(r'Thread\.callStackSymbols')

# Regex to detect function definitions named as debug functions
DEBUG_FUNC_DEF_RE = re.compile(
    r'^\s*(?:public|internal|private|fileprivate)?\s*'
    r'(?:final\s+)?(?:static\s+)?func\s+('
    + "|".join(DEBUG_FUNC_NAMES)
    + r')\b'
)

# Generic function definition line detection
FUNC_DEF_RE = re.compile(
    r'^\s*(?:public|internal|private|fileprivate)?\s*'
    r'(?:final\s+)?(?:static\s+)?func\b'
)

# Maximum lines to lookahead when balancing parentheses/braces
MAX_LOOKAHEAD_LINES = 40

# Backup file extension for removals
BACKUP_EXT = ".debugbak"

# Directories to exclude from scans
EXCLUDE_DIR_NAMES: Set[str] = {
    ".build",
    "Pods",
    "Carthage",
    "Checkouts",
    ".swiftpm",
    "DerivedData",
    "Tuist",
    ".xcodeproj",
}