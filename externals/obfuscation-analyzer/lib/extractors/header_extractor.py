#!/usr/bin/env python3
"""
Swift 소스코드 난독화를 위한 헤더 식별자 추출기 (병렬 처리 버전)

DerivedData와 프로젝트 내의 모든 헤더 파일에서 난독화 제외 대상 식별자를 추출합니다.
멀티프로세싱을 사용하여 빠른 속도로 처리합니다.
"""

import re
import argparse
import glob
from pathlib import Path
from typing import Set, Dict, List, Tuple
from collections import defaultdict
from enum import Enum, auto
from multiprocessing import Pool, cpu_count
import time


class ParseState(Enum):
    NORMAL = auto()
    SINGLE_LINE_COMMENT = auto()
    MULTI_LINE_COMMENT = auto()
    STRING = auto()
    STRING_ESCAPE = auto()
    PREPROCESSOR = auto()


class ObjectiveCCommentRemover:
    """Objective-C 주석 제거"""

    def remove_comments(self, source: str) -> str:
        result = []
        state = ParseState.NORMAL
        i = 0
        length = len(source)

        while i < length:
            char = source[i]

            if state == ParseState.NORMAL:
                if char == '/' and i + 1 < length:
                    if source[i + 1] == '/':
                        state = ParseState.SINGLE_LINE_COMMENT
                        i += 1
                    elif source[i + 1] == '*':
                        state = ParseState.MULTI_LINE_COMMENT
                        i += 1
                    else:
                        result.append(char)
                elif char == '"' or (char == '@' and i + 1 < length and source[i + 1] == '"'):
                    result.append(char)
                    if char == '@':
                        result.append('"')
                        i += 1
                    state = ParseState.STRING
                elif char == '#' and (i == 0 or source[i - 1] == '\n'):
                    result.append(char)
                    state = ParseState.PREPROCESSOR
                else:
                    result.append(char)

            elif state == ParseState.STRING:
                result.append(char)
                if char == '\\':
                    state = ParseState.STRING_ESCAPE
                elif char == '"':
                    state = ParseState.NORMAL

            elif state == ParseState.STRING_ESCAPE:
                result.append(char)
                state = ParseState.STRING

            elif state == ParseState.SINGLE_LINE_COMMENT:
                if char == '\n':
                    result.append(char)
                    state = ParseState.NORMAL

            elif state == ParseState.MULTI_LINE_COMMENT:
                if char == '*' and i + 1 < length and source[i + 1] == '/':
                    i += 1
                    state = ParseState.NORMAL

            elif state == ParseState.PREPROCESSOR:
                result.append(char)
                if char == '\n':
                    if len(result) >= 2 and result[-2] == '\\':
                        pass
                    else:
                        state = ParseState.NORMAL

            i += 1

        return "".join(result)


