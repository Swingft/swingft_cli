"""
Facade for config APIs, re-exporting split core modules.
"""
from __future__ import annotations

from typing import Any, Dict, Iterable, List, Tuple

from swingft_cli.core.config.loader import load_config_or_exit
from swingft_cli.core.config.rules import (
    extract_rule_patterns,
    summarize_identifier_presence,
    clear_identifier_cache,
)

# Backwards-compatible APIs
from swingft_cli.core.config.rules import scan_swift_identifiers as scan_swift_identifiers  # re-export

def summarize_risks_and_confirm(config: Dict[str, Any], auto_yes: bool = False) -> bool:
    """Summarize risks and get user confirmation"""
    risks = summarize_risks(config)
    if not risks:
        print("설정 검토: 위험 요소 없음 ✅")
        return True
    
    print("\n설정 검토: 위험 요소 발견:")
    for title, desc in risks:
        print(f"  - {title}: {desc}")
    
    if auto_yes:
        print("auto_yes=True 로 설정되어 자동으로 계속 진행합니다.")
        return True
    
    try:
        ans = input("\n계속 진행하시겠습니까? [y/N]: ").strip().lower()
        return ans in ("y", "yes")
    except (EOFError, KeyboardInterrupt):
        print("\n사용자에 의해 취소되었습니다.")
        return False


def summarize_risks(config: Dict[str, Any]) -> List[Tuple[str, str]]:
    """Summarize risks in configuration"""
    risks: List[Tuple[str, str]] = []
    
    # Check for conflicts between include and exclude
    for category in ("obfuscation", "encryption"):
        include_items = set(config.get("include", {}).get(category, []) or [])
        exclude_items = set(config.get("exclude", {}).get(category, []) or [])
        
        conflict = include_items & exclude_items
        if conflict:
            risks.append((f"{category}에서 include와 exclude가 충돌", ", ".join(list(conflict)[:5])))
    
    # Check for wildcard patterns
    for section in ("include", "exclude"):
        for category in ("obfuscation", "encryption"):
            items = config.get(section, {}).get(category, []) or []
            if any(p == "*" for p in items):
                risks.append((f"{section}.{category}에 '*' 단독 패턴 사용", "모든 항목을 포괄합니다. 의도된 것인지 확인하세요."))
    
    return risks


def extract_rule_patterns(config: Dict[str, Any]) -> Dict[str, List[str]]:
    """Extract rule patterns from config"""
    patterns = {}
    
    # Extract include patterns
    for category in ("obfuscation", "encryption"):
        key = f"{category}_include"
        patterns[key] = list(config.get("include", {}).get(category, []) or [])
    
    # Extract exclude patterns
    for category in ("obfuscation", "encryption"):
        key = f"{category}_exclude"
        patterns[key] = list(config.get("exclude", {}).get(category, []) or [])
    
    return patterns
