

import os
import sys
import json
from typing import Dict, List
from pathlib import Path

def handle_obfuscate(args):
    from swingft_cli.validator import check_permissions
    from swingft_cli.config import load_config_or_exit, summarize_risks_and_confirm, extract_rule_patterns
    from swingft_cli.core.project import iter_swift_files, collect_project_sidecar_files
    from swingft_cli.core.engine import apply_obfuscation
    from swingft_cli.core.fs import read_plist_as_text, read_text_fallback, flatten_relpath_for_sidecar

    check_permissions(args.input, args.output)

    print("Start Swingft ...")
    print_banner()

    config_path = None
    if getattr(args, 'config', None) is not None:
        if isinstance(args.config, str) and args.config.strip():
            config_path = args.config.strip()
        else:
            config_path = 'swingft_config.json'
        if not os.path.exists(config_path):
            print(f"Error: {config_path} not found. You can generate a sample file using the --json option.")
            sys.exit(1)

    patterns: Dict[str, List[str]] = {}
    if config_path:
        config = load_config_or_exit(config_path)
        
        # Check for conflicts with exception_list.json
        _check_exception_conflicts(config_path)
        
        if args.check_rules:
            _check_rules_and_print(args.input, config)
            proceed = summarize_risks_and_confirm(config)
            if not proceed:
                print("Operation cancelled by user.")
                sys.exit(1)
        else:
            proceed = summarize_risks_and_confirm(config)
            if not proceed:
                print("Operation cancelled by user.")
                sys.exit(1)
        patterns = extract_rule_patterns(config)

    # I/O 처리: 입력 단일 파일/디렉터리 분기
    os.makedirs(args.output, exist_ok=True)
    log_path = os.path.join(args.output, 'obfuscator.log')
    with open(log_path, 'w', encoding='utf-8') as log_file:
        if os.path.isfile(args.input):
            with open(args.input, 'r', encoding='utf-8') as infile:
                code = infile.read()
            transformed = apply_obfuscation(code, patterns)
            with open(args.output, 'w', encoding='utf-8') as outfile:
                outfile.write(transformed)
            log_file.write(f"{args.output}\n")
        elif os.path.isdir(args.input):
            swift_files = list(iter_swift_files(args.input))
            total = len(swift_files)
            for idx, (src_file, rel_path) in enumerate(swift_files):
                dst_file = os.path.join(args.output, rel_path)
                os.makedirs(os.path.dirname(dst_file), exist_ok=True)
                with open(src_file, 'r', encoding='utf-8') as infile:
                    code = infile.read()
                transformed = apply_obfuscation(code, patterns)
                with open(dst_file, 'w', encoding='utf-8') as outfile:
                    outfile.write(transformed)
                log_file.write(f"{rel_path}\n")
                if patterns:
                    matched = []
                    for key, arr in patterns.items():
                        for p in arr:
                            if _match_wildcard(rel_path, p):
                                matched.append(f"{key}:{p}")
                    if matched:
                        log_file.write("[match] " + ", ".join(matched) + "\n")
                bar = ('#' * ((idx + 1) * 20 // total)).ljust(20, ' ')
                percent = (idx + 1) * 100 // total if total > 0 else 100
                print(f"\r[{bar}] {percent}%", end='', flush=True)
            print()

            # 프로젝트 관련 파일 텍스트화 저장
            sidecars = collect_project_sidecar_files(args.input, (
                '.plist', '.xcodeproj', '.xcworkspace', '.swiftpm',
                '.pbxproj', '.xcconfig', '.entitlements', '.modulemap',
                '.xcsettings', '.xcuserstate', '.xcworkspacedata',
                '.xcscheme', '.xctestplan', '.xcassets', '.storyboard',
                '.xcdatamodeld', '.xcappdata', '.xcfilelist',
                '.xcplayground', '.xcplaygroundpage', '.xctemplate',
                '.xcsnippet', '.xcstickers', '.xcstickersicon',
                '.xcuserdatad'
            ))
            for src_path in sidecars:
                rel_path = os.path.relpath(src_path, args.input)
                flat = flatten_relpath_for_sidecar(rel_path)
                dst_path = os.path.join(args.output, 'project_info', flat)
                os.makedirs(os.path.dirname(dst_path), exist_ok=True)
                if src_path.endswith('.plist'):
                    text = read_plist_as_text(src_path)
                    with open(dst_path, 'w', encoding='utf-8') as f:
                        f.write(text)
                else:
                    content, mode = read_text_fallback(src_path)
                    with open(dst_path, mode) as f:
                        f.write(content)
                log_file.write(f"{os.path.join('project_info', flat)}\n")
        else:
            print("Error: Input path is neither file nor directory")


def print_banner():
    banner = r"""
__     ____            _              __ _
\ \   / ___|_       _ (_)_ __   __ _ / _| |_
 \ \  \___  \ \ /\ / /| | '_ \ / _` | |_| __|
 / /   ___) |\ V  V / | | | | | (_) |  _| |_
/_/___|____/  \_/\_/  |_|_| |_|\__, |_|  \__|
 |_____|                       |___/
    """
    print(banner)


def _check_rules_and_print(project_root: str, config):
    """프로젝트의 .swift 파일을 스캔해 식별자 존재 여부를 요약 출력"""
    from pathlib import Path
    from swingft_cli.config import extract_rule_patterns

    patterns = extract_rule_patterns(config)
    idents = set()
    for key in ("obfuscation_include", "obfuscation_exclude", "encryption_include", "encryption_exclude"):
        for p in patterns.get(key, []):
            # 와일드카드 패턴은 원문 그대로 보고, 리터럴로 보이는 항목만 식별자 후보에 추가
            if "*" not in p and "?" not in p:
                idents.add(p)

    found = {i: [] for i in idents}
    root = Path(project_root)
    for p in root.rglob("*.swift"):
        try:
            text = p.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            continue
        for ident in idents:
            if ident in text:
                if len(found[ident]) < 5:
                    found[ident].append(str(p))

    print("[규칙 검사] JSON에 지정된 식별자 존재 여부:")
    for ident in sorted(idents):
        paths = found.get(ident, [])
        if paths:
            print(f"  - {ident}: 발견됨 (예: {paths[0]}{' 외' if len(paths)>1 else ''})")
        else:
            print(f"  - {ident}: 미발견")

def _check_exception_conflicts(config_path: str) -> None:
    """Check for conflicts between config and exception_list.json"""
    from pathlib import Path
    
    # Auto-detect exception list path (same logic as cli.py)
    exc_candidates = [
        os.path.join(os.getcwd(), "exception_list.json"),
        os.path.join(os.getcwd(), "ID_Obfuscation", "output", "exception_list.json"),
        os.path.join(os.getcwd(), "identifier_obfuscation", "exception_list.json"),
    ]
    exc_file = next((Path(p) for p in exc_candidates if Path(p).exists()), None)
    
    if not exc_file:
        print("[preflight] exception_list.json not found - skipping conflict check")
        return
    
    try:
        # Load config
        with open(config_path, 'r', encoding='utf-8') as f:
            config = json.load(f)
        
        # Load exception list
        with open(exc_file, 'r', encoding='utf-8') as f:
            ex_list = json.load(f)
    except Exception as e:
        print(f"[preflight] warning: failed to load files for conflict check: {e}")
        return
    
    # Extract identifiers from exception list
    ex_names = set()
    if isinstance(ex_list, list):
        for item in ex_list:
            if isinstance(item, dict):
                name = str(item.get("A_name", "")).strip()
                if name:
                    ex_names.add(name)
    
    if not ex_names:
        print("[preflight] exception_list.json contains no identifiers - skipping conflict check")
        return
    
    # Check for '*' patterns and warn user
    wildcard_patterns = []
    for section in ("include", "exclude"):
        for category in ("obfuscation", "encryption"):
            items = config.get(section, {}).get(category, [])
            if isinstance(items, list):
                for item in items:
                    if isinstance(item, str) and item.strip() == "*":
                        wildcard_patterns.append(f"{section}.{category}")
    
    if wildcard_patterns:
        print(f"\n[preflight] ⚠️  '*' 단독 패턴 사용 감지:")
        for pattern in wildcard_patterns:
            print(f"  - {pattern}: 모든 식별자에 적용됩니다")
        print("  - 이는 의도된 설정인지 확인이 필요합니다.")
        
        try:
            ans = input("계속 진행하시겠습니까? [y/N]: ").strip().lower()
            if ans not in ("y", "yes"):
                print("사용자에 의해 취소되었습니다.")
                sys.exit(1)
        except (EOFError, KeyboardInterrupt):
            print("\n사용자에 의해 취소되었습니다.")
            sys.exit(1)
    
    # Extract only include identifiers (excluding exclude - they're fine to overlap)
    config_names = set()
    for category in ("obfuscation", "encryption"):
        items = config.get("include", {}).get(category, [])
        if isinstance(items, list):
            for item in items:
                if isinstance(item, str) and item.strip():
                    item = item.strip()
                    if "*" not in item and "?" not in item:
                        # Literal identifier
                        config_names.add(item)
                    else:
                        # Wildcard pattern - expand against exception list
                        import fnmatch
                        for ex_name in ex_names:
                            if fnmatch.fnmatchcase(ex_name, item):
                                config_names.add(ex_name)
    
    # Check for conflicts
    conflicts = config_names & ex_names
    if conflicts:
        print(f"\n[preflight] ⚠️  Include 대상과 exception_list.json 간 식별자 충돌 발견:")
        sample = sorted(list(conflicts))[:10]
        print(f"  - 충돌 식별자: {len(conflicts)}개 (예: {', '.join(sample)})")
        print(f"  - exception_list.json 위치: {exc_file}")
        print("  - 이 식별자들은 난독화 대상이지만 exception_list에도 있어 혼동 가능합니다.")
        
        print("\n  이 충돌을 무시하고 계속 진행하시겠습니까?")
        try:
            ans = input("Include 충돌 무시하고 계속 [y/N]: ").strip().lower()
            if ans not in ("y", "yes"):
                print("사용자에 의해 취소되었습니다.")
                sys.exit(1)
        except (EOFError, KeyboardInterrupt):
            print("\n사용자에 의해 취소되었습니다.")
            sys.exit(1)
    else:
        print("[preflight] Include 대상과 exception_list.json 충돌 없음 ✅")
    
    # Check exclude identifiers not in exception_list
    _check_exclude_sensitive_identifiers(config, ex_names)


def _check_exclude_sensitive_identifiers(config, ex_names):
    """Check exclude identifiers not in exception_list and get LLM sensitivity analysis"""
    # First, scan project identifiers
    from swingft_cli.core.config.rules import scan_swift_identifiers
    project_root = config.get("project", {}).get("input")
    if not project_root or not os.path.isdir(project_root):
        print("[preflight] project.input 경로가 없어 프로젝트 식별자 스캔을 건너뜁니다.")
        return
    
    project_identifiers = set(scan_swift_identifiers(project_root))
    if not project_identifiers:
        print("[preflight] 프로젝트에서 식별자를 찾지 못했습니다.")
        return
    
    # Extract exclude identifiers that exist in project but not in exception_list
    exclude_candidates = set()
    for category in ("obfuscation", "encryption"):
        items = config.get("exclude", {}).get(category, [])
        if isinstance(items, list):
            for item in items:
                if isinstance(item, str) and item.strip():
                    item = item.strip()
                    if "*" not in item and "?" not in item:
                        # Literal identifier that exists in project but not in exception_list
                        if item in project_identifiers and item not in ex_names:
                            exclude_candidates.add(item)
                    else:
                        # Wildcard pattern - expand against project identifiers
                        import fnmatch
                        for proj_id in project_identifiers:
                            if fnmatch.fnmatchcase(proj_id, item) and proj_id not in ex_names:
                                exclude_candidates.add(proj_id)
    
    if not exclude_candidates:
        print("[preflight] Exclude 대상 중 exception_list에 없는 식별자 없음 ✅")
        print(f"[debug] 프로젝트 식별자 수: {len(project_identifiers)}")
        print(f"[debug] exception_list 식별자 수: {len(ex_names)}")
        return
    
    print(f"\n[preflight] Exclude 대상 중 exception_list에 없는 식별자 {len(exclude_candidates)}개 발견")
    print("  - 임시 랜덤 민감도 분석을 수행합니다...")
    
    # Generate random sensitivity analysis (temporary)
    import random
    llm_result = {
        "results": []
    }
    
    for name in sorted(exclude_candidates):
        is_sensitive = random.choice([True, False])
        if is_sensitive:
            reasons = ["contains password", "API key identifier", "sensitive data", "authentication token"]
            reason = random.choice(reasons)
        else:
            reasons = ["generic identifier", "UI component", "utility function", "data structure"]
            reason = random.choice(reasons)
        
        llm_result["results"].append({
            "name": name,
            "sensitive": is_sensitive,
            "reason": reason
        })
    
    # Process LLM results
    sensitive_identifiers = []
    non_sensitive_identifiers = []
    
    if "results" in llm_result:
        for result in llm_result["results"]:
            if result.get("sensitive", False):
                sensitive_identifiers.append(result)
            else:
                non_sensitive_identifiers.append(result)
    
    if sensitive_identifiers:
        print(f"\n[preflight] ⚠️  민감한 식별자 {len(sensitive_identifiers)}개 발견:")
        for item in sensitive_identifiers[:5]:  # Show first 5
            print(f"  - {item['name']}: {item.get('reason', '민감한 식별자로 판단됨')}")
        if len(sensitive_identifiers) > 5:
            print(f"  - ... 외 {len(sensitive_identifiers) - 5}개")
        
        print("\n  이 식별자들을 난독화에서 제외하시겠습니까?")
        try:
            ans = input("민감한 식별자 제외 진행 [y/N]: ").strip().lower()
            if ans not in ("y", "yes"):
                print("사용자에 의해 취소되었습니다.")
                sys.exit(1)
        except (EOFError, KeyboardInterrupt):
            print("\n사용자에 의해 취소되었습니다.")
            sys.exit(1)
    
    if non_sensitive_identifiers:
        print(f"\n[preflight] 일반 식별자 {len(non_sensitive_identifiers)}개:")
        for item in non_sensitive_identifiers[:3]:  # Show first 3
            print(f"  - {item['name']}: {item.get('reason', '일반 식별자로 판단됨')}")
        if len(non_sensitive_identifiers) > 3:
            print(f"  - ... 외 {len(non_sensitive_identifiers) - 3}개")
    
    print("[preflight] Exclude 대상 민감도 분석 완료 ✅")


def _match_wildcard(text: str, pattern: str) -> bool:
    if pattern == "*":
        return True
    parts = pattern.split('*')
    if not parts:
        return text == pattern
    pos = 0
    for part in parts:
        if not part:
            continue
        idx = text.find(part, pos)
        if idx < 0:
            return False
        pos = idx + len(part)
    return True