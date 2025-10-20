#!/usr/bin/env python3
"""
iOS/macOS 리소스 파일에서 식별자 추출기 (최종 완성 버전 v3)
XIB, Storyboard, Plist, CoreData, Strings, Entitlements, Assets에서 난독화 제외 대상 추출
"""

import re
import json
import argparse
import plistlib
import subprocess
from pathlib import Path
from typing import Set, Dict, List, Optional
from collections import defaultdict
import xml.etree.ElementTree as ET


class AssetsParser:
    """Assets.xcassets에서 이미지/색상 이름 추출 (개선됨)"""

    @classmethod
    def parse(cls, assets_path: Path) -> Dict[str, Set[str]]:
        result = defaultdict(set)

        if not assets_path.is_dir():
            return dict(result)

        try:
            # .imageset, .colorset, .dataset 등 찾기
            for item in assets_path.rglob('*'):
                if item.is_dir():
                    # 이미지 세트
                    if item.suffix == '.imageset':
                        name = item.stem  # logo-evolution-splash.imageset → logo-evolution-splash
                        if cls._is_valid_asset_name(name):
                            result['images'].add(name)

                    # 색상 세트
                    elif item.suffix == '.colorset':
                        name = item.stem  # HeaderLabelColor.colorset → HeaderLabelColor
                        if cls._is_valid_asset_name(name):
                            result['colors'].add(name)

                    # 데이터 세트
                    elif item.suffix == '.dataset':
                        name = item.stem
                        if cls._is_valid_asset_name(name):
                            result['data_assets'].add(name)

                    # 심볼 (SF Symbols 커스텀)
                    elif item.suffix == '.symbolset':
                        name = item.stem
                        if cls._is_valid_asset_name(name):
                            result['symbols'].add(name)

                # ✅ Contents.json 파싱 추가
                elif item.name == 'Contents.json':
                    try:
                        with open(item, 'r', encoding='utf-8') as f:
                            data = json.load(f)

                            # 이미지 파일명 추출
                            if 'images' in data:
                                for img in data.get('images', []):
                                    filename = img.get('filename')
                                    if filename:
                                        # 확장자 제거하고 에셋 이름으로 사용
                                        name = Path(filename).stem
                                        if cls._is_valid_asset_name(name):
                                            result['asset_files'].add(name)

                            # 컬러 정보 추출
                            if 'colors' in data:
                                for color in data.get('colors', []):
                                    if 'color' in color:
                                        # 필요시 컬러 관련 메타데이터 추출
                                        pass
                    except:
                        pass

        except Exception:
            pass

        return dict(result)

    @staticmethod
    def _is_valid_asset_name(name: str) -> bool:
        """유효한 Asset 이름인지 검사"""
        if not name or len(name) < 1:
            return False

        # Assets은 거의 모든 문자 허용하지만, 시스템 예약어 제외
        system_reserved = {
            'Contents', 'Info', 'Metadata'
        }

        if name in system_reserved:
            return False

        return True