class ObjCHeaderParser:
    """Objective-C 헤더 파서 - 모든 공개 식별자 추출"""

    PATTERNS = {
        'interface': re.compile(r'@interface\s+(\w+)\s*[:(]', re.MULTILINE),
        'protocol': re.compile(r'@protocol\s+(\w+)\b', re.MULTILINE),

        'struct_typedef': re.compile(r'typedef\s+struct\s+\w*\s*\{[^}]*\}\s*(\w+)\s*;',
                                     re.MULTILINE | re.DOTALL),
        'struct_plain': re.compile(r'struct\s+(\w+)\s*\{', re.MULTILINE),

        'enum_ns': re.compile(r'(?:NS_ENUM|NS_OPTIONS|NS_CLOSED_ENUM|NS_ERROR_ENUM)\s*\(\s*\w+\s*,\s*(\w+)\s*\)',
                              re.MULTILINE),
        'enum_typedef': re.compile(r'typedef\s+enum\s+\w*\s*(?::\s*\w+)?\s*\{[^}]*\}\s*(\w+)\s*;',
                                   re.MULTILINE | re.DOTALL),
        'enum_forward_decl': re.compile(r'enum\s+(\w+)\s*:\s*\w+\s*;', re.MULTILINE),
        'swift_enum': re.compile(r'typedef\s+SWIFT_ENUM\s*\([^,]+,\s*(\w+)\s*,', re.MULTILINE),

        'typedef_funcptr': re.compile(r'typedef\s+.+\(\s*\*\s*(\w+)\s*\)\s*\(.*\)\s*;', re.MULTILINE),
        'typedef_block': re.compile(r'typedef\s+.+\(\s*\^\s*(\w+)\s*\)\s*\(.*\)\s*;', re.MULTILINE),
        'typedef': re.compile(r'typedef\s+(?!enum|struct|union).*?\s+(\w+)\s*;',
                              re.MULTILINE | re.DOTALL),

        'function': re.compile(r'^(?:extern\s+)?(?:static\s+)?(?:inline\s+)?[A-Z]\w*\s+\*?\s*(\w+)\s*\(',
                               re.MULTILINE),
        'export_function': re.compile(
            r'^(?:FOUNDATION_EXPORT|NS_SWIFT_NAME|UIKIT_EXTERN|extern)\s+.*?\*?\s*([a-zA-Z_]\w+)\s*\(',
            re.MULTILINE),

        'extern_const': re.compile(
            r'(?:FOUNDATION_EXPORT|UIKIT_EXTERN|extern)\s+(?:const\s+)?[\w\s\*]+?(?:const\s+)?(\w+)\s*;',
            re.MULTILINE),
        'extern_const_array': re.compile(
            r'(?:FOUNDATION_EXPORT|UIKIT_EXTERN|extern)\s+(?:const\s+)?[\w\s\*]+\s+(\w+)\s*\[\s*\]',
            re.MULTILINE),

        'macro_k_constant': re.compile(r'\b(k[A-Z]\w+)\b', re.MULTILINE),
    }

    @classmethod
    def parse(cls, file_path: Path) -> Set[str]:
        """헤더 파일에서 모든 식별자를 추출하여 Set으로 반환"""
        all_identifiers = set()

        try:
            content = file_path.read_text(encoding='utf-8', errors='ignore')

            remover = ObjectiveCCommentRemover()
            clean_content = remover.remove_comments(content)

            # 클래스와 프로토콜
            all_identifiers.update(cls.PATTERNS['interface'].findall(clean_content))
            all_identifiers.update(cls.PATTERNS['protocol'].findall(clean_content))

            # 구조체
            all_identifiers.update(cls.PATTERNS['struct_typedef'].findall(clean_content))
            all_identifiers.update(cls.PATTERNS['struct_plain'].findall(clean_content))

            # 열거형
            all_identifiers.update(cls.PATTERNS['enum_ns'].findall(clean_content))
            all_identifiers.update(cls.PATTERNS['enum_typedef'].findall(clean_content))
            all_identifiers.update(cls.PATTERNS['enum_forward_decl'].findall(clean_content))
            all_identifiers.update(cls.PATTERNS['swift_enum'].findall(clean_content))

            # Typedef
            all_identifiers.update(cls.PATTERNS['typedef'].findall(clean_content))
            all_identifiers.update(cls.PATTERNS['typedef_funcptr'].findall(clean_content))
            all_identifiers.update(cls.PATTERNS['typedef_block'].findall(clean_content))

            # 함수
            all_identifiers.update(cls.PATTERNS['function'].findall(clean_content))
            all_identifiers.update(cls.PATTERNS['export_function'].findall(clean_content))

            # 상수
            all_identifiers.update(cls.PATTERNS['extern_const'].findall(clean_content))
            all_identifiers.update(cls.PATTERNS['extern_const_array'].findall(clean_content))
            all_identifiers.update(cls.PATTERNS['macro_k_constant'].findall(clean_content))

            # 매크로
            all_identifiers.update(cls._extract_macros(content))

            # 복잡한 패턴들
            all_identifiers.update(cls._extract_enum_cases(clean_content))
            all_identifiers.update(cls._extract_methods(clean_content))
            all_identifiers.update(cls._extract_properties(clean_content))

            # 카테고리 제외
            categories = cls._extract_categories(clean_content)
            all_identifiers -= categories

            # 필터링
            all_identifiers = cls._filter_identifiers(all_identifiers)

        except Exception as e:
            pass

        return all_identifiers

    @classmethod
    def _extract_macros(cls, content: str) -> Set[str]:
        """#define 매크로 추출"""
        macros = set()

        for line in content.split('\n'):
            line = line.strip()

            if line.startswith('//') or line.startswith('/*'):
                continue

            if line.startswith('#ifndef') or line.startswith('#define'):
                match = re.match(r'^#(?:ifndef|define)\s+([A-Za-z_]\w*)(?:\s|$|\()', line)
                if match:
                    macro_name = match.group(1)
                    if len(macro_name) > 1:
                        macros.add(macro_name)

        return macros

    @classmethod
    def _extract_categories(cls, content: str) -> Set[str]:
        """카테고리 이름 추출 (제외용)"""
        pattern = re.compile(r'@interface\s+\w+\s*\((\w+)\)', re.MULTILINE)
        return set(pattern.findall(content))

    @classmethod
    def _extract_enum_cases(cls, content: str) -> Set[str]:
        """enum case 값들 추출"""
        cases = set()

        enum_blocks = re.findall(
            r'(?:typedef\s+)?enum\s+\w*\s*(?::\s*\w+)?\s*\{([^}]+)\}',
            content,
            re.MULTILINE | re.DOTALL
        )

        ns_enum_blocks = re.findall(
            r'(?:NS_ENUM|NS_OPTIONS|NS_CLOSED_ENUM|NS_ERROR_ENUM)\s*\([^)]+\)\s*\{([^}]+)\}',
            content,
            re.MULTILINE | re.DOTALL
        )

        swift_enum_blocks = re.findall(
            r'typedef\s+SWIFT_ENUM[^{]*\{([^}]+)\}',
            content,
            re.MULTILINE | re.DOTALL
        )

        all_blocks = enum_blocks + ns_enum_blocks + swift_enum_blocks

        for block in all_blocks:
            for line in block.split('\n'):
                line = line.strip()
                if not line or line.startswith('//') or line.startswith('/*'):
                    continue

                match = re.match(r'([A-Za-z_]\w*)\s*(?:=|,|$)', line)
                if match:
                    case_name = match.group(1)
                    if len(case_name) > 1:
                        cases.add(case_name)

        return cases

    @classmethod
    def _extract_methods(cls, content: str) -> Set[str]:
        """메서드 이름 추출"""
        methods = set()

        method_pattern = re.compile(
            r'^[\-+]\s*\([^)]+\)\s*([a-zA-Z_]\w*)(?:\s|:|;)',
            re.MULTILINE
        )

        for match in method_pattern.finditer(content):
            method_name = match.group(1)
            if method_name and len(method_name) > 1:
                methods.add(method_name)

        method_with_params = re.compile(
            r'^[\-+]\s*\([^)]+\)\s*([a-zA-Z_]\w*):',
            re.MULTILINE
        )

        for match in method_with_params.finditer(content):
            method_name = match.group(1)
            if method_name and len(method_name) > 1:
                methods.add(method_name)

        return methods

    @classmethod
    def _extract_properties(cls, content: str) -> Set[str]:
        """프로퍼티 이름 추출"""
        properties = set()

        property_pattern = re.compile(
            r'@property\s*\([^)]*\)\s*[\w\s\*<>]+\s+([a-zA-Z_]\w*)\s*;',
            re.MULTILINE
        )

        for match in property_pattern.finditer(content):
            prop_name = match.group(1)
            if prop_name and len(prop_name) > 1:
                properties.add(prop_name)

        return properties

    @classmethod
    def _filter_identifiers(cls, identifiers: Set[str]) -> Set[str]:
        """유효하지 않은 식별자 필터링"""
        filtered = set()

        reserved_keywords = {
            'id', 'in', 'out', 'inout', 'bycopy', 'byref', 'oneway',
            'self', 'super', 'nil', 'Nil', 'YES', 'NO',
            'Class', 'SEL', 'IMP', 'BOOL',
            'void', 'int', 'float', 'double', 'char', 'short', 'long',
            'unsigned', 'signed', 'const', 'static', 'extern', 'inline',
            'typedef', 'struct', 'union', 'enum',
            'if', 'else', 'switch', 'case', 'default',
            'for', 'while', 'do', 'break', 'continue', 'return',
        }

        for identifier in identifiers:
            if not identifier or len(identifier) <= 1:
                continue

            if identifier in reserved_keywords:
                continue

            if not re.match(r'^[A-Za-z_][A-Za-z0-9_]*$', identifier):
                continue

            if identifier.startswith('__'):
                continue

            filtered.add(identifier)

        return filtered


