import os
import re
import sys

# 더 포괄적인 Swift 식별자 패턴
patterns = [
    # 타입 선언: class, struct, enum, protocol, actor, extension
    re.compile(r'\b(class|struct|enum|protocol|actor|extension)\s+([A-Za-z_][A-Za-z0-9_]*)'),
    # 함수 선언: func name() 또는 func name(param: Type)
    re.compile(r'\bfunc\s+([A-Za-z_][A-Za-z0-9_]*)'),
    # 변수/상수 선언: var name, let name
    re.compile(r'\b(var|let)\s+([A-Za-z_][A-Za-z0-9_]*)'),
    # 타입 별칭: typealias
    re.compile(r'\btypealias\s+([A-Za-z_][A-Za-z0-9_]*)'),
]

def extract_identifiers_from_file(file_path):
    identifiers = []
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            content = f.read()
            for pattern in patterns:
                matches = pattern.findall(content)
                for match in matches:
                    if isinstance(match, tuple):
                        identifiers.append(match[1])  # 두 번째 그룹 (실제 이름)
                    else:
                        identifiers.append(match)   # 단일 그룹
    except Exception as e:
        print(f"[Error] {file_path}: {e}")
    return list(set(identifiers))  # 중복 제거



def extract_identifiers_from_project(root_dir):
    all_identifiers = {}
    for subdir, _, files in os.walk(root_dir):
        for file in files:
            if file.endswith(".swift"):
                path = os.path.join(subdir, file)
                ids = extract_identifiers_from_file(path)
                if ids:
                    all_identifiers[path] = ids
    return all_identifiers


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("사용법: python extract_identifiers.py <프로젝트 폴더 경로>")
        sys.exit(1)

    project_path = sys.argv[1]
    result = extract_identifiers_from_project(project_path)

    with open("identifiers.txt", "w", encoding="utf-8") as out:
        for file, ids in result.items():
            out.write(f"[File] {file}\n")
            for ident in ids:
                out.write(f"  - {ident}\n")
            out.write("\n")
    print("결과가 identifiers.txt 파일에 저장되었습니다.")

    for file, ids in result.items():
        print(f"\n[File] {file}")
        for ident in ids:
            print("  -", ident)