class XIBStoryboardParser:
    """XIB/Storyboard 파일에서 식별자 추출 (개선됨)"""

    # 제외할 시스템 클래스
    SYSTEM_CLASSES = {
        'UIResponder', 'UIViewController', 'UIView', 'UITableView',
        'UICollectionView', 'UIButton', 'UILabel', 'UIImageView',
        'UITableViewCell', 'UICollectionViewCell', 'UIScrollView',
        'UIStackView', 'UINavigationController', 'UITabBarController',
        'NSObject', 'NSManagedObject', 'UITextField', 'UITextView',
        'UISwitch', 'UISlider', 'UISegmentedControl', 'UIDatePicker',
        'UIPickerView', 'UIActivityIndicatorView', 'UIProgressView',
        'NSLayoutConstraint', 'UILayoutGuide'
    }

    @classmethod
    def parse(cls, file_path: Path) -> Dict[str, Set[str]]:
        result = defaultdict(set)

        try:
            tree = ET.parse(file_path)
            root = tree.getroot()

            # Custom Class 이름 추출
            for elem in root.iter():
                custom_class = elem.get('customClass')
                if custom_class and cls._is_valid_class(custom_class):
                    result['classes'].add(custom_class)

                custom_module = elem.get('customModule')
                if custom_module and cls._is_valid_identifier(custom_module):
                    result['modules'].add(custom_module)

            # IBOutlet/IBAction connections
            for connection in root.iter('connection'):
                kind = connection.get('kind')
                property_name = connection.get('property')

                if kind == 'outlet' and property_name:
                    if cls._is_valid_identifier(property_name):
                        result['outlets'].add(property_name)
                elif kind == 'action':
                    selector = connection.get('selector')
                    if selector and cls._is_valid_selector(selector):
                        result['actions'].add(selector)

            # Segue identifiers
            for segue in root.iter('segue'):
                identifier = segue.get('identifier')
                if identifier and cls._is_valid_identifier(identifier):
                    result['segue_identifiers'].add(identifier)

            # Reuse identifiers
            for elem in root.iter():
                reuse_id = elem.get('reuseIdentifier')
                if reuse_id and cls._is_valid_identifier(reuse_id):
                    result['reuse_identifiers'].add(reuse_id)

                storyboard_id = elem.get('storyboardIdentifier')
                if storyboard_id and cls._is_valid_identifier(storyboard_id):
                    result['storyboard_identifiers'].add(storyboard_id)

                restoration_id = elem.get('restorationIdentifier')
                if restoration_id and cls._is_valid_identifier(restoration_id):
                    result['restoration_identifiers'].add(restoration_id)

            # ✅ 이미지 이름 추출 추가
            for elem in root.iter('image'):
                # <image name="logo-evolution-splash"/> 형태
                image_name = elem.get('name')
                if image_name and cls._is_valid_identifier(image_name):
                    result['image_names'].add(image_name)

            # ✅ SF Symbols (systemName) 추출 추가
            for elem in root.iter():
                system_name = elem.get('systemName')
                if system_name:
                    # SF Symbol은 점(.)을 포함할 수 있음
                    if cls._is_valid_symbol_name(system_name):
                        result['system_symbols'].add(system_name)

            # ✅ 나머지 이미지 참조 (imageView 등)
            for elem in root.iter('imageView'):
                image = elem.get('image')
                if image and cls._is_valid_identifier(image):
                    result['image_names'].add(image)

            for elem in root.iter('button'):
                image = elem.get('image')
                if image and cls._is_valid_identifier(image):
                    result['image_names'].add(image)

            # User Defined Runtime Attributes (keyPath)
            for attr in root.iter('userDefinedRuntimeAttribute'):
                keypath = attr.get('keyPath')
                if keypath:
                    parts = keypath.split('.')
                    for part in parts:
                        if cls._is_valid_identifier(part):
                            result['runtime_attributes'].add(part)

            # ✅ Scene/View 레이어 이름 추출 (label 속성)
            for elem in root.iter():
                label = elem.get('label')
                if label and cls._is_scene_label(label):
                    result['scene_labels'].add(label)

        except Exception:
            pass

        return dict(result)

    @classmethod
    def _is_valid_class(cls, name: str) -> bool:
        """유효한 클래스명인지 검사"""
        if not name or len(name) <= 1:
            return False

        if name in cls.SYSTEM_CLASSES:
            return False

        # 대문자로 시작하는 영문자+숫자+언더스코어
        if not name[0].isupper():
            return False

        for char in name:
            if not (char.isalnum() or char == '_'):
                return False

        return True

    @classmethod
    def _is_valid_identifier(cls, name: str) -> bool:
        """유효한 일반 식별자인지 검사"""
        if not name or len(name) <= 1:
            return False

        # ✅ 하이픈(-) 허용 (Asset 이름에 사용됨)
        # 첫 글자: 영문자 또는 언더스코어
        if not (name[0].isalpha() or name[0] == '_'):
            return False

        # 나머지: 영문자, 숫자, 언더스코어, 하이픈
        for char in name:
            if not (char.isalnum() or char in ('_', '-')):
                return False

        return True

    @classmethod
    def _is_valid_symbol_name(cls, name: str) -> bool:
        """유효한 SF Symbol 이름인지 검사 (점 포함 가능)"""
        if not name or len(name) <= 1:
            return False

        # SF Symbol: arrow.backward, checkmark.circle.fill 등
        # 첫 글자: 영문자
        if not name[0].isalpha():
            return False

        # 허용: 영문자, 숫자, 점, 언더스코어, 하이픈
        for char in name:
            if not (char.isalnum() or char in ('.', '_', '-')):
                return False

        return True

    @classmethod
    def _is_scene_label(cls, label: str) -> bool:
        """Scene 레이블이 유효한지 검사"""
        if not label or len(label) < 2:
            return False

        # ✅ 숫자로 시작하는 레이블도 허용 (예: "1 Small Clouds")
        # 단, 순수 숫자만인 경우 제외
        if label.isdigit():
            return False

        # 너무 긴 문장 제외 (10단어 이상)
        if ' ' in label:
            words = label.split()
            if len(words) > 10:
                return False

        return True

    @classmethod
    def _is_valid_selector(cls, selector: str) -> bool:
        """유효한 Selector인지 검사"""
        if not selector or len(selector) <= 1:
            return False

        # 콜론 제거 후 검증
        parts = selector.replace(':', '').split()
        if not parts:
            return False

        # 각 파트가 유효한 식별자인지 확인
        for part in parts:
            if part and not cls._is_valid_identifier(part):
                return False

        return True


