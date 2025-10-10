import os
import re

SWIFT_FILE_PATH = []

def read_file():
    # swift 파일 경로 저장
    swift_file_path = "./swift_file_list.txt"
    if os.path.exists(swift_file_path):
        with open(swift_file_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                SWIFT_FILE_PATH.append(line)
    
def find_wrapper_candidates():
    read_file()

    wrapper_candidates = []
    remove_candidates = []
    for file_path in SWIFT_FILE_PATH:
        if os.path.exists(file_path):
            with open(file_path, "r", encoding="utf-8") as f:
                source_code = f.read()
            
            pattern_wrapper = re.compile(r'_([A-Za-z0-9_]\w*)')
            matches = pattern_wrapper.findall(source_code)
            wrapper_candidates.extend(matches)

            pattern_let = re.compile(r'\blet\s+_([A-Za-z]\w*)')
            let_matches = pattern_let.findall(source_code)
            remove_candidates.extend(let_matches)

            pattern_var = re.compile(r'\bvar\s+_([A-Za-z]\w*)')
            var_matches = pattern_var.findall(source_code)
            remove_candidates.extend(var_matches)

    wrapper_candidates = list(set(wrapper_candidates) - set(remove_candidates))

    output_path = "./AST/output/wrapper_list.txt"
    with open(output_path, "w", encoding="utf-8") as f:
        for candidate in wrapper_candidates:
            f.write(f"{candidate}\n")
