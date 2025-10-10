import random
from .generate_deadcode import generate_deadcode

def insert_deadcode(swift_file_path):
    for path in swift_file_path:
        with open(path, "r", encoding="utf-8") as f:
            source_code = f.read()

        global_idx = -1 
        call_line = [] 
        func_line = []
        idx = 0
        in_string = False 
        in_func = False
        in_comment = False
        level = 0
        count = {"top": 0, "func": 0}
        for line in source_code.splitlines():

            for i, char in enumerate(line):
                if char == '"' and (i == 0 or line[i-1] != '\\'):
                    in_string = not in_string

            if "/*" in line:
                in_comment = True
            
            if "*/" in line:
                in_comment = False
                idx += 1
                continue
            
            if "//" in line:
                idx += 1
                continue

            if global_idx == -1:
                if "import " in line:
                    global_idx = idx + 1
                idx += 1
                continue
            
            if not in_comment and not in_string and "class "  in line or "struct "  in line or "extension " in line or "enum " in line:
                if "extension " in line and level == 0:
                    break

                level += 1
                count["top"] += line.count("{") - line.count("}")

            if not in_comment and not in_string and level == 1:
                if "func " in line:
                    prev_line = source_code.splitlines()[idx - 1].strip()
                    if not prev_line.startswith("@") or not prev_line.startswith("//") or not prev_line.startswith("/*") or not prev_line.endswith("*/"):
                        func_line.append(idx - 1)

                if "func " in line and "{" in line and "static " not in line and "->" not in line:
                    in_func = True
                    count["func"] += line.count("{") - line.count("}")
                    
                    if count["func"] == 1:
                        call_line.append(idx + 1)
                
                if in_func:
                    count["func"] += line.count("{") - line.count("}")
                
                if count["func"] == 0:
                    in_func = False

                count["top"] += line.count("{") - line.count("}")

                if count["top"] == 0:
                    level -= 1
                    break

            idx += 1

        if global_idx != -1 and call_line and func_line:
            decl, call, global_var, global_call = generate_deadcode()
            if decl == "-1":
                break

            candidates = []
            for idx in call_line:
                if idx != global_idx:
                    candidates.append(idx)
            if candidates:  
                call_idx = random.choice(candidates)
            else:
                continue

            candidates = []
            for idx in func_line:
                if idx != global_idx and idx != call_idx:
                    candidates.append(idx)
            if candidates:
                func_idx = random.choice(candidates)
            else:
                continue
            
            new_source_code = ""
            for idx, line in enumerate(source_code.splitlines()):
                line_indent = len(line) - len(line.lstrip())
                if global_var != "-1" and idx == global_idx: # 전역 변수 선언부
                    new_source_code += line + "\n"
                    indented_code = "\n".join(" " * line_indent + l for l in global_var.splitlines())
                    new_source_code += indented_code + "\n"
                elif idx == func_idx:                        # 함수 선언부
                    new_source_code += line + "\n"
                    indented_func = "\n".join(" " * line_indent + l for l in decl.splitlines())
                    new_source_code += indented_func + "\n"
                elif idx == call_idx:                        # 호출부
                    call_code = call
                    if global_var != "-1":
                        call_code = global_call
                    indented_call = "\n".join(" " * line_indent + l for l in call_code.splitlines())
                    new_source_code += indented_call + "\n"
                    new_source_code += line + "\n"
                else:
                    new_source_code += line + "\n"
                
            with open(path, "w", encoding="utf-8") as f:
                f.write(new_source_code)