# 병렬 처리를 위한 전역 함수
def process_header_file(args: Tuple[Path, Path]) -> Tuple[str, Set[str], bool]:
    """
    단일 헤더 파일 처리 (멀티프로세싱용)

    Returns:
        (relative_path, identifiers, success)
    """
    header_file, project_path = args

    try:
        identifiers = ObjCHeaderParser.parse(header_file)

        # 상대 경로 생성
        try:
            relative_path = str(header_file.relative_to(project_path))
        except ValueError:
            relative_path = f"[DerivedData] {header_file.name}"

        return (relative_path, identifiers, True)

    except Exception as e:
        return (header_file.name, set(), False)


class HeaderScanner:
    """헤더 파일 스캐너 (병렬 처리 지원)"""

    def __init__(self, project_path: Path, target_name: str = None, num_workers: int = None):
        """
        Args:
            project_path: 프로젝트 루트 경로
            target_name: 실제 프로젝트/타겟 이름 (DerivedData 검색용)
            num_workers: 병렬 처리 워커 수 (None이면 CPU 코어 수 사용)
        """
        self.project_path = project_path.resolve()
        self.target_name = target_name
        self.num_workers = num_workers or cpu_count()
        self.all_identifiers: Set[str] = set()
        self.stats = {
            'project_headers': 0,
            'derived_data_headers': 0,
            'total_headers': 0,
            'success': 0,
            'failed': 0,
            'processing_time': 0.0
        }
        self.exclude_dirs = {'.git', '.build', 'build', 'Pods', 'Carthage',
                             'DerivedData', 'node_modules', '.svn', '.hg'}

    def find_project_headers(self) -> List[Path]:
        """프로젝트 디렉토리 내의 모든 .h 파일 찾기"""
        print(f"📂 프로젝트 내부 헤더 검색 중: {self.project_path}")

        headers = []

        for header_file in self.project_path.rglob("*.h"):
            # 제외 디렉토리 체크
            if any(excluded in header_file.parts for excluded in self.exclude_dirs):
                continue

            headers.append(header_file)

        print(f"   ✅ {len(headers)}개의 프로젝트 헤더 발견")
        return headers

    def find_derived_data_headers(self) -> List[Path]:
        """DerivedData에서 헤더 파일 찾기 (가장 최신 것만)"""
        if not self.target_name:
            print("   ⚠️  타겟 이름이 지정되지 않아 DerivedData 스캔을 건너뜁니다.")
            return []

        derived_data_base = Path.home() / "Library" / "Developer" / "Xcode" / "DerivedData"

        if not derived_data_base.exists():
            print(f"   ⚠️  DerivedData 디렉토리를 찾을 수 없습니다: {derived_data_base}")
            return []

        print(f"\n📦 DerivedData 헤더 검색 중: {self.target_name}")

        # 타겟 이름으로 시작하는 디렉토리 찾기
        matching_dirs = []
        for item in derived_data_base.iterdir():
            if item.is_dir() and item.name.startswith(f"{self.target_name}-"):
                matching_dirs.append(item)

        if not matching_dirs:
            print(f"   ⚠️  '{self.target_name}'에 해당하는 DerivedData 디렉토리를 찾을 수 없습니다.")
            print(f"   💡 ~/Library/Developer/Xcode/DerivedData/{self.target_name}-* 형식을 찾습니다.")
            return []

        # 여러 개 발견 시 가장 최신 것만 사용
        if len(matching_dirs) > 1:
            print(f"   → {len(matching_dirs)}개의 매칭 디렉토리 발견 (가장 최신 것만 사용)")
            # 수정 시간 기준으로 정렬하여 가장 최신 것 선택
            matching_dirs.sort(key=lambda x: x.stat().st_mtime, reverse=True)
            selected_dir = matching_dirs[0]
            print(f"   ✅ 선택됨: {selected_dir.name}")
            matching_dirs = [selected_dir]
        else:
            print(f"   → 1개의 매칭 디렉토리 발견")

        headers = []
        for derived_dir in matching_dirs:
            print(f"   → 스캔: {derived_dir.name}")

            # DerivedData 내의 모든 .h 파일 찾기
            for header_file in derived_dir.rglob("*.h"):
                headers.append(header_file)

        print(f"   ✅ {len(headers)}개의 DerivedData 헤더 발견")
        return headers

    def scan_all(self) -> Set[str]:
        """모든 헤더 파일 스캔 (병렬 처리)"""
        print("🚀 Swift 난독화용 헤더 식별자 추출기 (병렬 처리)")
        print("=" * 60)
        print()

        # 1. 프로젝트 내부 헤더
        project_headers = self.find_project_headers()
        self.stats['project_headers'] = len(project_headers)

        # 2. DerivedData 헤더
        derived_headers = self.find_derived_data_headers()
        self.stats['derived_data_headers'] = len(derived_headers)

        # 전체 헤더 목록
        all_headers = project_headers + derived_headers
        self.stats['total_headers'] = len(all_headers)

        if not all_headers:
            print("❌ 헤더 파일을 찾을 수 없습니다.")
            return set()

        print(f"\n✓ 총 {len(all_headers)}개의 헤더 파일 발견")
        print(f"  - 프로젝트 내부: {len(project_headers)}개")
        print(f"  - DerivedData: {len(derived_headers)}개")
        print(f"\n⚡ {self.num_workers}개의 워커로 병렬 처리 시작...")
        print("-" * 60)

        # 시작 시간 기록
        start_time = time.time()

        # 병렬 처리
        args_list = [(header, self.project_path) for header in all_headers]

        with Pool(processes=self.num_workers) as pool:
            results = pool.map(process_header_file, args_list)

        # 결과 수집
        for relative_path, identifiers, success in results:
            if success and identifiers:
                self.all_identifiers.update(identifiers)
                self.stats['success'] += 1
                print(f"✓ {relative_path}: {len(identifiers)}개")
            else:
                self.stats['failed'] += 1
                if not success:
                    print(f"✗ {relative_path}: 오류")

        # 처리 시간 기록
        end_time = time.time()
        self.stats['processing_time'] = end_time - start_time

        return self.all_identifiers

    def print_summary(self):
        """추출 결과 요약 출력"""
        print("\n" + "=" * 60)
        print("📊 추출 결과 요약 (난독화 제외 대상)")
        print("=" * 60)
        print(f"프로젝트 헤더:       {self.stats['project_headers']:>6}개")
        print(f"DerivedData 헤더:    {self.stats['derived_data_headers']:>6}개")
        print(f"총 헤더 파일:        {self.stats['total_headers']:>6}개")
        print(f"성공:               {self.stats['success']:>6}개")
        print(f"실패:               {self.stats['failed']:>6}개")
        print(f"처리 시간:          {self.stats['processing_time']:>6.2f}초")
        print(f"워커 수:            {self.num_workers:>6}개")
        print(f"\n고유 식별자 총합:    {len(self.all_identifiers):>6}개")
        print("=" * 60)

    def save_to_txt(self, output_path: Path):
        """식별자를 .txt 파일로 저장 (한 줄에 하나씩)"""
        output_path.parent.mkdir(parents=True, exist_ok=True)

        with open(output_path, 'w', encoding='utf-8') as f:
            for identifier in sorted(self.all_identifiers):
                f.write(identifier + '\n')

        print(f"\n💾 저장 완료: {output_path}")
        print(f"   총 {len(self.all_identifiers)}개의 식별자가 저장되었습니다.")


