import os
from .identifier_list import read_identifier_list
from .insert_deadcode import insert_deadcode

def deadcode():
    swift_file_path = []
    # swift 파일 경로 저장
    file_path = "./swift_file_list.txt"
    if os.path.exists(file_path):
        with open(file_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                swift_file_path.append(line)
    
    read_identifier_list()
    insert_deadcode(swift_file_path)