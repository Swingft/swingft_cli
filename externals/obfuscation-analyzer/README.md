# Swift Obfuscation Analyzer

iOS/macOS Swift 프로젝트에서 난독화 제외 대상을 자동으로 분석하는 CLI 도구입니다.

## 🚀 빠른 시작

### 요구사항

- **Python 3.8+**
- **Swift 5.9+** (SymbolExtractor 빌드용)
- macOS 12.0+ (권장)

### 설치

```bash
# 1. 저장소 클론 또는 압축 해제
cd obfuscation-analyzer

# 2. Python 의존성 설치
pip install -r requirements.txt

# 3. 첫 실행 시 자동으로 Swift 코드가 빌드됩니다
python analyze.py /path/to/YourProject.xcodeproj
```

### 수동 빌드 (선택사항)

```bash
# Swift SymbolExtractor 미리 빌드
cd swift-extractor
swift build -c release
cd ..

# 빌드 스킵하고 실행
python analyze.py /path/to/project --skip-build
```

## 📖 사용법

### 기본 사용

```bash
# .xcodeproj 프로젝트 분석
python analyze.py /path/to/MyApp.xcodeproj

# .xcworkspace 분석
python analyze.py /path/to/MyApp.xcworkspace

# 프로젝트 루트 디렉토리 분석 (자동 탐지)
python analyze.py /path/to/project
```

### 고급 옵션

```bash
# 출력 디렉토리 지정
python analyze.py /path/to/project -o ./custom_output

# DerivedData 검색용 프로젝트 이름 명시
python analyze.py /path/to/project -p "RealProjectName"

# 디버그 모드 (모든 중간 파일 보존)
python analyze.py /path/to/project --debug

# 빌드 건너뛰기 (이미 빌드된 경우)
python analyze.py /path/to/project --skip-build
```

## 📊 출력 파일

분석 결과는 `analysis_output/` 디렉토리에 저장됩니다:

| 파일 | 설명 | 기본 보존 |
|------|------|----------|
| `exclusion_list.txt` | 난독화 제외 대상 심볼 이름 목록 (최종 결과) | ✅ |
| `exclusion_report.json` | 상세 분석 결과 (이유 포함) | ❌ (--debug) |
| `symbol_graph.json` | 전체 심볼 그래프 | ❌ (--debug) |
| `external_identifiers.txt` | 외부 참조 식별자 목록 | ❌ (--debug) |

## 🏗️ 프로젝트 구조

```
obfuscation-analyzer/
├── swift-extractor/              # Swift 소스코드 (자동 빌드)
│   ├── Sources/
│   │   ├── Analyzers/           # Plist/Storyboard 분석기
│   │   ├── Extractor/           # 심볼 추출 로직
│   │   ├── Models/              # 데이터 모델
│   │   └── SymbolExtractor/     # 메인 실행 파일
│   ├── Package.swift
│   └── .build/                  # 빌드 결과 (자동 생성)
│       └── release/
│           └── SymbolExtractor
│
├── lib/
│   ├── extractors/              # 외부 식별자 추출기
│   ├── analyzer/                # 규칙 기반 분석 엔진
│   └── utils/                   # 리포트 생성 등
│
├── rules/
│   └── swift_exclusion_rules.yaml  # 분석 규칙
│
├── analyze.py                   # 메인 CLI
├── requirements.txt
└── README.md
```

## 🔍 분석 과정

1. **외부 식별자 추출**
   - Objective-C 헤더 스캔 (프로젝트 + SPM)
   - 리소스 파일 분석 (XIB, Storyboard, Plist 등)

2. **심볼 그래프 생성**
   - Swift 소스코드 파싱
   - 심볼 간 관계 추출 (상속, 프로토콜 준수 등)

3. **규칙 기반 분석**
   - 190개 이상의 패턴 규칙 적용
   - 난독화 제외 대상 자동 탐지

4. **결과 리포트 생성**
   - 제외 대상 목록 생성
   - 통계 및 요약 정보 출력

## ⚙️ 문제 해결

### Swift 컴파일러를 찾을 수 없음

```bash
# Swift 설치 확인
swift --version

# Swift 설치 (macOS)
xcode-select --install

# Swift 설치 (Linux/Windows)
# https://swift.org/download/ 참조
```

### 빌드 실패

```bash
# 의존성 업데이트
cd swift-extractor
swift package update
swift build -c release
```

### Python 의존성 오류

```bash
# 가상환경 사용 권장
python -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate
pip install -r requirements.txt
```

## 📄 라이선스

MIT License

## 🤝 기여

이슈 및 PR 환영합니다!