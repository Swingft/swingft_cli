import os
import plistlib
import re
import sys

def obfuscate(input_path, output_path, exclude_json=None):
    """
    입력 파일(input_path)을 읽어서, 난독화(현재는 더미) 후 출력 파일(output_path)로 저장합니다.
    exclude_json: 제외목록 JSON 파일 경로 (추후 활용)
    input_path가 디렉토리면 하위 모든 .swift 파일을 재귀적으로 처리하고,
    프로젝트 관련 파일(.plist, .xcodeproj, .xcworkspace, .swiftpm, .pbxproj 등)도 project_info 폴더에 텍스트로 저장합니다.
    프로젝트 관련 파일은 상대경로를 언더스코어(_)로 치환하여 파일명에 포함시켜 저장합니다.
    """
    def find_project_files(root_dir, exts=(
        '.plist', '.xcodeproj', '.xcworkspace', '.swiftpm', '.pbxproj', '.xcconfig', '.entitlements', '.modulemap', '.xcsettings', '.xcuserstate', '.xcworkspacedata', '.xcscheme', '.xctestplan', '.xcassets', '.storyboard', '.xcdatamodeld', '.xcappdata', '.xcfilelist', '.xcplayground', '.xcplaygroundpage', '.xctemplate', '.xcsnippet', '.xcstickers', '.xcstickersicon', '.xcuserdatad', '.xcworkspace', '.xcodeproj', '.pbxproj', '.swiftpm', '.plist', '.entitlements', '.xcconfig', '.modulemap', '.storyboard', '.xcdatamodeld', '.xcassets', '.xcuserstate', '.xcscheme', '.xctestplan', '.xcworkspacedata', '.xcappdata', '.xcfilelist', '.xcplayground', '.xcplaygroundpage', '.xctemplate', '.xcsnippet', '.xcstickers', '.xcstickersicon', '.xcuserdatad'
    )):
        project_files = []
        for dirpath, _, filenames in os.walk(root_dir):
            for filename in filenames:
                if filename.endswith(exts):
                    project_files.append(os.path.join(dirpath, filename))
        return project_files

    def read_plist_as_text(plist_path):
        with open(plist_path, 'rb') as f:
            try:
                plist_data = plistlib.load(f)
                return str(plist_data)
            except Exception:
                f.seek(0)
                return f.read().decode('utf-8', errors='replace')

    def save_project_file_as_text(src_path, rel_path, output_dir):
        flat_name = re.sub(r'[\\/]', '_', rel_path) + '.txt'
        dst_path = os.path.join(output_dir, 'project_info', flat_name)
        if src_path.endswith('.plist'):
            text = read_plist_as_text(src_path)
        else:
            try:
                with open(src_path, 'r', encoding='utf-8', errors='replace') as f:
                    text = f.read()
            except Exception:
                with open(src_path, 'rb') as f:
                    text = f.read()
        os.makedirs(os.path.dirname(dst_path), exist_ok=True)
        mode = 'w' if isinstance(text, str) else 'wb'
        with open(dst_path, mode) as f:
            f.write(text)

    if os.path.isfile(input_path):
        # input이 파일이면 output이 파일이어야 함
        with open(input_path, 'r', encoding='utf-8') as infile:
            code = infile.read()
        # TODO: exclude_json을 활용한 난독화 로직 구현 예정
        os.makedirs(os.path.dirname(output_path) or '.', exist_ok=True)
        with open(output_path, 'w', encoding='utf-8') as outfile:
            outfile.write(code)
        print(f"난독화 완료: {output_path}")
    elif os.path.isdir(input_path):
        # input이 디렉토리면 output도 디렉토리여야 함
        for dirpath, _, filenames in os.walk(input_path):
            for filename in filenames:
                if filename.endswith('.swift'):
                    src_file = os.path.join(dirpath, filename)
                    rel_path = os.path.relpath(src_file, input_path)
                    dst_file = os.path.join(output_path, rel_path)
                    os.makedirs(os.path.dirname(dst_file), exist_ok=True)
                    with open(src_file, 'r', encoding='utf-8') as infile:
                        code = infile.read()
                    with open(dst_file, 'w', encoding='utf-8') as outfile:
                        outfile.write(code)
                    print(f"난독화 완료: {dst_file}")
        # 프로젝트 관련 파일들 저장
        project_files = find_project_files(input_path)
        for src_path in project_files:
            rel_path = os.path.relpath(src_path, input_path)
            save_project_file_as_text(src_path, rel_path, output_path)
            print(f"프로젝트 정보 파일 저장: {os.path.join(output_path, 'project_info', re.sub(r'[\\/]', '_', rel_path) + '.txt')}")
    else:
        print("에러: 입력 경로가 파일도 디렉토리도 아닙니다.") 