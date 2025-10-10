import json
import re
import os

MATCHED_LIST = []
STORYBOARD_AND_XC_WRAP_NAME = []

# 제외 대상 MATCHED_LIST에 추가
def in_matched_list(node):
    if node not in MATCHED_LIST:
        MATCHED_LIST.append(node)

# 스토리보드, xcassets
def get_storyboard_and_xc_wrapper_info():
    storyboard_path = "./AST/output/storyboard_list.txt"
    if os.path.exists(storyboard_path):
        with open(storyboard_path, "r", encoding="utf-8") as f:
            for name in f:
                name = name.strip()
                if name:
                    STORYBOARD_AND_XC_WRAP_NAME.append(name)

    xc_path = "./AST/output/xc_list.txt"
    if os.path.exists(xc_path):
        with open(xc_path, "r", encoding="utf-8") as f:
            for name in f:
                name = name.strip()
                if name:
                    STORYBOARD_AND_XC_WRAP_NAME.append(name)
    
    wrapper_path = "./AST/output/wrapper_list.txt"
    if os.path.exists(wrapper_path):
        with open(wrapper_path, "r", encoding="utf-8") as f:
            for name in f:
                name = name.strip()
                if name:
                    STORYBOARD_AND_XC_WRAP_NAME.append(name)
    
    keyword_path = "./AST/output/keyword_list.txt"
    if os.path.exists(keyword_path):
        with open(keyword_path, "r", encoding="utf-8") as f:
            for name in f:
                name = name.strip()
                if name:
                    STORYBOARD_AND_XC_WRAP_NAME.append(name)

def check_attribute(node, p_same_name):
    def check_member():
        members = node.get("G_members", [])
        for member in members:
            check_attribute(member, p_same_name)

    attributes = node.get("D_attributes", [])
    adopted = node.get("E_adoptedClassProtocols", [])
    members = node.get("G_members", [])

    name = node.get("A_name")

    # 스토리보드, assets, wrapper 식별자
    if node.get("A_name") in STORYBOARD_AND_XC_WRAP_NAME:
        in_matched_list(node)

    # 앱 진입점
    if "main" in attributes or "UIApplicationMain" in attributes or "UIApplicationDelegate" in adopted or "UIWindowSceneDelegate" in adopted or "App" in adopted:
        in_matched_list(node)
        for member in members:
            if member.get("B_kind") == "variable" and member.get("A_name") == "body":
                in_matched_list(member)
            if member.get("B_kind") == "function" and member.get("A_name") == "main":
                in_matched_list(member)

    # ui
    skip_attrs = {"IBOutlet", "IBAction", "IBInspectable", "IBDesignable",  "State", "StateObject"}
    if any(attr in skip_attrs for attr in attributes):
        in_matched_list(node)
    
    # 런타임 참조
    if "objc" in attributes or "dynamic" in attributes or "NSManaged" in attributes:
        in_matched_list(node)

    if "objcMembers" in attributes:
        in_matched_list(node)
        for member in members:
            in_matched_list(member)
    
    # 데이터베이스
    if "Model" in attributes:
        in_matched_list(node)
        for member in members:
            if member.get("B_kind") == "variable": 
                in_matched_list(member)

    # actor
    if "globalActor" in attributes:
        in_matched_list(node)
        for member in members:
            if member.get("A_name") == "shared" and member.get("B_kind") == "variable":
                in_matched_list(member)
    
    if name in ["get", "set", "willSet", "didSet", "init"]:
        in_matched_list(node)

    if name.startswith("`") and name.endswith("`"):
        name = name[1:-1]
    if name in p_same_name:
        in_matched_list(node)

    check_member()

# 자식 노드가 자식 노드를 가지는 경우
def repeat_match_member(data, p_same_name):
    if data is None: 
        return
    node = data.get("node", data)
    extensions = data.get("extension", [])
    children = data.get("children", [])

    check_attribute(node, p_same_name)
    for extension in extensions:
        repeat_match_member(extension, p_same_name)
    for child in children:
        repeat_match_member(child, p_same_name)

# node 처리
def find_node(data, p_same_name):
    if isinstance(data, list):
        for item in data:
            repeat_match_member(item, p_same_name)

    elif isinstance(data, dict):
        for _, node in data.items():
            check_attribute(node, p_same_name)

def find_exception_target(p_same_name):
    input_file_1 = "./AST/output/inheritance_node.json"
    input_file_2 = "./AST/output/no_inheritance_node.json"
    output_file_1 = "./AST/output/internal_exception_list.json"

    get_storyboard_and_xc_wrapper_info()
    
    if os.path.exists(input_file_1):
        with open(input_file_1, "r", encoding="utf-8") as f:
            nodes = json.load(f)
        find_node(nodes, p_same_name)
    if os.path.exists(input_file_2):
        with open(input_file_2, "r", encoding="utf-8") as f:
            nodes = json.load(f)
        find_node(nodes, p_same_name)
    
    with open(output_file_1, "w", encoding="utf-8") as f:
        json.dump(MATCHED_LIST, f, indent=2, ensure_ascii=False)
    
    temp = "./AST/output/external_name.txt"
    with open(temp, "w", encoding="utf-8") as f:
        for name in p_same_name:
            f.write(f"{name}\n")