import shutil
import os

from .run_swift_syntax import run_swift_syntax
from .internal_tool.find_internal_files import find_internal_files
from .internal_tool.integration_ast import integration_ast
from .internal_tool.find_wrapper_candidates import find_wrapper_candidates
from .internal_tool.find_keyword import find_keyword
from .internal_tool.find_exception_target import find_exception_target
from .external_library_tool.find_external_files import find_external_files
from .external_library_tool.find_external_candidates import find_external_candidates
from .external_library_tool.match_candidates import match_candidates_external
from .standard_sdk_tool.find_standard_sdk import find_standard_sdk
from .standard_sdk_tool.match_candidates import match_candidates_sdk
from .obfuscation_tool.get_external_name import get_external_name
from .obfuscation_tool.merge_exception_list import merge_exception_list
from .obfuscation_tool.exception_tagging import exception_tagging

def run_ast(code_project_dir):
    original_dir = os.getcwd()  

    # 필요한 디렉토리 생성
    os.makedirs("./AST/output/source_json/", exist_ok=True) 
    os.makedirs("./AST/output/typealias_json/", exist_ok=True)
    os.makedirs("./AST/output/external_to_ast/", exist_ok=True)
    os.makedirs("./AST/output/sdk-json/", exist_ok=True)

    # 소스코드 & 외부 라이브러리 파일 위치 수집 
    find_internal_files(code_project_dir)
    find_external_files(code_project_dir)

    # 소스코드, 외부 라이브러리 AST 파싱 & 소스코드 AST 선언부 통합
    run_swift_syntax()
    os.chdir(original_dir)
    integration_ast()

    # 외부 라이브러리 / 표준 SDK 후보 추출 & 외부 라이브러리 요소 식별
    find_external_candidates()
    match_candidates_external()

    p_same_name = set()
    # 표준 SDK 정보 추출 & 표준 SDK 요소 식별
    path = "./AST/output/import_list.txt"
    if os.path.exists(path):
        p_same_name = find_standard_sdk()
        match_candidates_sdk()
    
    # 래퍼 후보 추출 & 내부 제외 대상 식별 
    find_wrapper_candidates()
    find_keyword()
    p_same_name.update(get_external_name())
    find_exception_target(p_same_name)

    # 제외 대상 리스트 병합
    merge_exception_list()
    exception_tagging()