class PlistParser:
    """Plist 파일에서 식별자 추출 (🔥 키 목록 대폭 강화)"""

    # 룰베이스 팀 자료와 Apple 문서를 기반으로 키 목록 확장
    PRINCIPAL_CLASS_KEYS = {
        "NSPrincipalClass", "NSExtensionPrincipalClass", "UISceneDelegateClassName",
        "NSApplicationClass", "NSServices", "NSClass"
    }
    STRING_IDENTIFIER_KEYS = {
        "CFBundleIdentifier", "CFBundleName", "CFBundleDisplayName",
        "UIApplicationShortcutItemType", "WKWebsiteDataStoreIdentifier"
    }

    @classmethod
    def parse(cls, file_path: Path) -> Dict[str, Set[str]]:
        result = defaultdict(set)
        try:
            # [수정] xml.etree.ElementTree 대신 plistlib을 사용하여 바이너리 Plist도 지원
            with open(file_path, 'rb') as f:
                plist_data = plistlib.load(f)
            cls._recursive_parse(plist_data, result)
        except Exception:
            pass
        return dict(result)

    @classmethod
    def _recursive_parse(cls, data: any, result: defaultdict):
        if isinstance(data, dict):
            for key, value in data.items():
                if key in cls.PRINCIPAL_CLASS_KEYS and isinstance(value, str):
                    if cls._is_valid_class_name(value):
                        result['principal_classes'].add(value)
                elif key in cls.STRING_IDENTIFIER_KEYS and isinstance(value, str):
                    if cls._is_valid_bundle_id_style(value):
                        result['bundle_identifiers'].add(value)
                # [추가] NSUserActivityTypes 키 처리
                elif key == "NSUserActivityTypes" and isinstance(value, list):
                    for activity_type in value:
                        if isinstance(activity_type, str) and cls._is_valid_bundle_id_style(activity_type):
                            result['user_activity_types'].add(activity_type)
                else:
                    cls._recursive_parse(value, result)
        elif isinstance(data, list):
            for item in data:
                cls._recursive_parse(item, result)

    @staticmethod
    def _is_valid_class_name(name: str) -> bool:
        return name and len(name) > 1 and (name[0].isupper() or name.startswith('$'))

    @staticmethod
    def _is_valid_bundle_id_style(value: str) -> bool:
        return value and len(value) > 3 and ('.' in value or value.startswith('$'))


class CoreDataParser:
    """CoreData 모델 파일에서 식별자 추출"""

    @classmethod
    def parse(cls, model_path: Path) -> Dict[str, Set[str]]:
        result = defaultdict(set)

        if model_path.is_dir():
            for xcdatamodel in model_path.glob('*.xcdatamodel'):
                contents_file = xcdatamodel / 'contents'
                if contents_file.exists():
                    cls._parse_contents(contents_file, result)
        else:
            cls._parse_contents(model_path, result)

        return dict(result)

    @classmethod
    def _parse_contents(cls, contents_file: Path, result: defaultdict):
        try:
            tree = ET.parse(contents_file)
            root = tree.getroot()

            for entity in root.findall('.//entity'):
                name = entity.get('name')
                if name and cls._is_valid_identifier(name):
                    result['entities'].add(name)

                for attr in entity.findall('attribute'):
                    attr_name = attr.get('name')
                    if attr_name and cls._is_valid_identifier(attr_name):
                        result['attributes'].add(attr_name)

                for rel in entity.findall('relationship'):
                    rel_name = rel.get('name')
                    if rel_name and cls._is_valid_identifier(rel_name):
                        result['relationships'].add(rel_name)

            for fetch in root.findall('.//fetchRequest'):
                name = fetch.get('name')
                if name and cls._is_valid_identifier(name):
                    result['fetch_requests'].add(name)

        except Exception:
            pass

    @staticmethod
    def _is_valid_identifier(name: str) -> bool:
        """유효한 식별자인지 검사"""
        if not name or len(name) <= 1:
            return False

        if not (name[0].isalpha() or name[0] == '_'):
            return False

        for char in name:
            if not (char.isalnum() or char == '_'):
                return False

        return True