def main():
    parser = argparse.ArgumentParser(
        description="Swift 난독화를 위한 헤더 식별자 추출기 (병렬 처리)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
사용 예시:
  python header_extractor.py -i /path/to/project -o identifiers.txt -t MyApp
  python header_extractor.py -i ~/Projects/MyProject -o ./output/exclude.txt -t MyProject
  python header_extractor.py -i ~/Projects/MyProject -o ./id.txt -t MyProject --workers 8
        """
    )

    parser.add_argument('-i', '--input', type=Path, required=True,
                        help='프로젝트 루트 경로')
    parser.add_argument('-o', '--output', type=Path, required=True,
                        help='출력 .txt 파일 경로 (식별자가 한 줄에 하나씩 저장됨)')
    parser.add_argument('-t', '--target', type=str,
                        help='타겟 프로젝트 이름 (DerivedData 검색용, 예: MyApp)')
    parser.add_argument('-w', '--workers', type=int, default=None,
                        help=f'병렬 처리 워커 수 (기본값: CPU 코어 수 = {cpu_count()})')

    args = parser.parse_args()

    # 입력 경로 검증
    if not args.input.exists():
        print(f"❌ 경로를 찾을 수 없습니다: {args.input}")
        return 1

    if not args.input.is_dir():
        print(f"❌ 디렉토리가 아닙니다: {args.input}")
        return 1

    # 스캐너 실행
    scanner = HeaderScanner(args.input, args.target, args.workers)
    identifiers = scanner.scan_all()
    scanner.print_summary()

    # 결과 저장
    if identifiers:
        scanner.save_to_txt(args.output)
        print("\n✅ 완료!")
        print("💡 이 식별자들은 공개 API이므로 난독화에서 제외해야 합니다.")
    else:
        print("\n⚠️  추출된 식별자가 없습니다.")
        return 1

    return 0


if __name__ == "__main__":
    exit(main())