class StringsFileParser:
    """Localizable.strings 파일에서 키만 추출"""

    @classmethod
    def parse(cls, file_path: Path) -> Set[str]:
        keys = set()

        try:
            content = file_path.read_text(encoding='utf-8', errors='ignore')

            # "key" = "value"; 패턴
            pattern = re.compile(r'^"([^"]+)"\s*=\s*"[^"]*"\s*;', re.MULTILINE)

            for match in pattern.finditer(content):
                key = match.group(1)
                if key and cls._is_valid_localization_key(key):
                    keys.add(key)

        except Exception:
            pass

        return keys

    @staticmethod
    def _is_valid_localization_key(key: str) -> bool:
        """유효한 localization key인지 검사"""
        if not key or len(key) < 2:
            return False

        # 특수문자로 시작하는 키 제외 (%, $, @ 등)
        # ✅ 숫자로 시작하는 키는 허용하지 않음 (일반적이지 않음)
        if not (key[0].isalnum() or key[0] in ('_', '-')):
            return False

        # 공백이 있는 경우: 5단어 이상이면 일반 문장으로 간주
        if ' ' in key:
            words = key.split()
            if len(words) > 5:
                return False

        # 허용 문자: 영문자, 숫자, 점, 언더스코어, 하이픈, 공백(제한적)
        allowed_chars = set('abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789._- ')
        for char in key:
            if char not in allowed_chars:
                return False

        return True


class EntitlementsParser:
    """Entitlements 파일에서 식별자 추출"""

    @classmethod
    def parse(cls, file_path: Path) -> Dict[str, Set[str]]:
        result = defaultdict(set)

        try:
            tree = ET.parse(file_path)
            root = tree.getroot()

            main_dict = root.find('dict')
            if main_dict is None:
                return dict(result)

            children = list(main_dict)
            i = 0

            while i < len(children):
                if children[i].tag == 'key':
                    key = children[i].text
                    if i + 1 < len(children):
                        value_elem = children[i + 1]

                        # App Groups
                        if key == 'com.apple.security.application-groups' and value_elem.tag == 'array':
                            for string_elem in value_elem.findall('string'):
                                text = string_elem.text
                                if text and cls._is_valid_identifier(text):
                                    result['app_groups'].add(text)

                        # Keychain Access Groups
                        elif key == 'keychain-access-groups' and value_elem.tag == 'array':
                            for string_elem in value_elem.findall('string'):
                                text = string_elem.text
                                if text and cls._is_valid_identifier(text):
                                    result['keychain_groups'].add(text)

                        # iCloud Container Identifiers
                        elif key == 'com.apple.developer.icloud-container-identifiers' and value_elem.tag == 'array':
                            for string_elem in value_elem.findall('string'):
                                text = string_elem.text
                                if text and cls._is_valid_identifier(text):
                                    result['icloud_containers'].add(text)

                        # Ubiquity KV Store Identifier
                        elif key == 'com.apple.developer.ubiquity-kvstore-identifier' and value_elem.tag == 'string':
                            text = value_elem.text
                            if text and cls._is_valid_identifier(text):
                                result['ubiquity_kvstore'].add(text)

                        # Associated Domains
                        elif key == 'com.apple.developer.associated-domains' and value_elem.tag == 'array':
                            for string_elem in value_elem.findall('string'):
                                text = string_elem.text
                                if text and cls._is_valid_domain(text):
                                    result['associated_domains'].add(text)

                        i += 2
                    else:
                        i += 1
                else:
                    i += 1

        except Exception:
            pass

        return dict(result)

    @staticmethod
    def _is_valid_identifier(identifier: str) -> bool:
        """유효한 identifier인지 검사"""
        if not identifier or len(identifier) < 3:
            return False

        # 특수 케이스: $(VARIABLE) 형태
        if identifier.startswith('$(') and ')' in identifier:
            return True

        # 일반 케이스
        if not (identifier[0].isalpha() or identifier[0] == '$'):
            return False

        # 허용 문자
        allowed_chars = set('abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789._-$()')
        for char in identifier:
            if char not in allowed_chars:
                return False

        return True

    @staticmethod
    def _is_valid_domain(domain: str) -> bool:
        """유효한 associated domain인지 검사"""
        if not domain or len(domain) < 3:
            return False

        # webcredentials:example.com, applinks:example.com 패턴
        if ':' not in domain:
            return False

        parts = domain.split(':', 1)
        if len(parts) != 2:
            return False

        prefix, host = parts

        # prefix는 영문 소문자
        if not prefix.islower() or not prefix.isalpha():
            return False

        # host는 도메인 형식
        if not host or len(host) < 3:
            return False

        # 허용 문자: 영문자, 숫자, 점, 하이픈
        allowed_chars = set('abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789.-')
        for char in host:
            if char not in allowed_chars:
                return False

        return True


class ResourceScanner:
    """프로젝트 전체 리소스 스캔"""

    def __init__(self, project_path: Path, exclude_dirs: List[str] = None):
        self.project_path = Path(project_path)
        self.exclude_dirs = exclude_dirs or [
            '.build', 'build', 'DerivedData', '.git', 'node_modules',
            'Pods', 'Carthage', '.xcodeproj', '.xcworkspace'
        ]
        self.results = defaultdict(lambda: defaultdict(set))
        self.stats = defaultdict(int)

    def should_skip_directory(self, dir_path: Path) -> bool:
        dir_name = dir_path.name

        if dir_name.startswith('.') and dir_name not in ('.xcodeproj', '.xcworkspace'):
            return True

        if dir_name in self.exclude_dirs:
            return True

        return False

    def scan_all(self):
        print(f"🔍 프로젝트: {self.project_path}")
        print(f"📂 리소스 파일 검색 중...\n")

        self._scan_directory(self.project_path)

        print("\n" + "=" * 60)
        print("📊 추출 결과 요약")
        print("=" * 60)

        for file_type, categories in self.results.items():
            total = sum(len(ids) for ids in categories.values())
            if total > 0:
                print(f"\n[{file_type}]")
                for category, identifiers in sorted(categories.items()):
                    if identifiers:
                        print(f"  {category:30s}: {len(identifiers):>6}개")

        print("\n" + "=" * 60)

    def _scan_directory(self, directory: Path):
        try:
            for item in directory.iterdir():
                if item.is_dir():
                    if not self.should_skip_directory(item):
                        # CoreData 모델
                        if item.suffix == '.xcdatamodeld':
                            print(f"✓ CoreData: {item.name}")
                            parsed = CoreDataParser.parse(item)
                            self._merge_results('CoreData', parsed)
                            self.stats['coredata'] += 1

                        # Assets Catalog
                        elif item.suffix == '.xcassets':
                            print(f"✓ Assets: {item.name}")
                            parsed = AssetsParser.parse(item)
                            self._merge_results('Assets', parsed)
                            self.stats['assets'] += 1

                        else:
                            self._scan_directory(item)

                elif item.is_file():
                    if item.suffix == '.xib':
                        print(f"✓ XIB: {item.name}")
                        parsed = XIBStoryboardParser.parse(item)
                        self._merge_results('XIB/Storyboard', parsed)
                        self.stats['xib'] += 1

                    elif item.suffix == '.storyboard':
                        print(f"✓ Storyboard: {item.name}")
                        parsed = XIBStoryboardParser.parse(item)
                        self._merge_results('XIB/Storyboard', parsed)
                        self.stats['storyboard'] += 1

                    elif item.suffix == '.plist':
                        if 'xcschememanagement' not in item.name.lower():
                            print(f"✓ Plist: {item.name}")
                            parsed = PlistParser.parse(item)
                            self._merge_results('Plist', parsed)
                            self.stats['plist'] += 1

                    elif item.suffix == '.strings':
                        print(f"✓ Strings: {item.name}")
                        keys = StringsFileParser.parse(item)
                        if keys:
                            self.results['Strings']['localization_keys'].update(keys)
                        self.stats['strings'] += 1

                    elif item.suffix == '.entitlements':
                        print(f"✓ Entitlements: {item.name}")
                        parsed = EntitlementsParser.parse(item)
                        self._merge_results('Entitlements', parsed)
                        self.stats['entitlements'] += 1

        except PermissionError:
            pass

    def _merge_results(self, file_type: str, parsed: Dict[str, Set[str]]):
        for category, identifiers in parsed.items():
            self.results[file_type][category].update(identifiers)

    def get_all_identifiers(self) -> Set[str]:
        """모든 식별자 통합"""
        all_ids = set()
        for file_type, categories in self.results.items():
            for identifiers in categories.values():
                all_ids.update(identifiers)
        return all_ids

    def get_identifiers_with_metadata(self) -> Dict[str, Dict[str, any]]:
        """식별자별 메타데이터 포함하여 반환"""
        metadata = {}

        for file_type, categories in self.results.items():
            for category, identifiers in categories.items():
                for identifier in identifiers:
                    if identifier not in metadata:
                        metadata[identifier] = {
                            'sources': [],
                            'categories': []
                        }
                    metadata[identifier]['sources'].append(file_type)
                    metadata[identifier]['categories'].append(f"{file_type}.{category}")

        return metadata

    def save_to_json(self, output_path: Path, include_metadata: bool = True):
        """JSON 저장"""
        output_data = {
            "project_path": str(self.project_path),
            "description": "난독화에서 제외해야 할 리소스 파일 식별자 목록",
            "statistics": dict(self.stats),
            "identifiers_by_file_type": {}
        }

        for file_type, categories in self.results.items():
            output_data["identifiers_by_file_type"][file_type] = {
                category: sorted(list(identifiers))
                for category, identifiers in categories.items()
            }

        all_ids = self.get_all_identifiers()
        output_data["all_identifiers"] = sorted(list(all_ids))
        output_data["total_identifiers"] = len(all_ids)

        # ✅ 메타데이터 추가
        if include_metadata:
            output_data["identifiers_metadata"] = {
                identifier: {
                    'sources': list(set(meta['sources'])),
                    'categories': list(set(meta['categories']))
                }
                for identifier, meta in self.get_identifiers_with_metadata().items()
            }

        output_path.parent.mkdir(parents=True, exist_ok=True)
        with open(output_path, 'w', encoding='utf-8') as f:
            json.dump(output_data, f, indent=2, ensure_ascii=False)

        print(f"\n💾 JSON 저장: {output_path}")

    def save_to_txt(self, output_path: Path):
        """TXT 저장 (단순 리스트)"""
        all_ids = self.get_all_identifiers()
        output_path.parent.mkdir(parents=True, exist_ok=True)
        with open(output_path, 'w', encoding='utf-8') as f:
            for identifier in sorted(all_ids):
                f.write(identifier + '\n')
        print(f"💾 TXT 저장: {output_path} ({len(all_ids)}개)")

    def save_categorized_txt(self, output_dir: Path):
        """카테고리별로 분리된 TXT 파일 저장"""
        output_dir.mkdir(parents=True, exist_ok=True)

        for file_type, categories in self.results.items():
            for category, identifiers in categories.items():
                if identifiers:
                    # 파일명에서 사용 불가능한 문자 제거
                    safe_filename = f"{file_type}_{category}".replace('/', '_').replace(' ', '_')
                    output_file = output_dir / f"{safe_filename}.txt"

                    with open(output_file, 'w', encoding='utf-8') as f:
                        for identifier in sorted(identifiers):
                            f.write(identifier + '\n')

                    print(f"💾 {safe_filename}.txt: {len(identifiers)}개")

    def print_detailed_summary(self):
        """상세 요약 출력"""
        print("\n" + "=" * 60)
        print("📊 상세 분석 결과")
        print("=" * 60)

        all_ids = self.get_all_identifiers()
        metadata = self.get_identifiers_with_metadata()

        # 중복 분석
        duplicates = {k: v for k, v in metadata.items() if len(v['sources']) > 1}

        print(f"\n전체 고유 식별자: {len(all_ids)}개")
        print(f"여러 소스에서 발견된 식별자: {len(duplicates)}개")

        if duplicates:
            print("\n[중복 식별자 예시 (상위 10개)]")
            for i, (identifier, meta) in enumerate(list(duplicates.items())[:10], 1):
                sources = ', '.join(meta['sources'])
                print(f"  {i:2d}. {identifier:30s} → {sources}")

        # CoreData 속성 중 범용 이름 경고
        if 'CoreData' in self.results:
            common_names = {'id', 'date', 'title', 'name', 'type', 'description'}
            coredata_attrs = self.results['CoreData'].get('attributes', set())
            common_found = coredata_attrs & common_names

            if common_found:
                print(f"\n⚠️  CoreData에서 범용 속성명 발견: {', '.join(sorted(common_found))}")
                print("   → 난독화 시 주의: 다른 변수와 충돌 가능성")

        # Scene 레이블 중 숫자로 시작하는 것들
        if 'XIB/Storyboard' in self.results:
            scene_labels = self.results['XIB/Storyboard'].get('scene_labels', set())
            numeric_labels = {label for label in scene_labels if label[0].isdigit()}

            if numeric_labels:
                print(f"\n⚠️  숫자로 시작하는 Scene 레이블: {len(numeric_labels)}개")
                print("   예시:", ', '.join(sorted(list(numeric_labels)[:5])))
                print("   → 코드에서 실제로 참조하는지 확인 필요")

        print("\n" + "=" * 60)


def main():
    parser = argparse.ArgumentParser(
        description="iOS/macOS 리소스 파일에서 난독화 제외 대상 식별자 추출 (최종 완성 v3)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
    사용 예시:
      # 기본 사용 (JSON 저장)
      python resource_identifier_extractor.py /path/to/project -o identifiers.json

      # TXT 파일도 함께 저장
      python resource_identifier_extractor.py /path/to/project -o identifiers.json --txt identifiers.txt

      # 카테고리별 분리된 TXT 파일 저장
      python resource_identifier_extractor.py /path/to/project --categorized-txt ./output

      # 특정 디렉토리 제외
      python resource_identifier_extractor.py /path/to/project -o out.json --exclude Tests Vendor
            """
    )

    parser.add_argument('project_path', type=Path, help='프로젝트 루트 경로')
    parser.add_argument('-o', '--output', type=Path, help='JSON 파일 경로')
    parser.add_argument('--txt', type=Path, help='TXT 파일 경로 (전체 식별자 리스트)')
    parser.add_argument('--categorized-txt', type=Path, help='카테고리별 TXT 파일 저장 디렉토리')
    parser.add_argument('--exclude', nargs='+', help='제외할 디렉토리')
    parser.add_argument('--no-metadata', action='store_true', help='JSON에서 메타데이터 제외')
    parser.add_argument('--detailed', action='store_true', help='상세 분석 결과 출력')

    args = parser.parse_args()

    if not args.project_path.exists():
        print(f"❌ 경로를 찾을 수 없습니다: {args.project_path}")
        return 1

    if not args.project_path.is_dir():
        print(f"❌ 디렉토리가 아닙니다: {args.project_path}")
        return 1

    exclude_dirs = None
    if args.exclude:
        default_exclude = ['.build', 'build', 'DerivedData', '.git',
                           'node_modules', 'Pods', 'Carthage']
        exclude_dirs = default_exclude + args.exclude

    print("🚀 iOS/macOS 리소스 식별자 추출기 (최종 완성 v3)")
    print("   (XIB, Storyboard, Plist, CoreData, Strings, Entitlements, Assets)")
    print("=" * 60)
    print()

    scanner = ResourceScanner(args.project_path, exclude_dirs)
    scanner.scan_all()

    # 상세 분석 출력
    if args.detailed:
        scanner.print_detailed_summary()

    # 파일 저장
    if args.output:
        scanner.save_to_json(args.output, include_metadata=not args.no_metadata)

    if args.txt:
        scanner.save_to_txt(args.txt)

    if args.categorized_txt:
        print(f"\n📁 카테고리별 TXT 파일 저장 중...")
        scanner.save_categorized_txt(args.categorized_txt)

    print("\n✅ 완료!")
    print("💡 이 식별자들은 리소스 파일에서 참조되므로 난독화에서 제외해야 합니다.")

    # 요약 통계
    all_ids = scanner.get_all_identifiers()
    print(f"\n📈 최종 통계:")
    print(f"   총 {len(all_ids)}개의 고유 식별자 추출")
    print(f"   처리된 파일: XIB({scanner.stats['xib']}), Storyboard({scanner.stats['storyboard']}), "
          f"Plist({scanner.stats['plist']}), Strings({scanner.stats['strings']}), "
          f"CoreData({scanner.stats['coredata']}), Assets({scanner.stats['assets']}), "
          f"Entitlements({scanner.stats['entitlements']})")

    return 0


if __name__ == "__main__":
    exit(main())