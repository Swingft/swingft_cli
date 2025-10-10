import random
import string
from .identifier_list import large_identifiers, small_identifiers

def generate_random_name(flag):
    if flag in (1, 3):
        new_id = random.choice(large_identifiers)
        large_identifiers.remove(new_id)
    else:
        new_id = random.choice(small_identifiers)
        small_identifiers.remove(new_id)

    return new_id

def generate_deadcode():
    def template_one():
        func_name = generate_random_name(2)

        code_template = rf"""
@inline(never)
func {func_name}() -> Int {{
    let beforeNum = Int.random(in: 1...100)
    let afterNum = Int.random(in: 1...100)
    if beforeNum * afterNum == 10 {{
        print("\(beforeNum), \(afterNum)")
    }}
    return beforeNum + afterNum
}}
        """
        call_template = rf"""
if 5 == 3 || 2 > 3 {{
    var result = {func_name}()
    result += 100
}}
        """

        return func_name, code_template, call_template  
    
    def template_two():
        func_name = generate_random_name(2)

        code_template = rf"""
@inline(never)
func {func_name}() -> String {{
    let letters = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
    let result = String((0..<5).map {{ _ in letters.randomElement()! }})
    return result
}}
        """
        call_template = rf"""
if Int.random(in: 0...0) == 1 {{
    var result = {func_name}()
    let nums = [1, 2, 3, 4, 5]
    let numDoubled = nums.map {{ $0 * 2 }}

    for num in numDoubled {{
        result += "-\(num)"
    }}

    result.append(" - \({func_name}())")
    print(result)
}}
        """

        return func_name, code_template, call_template  

    def template_three():
        opt_numbers = generate_random_name(0)
        func_name = generate_random_name(2)
        random_num = random.randint(0, 5000)
        random_num_list = random.randint(0, 4)
        random_list = ", ".join(str(random.randint(0, 5000)) for _ in range(5))
        random_string = "".join(random.choices(string.ascii_letters, k = 7))
        random_num_if = random.randint(0, 5000)
        random_num_loop = random.randint(5, 10)
        random_mult = random.randint(1, 5000)

        code_template = rf"""
@inline(never)
func {func_name}(_ userName: String) {{
    let apiKeyNum = {random_num}
    let apiKeyName = userName

    let array = [{random_list}]
    let randomArray = array.map{{ $0 * {random_mult} }}

    if array[{random_num_list}] == {random_num_if} {{
        print("The API key for \(apiKeyName) is \(apiKeyName)\(apiKeyNum)")
        for index in 0...{random_num_loop} {{
            let userSerialKey = index * {random_mult}
        }}
    }}
}}
        """
        call_template = rf"""
if false {{
    {func_name}("{random.choice(random_string)}")
    let {opt_numbers} = {random.randint(3, 100)} + 3
}}
        """

        return func_name, code_template, call_template
    
    def template_four():
        opt_numbers = generate_random_name(0)
        func_name = generate_random_name(2)

        code_template = rf"""
let {opt_numbers}: String? = nil

@inline(never)
func {func_name}() {{
    print("nongshin.com")
}}
        """
        call_template = rf"""
if {opt_numbers} != nil && {opt_numbers}!.hasPrefix("x") {{
    {func_name}()
}}
        """

        return func_name, code_template, call_template  
    
    def template_five():
        class_name = generate_random_name(1)
        class_var_name = generate_random_name(0)
        class_enum_name = generate_random_name(3)
        class_func_name = generate_random_name(2)
        class_case_name = generate_random_name(4)
        class_random_value = "".join(random.choices(string.ascii_letters, k = 5))
        random_string = "".join(random.choices(string.ascii_letters, k = 7))
        
        code_template = rf"""
@objcMembers 
class {class_name} {{
    let {class_var_name}: String

    init(_ {class_var_name}: String) {{
        self.{class_var_name} = {class_var_name}
    }}

    enum {class_enum_name}: String {{
        var value: String {{ return "{class_random_value}"}}
        case {generate_random_name(4)}
        case {generate_random_name(4)}
        case {class_case_name}
    }}

    func {class_func_name}() -> {class_enum_name} {{
        return .{class_case_name}
    }}
}}
        """
        call_template = rf"""
if Bool.random() && false {{
    let use = {class_name}("{random_string}")
    let resultCase = use.{class_func_name}()

    var aCase = {class_name}.{class_enum_name}.{class_case_name}.value
    aCase.append(contentsOf: use.{class_var_name}.reversed())

    let nums = [1, 2, 3, 4, 5]
    let squared = nums.map {{ $0 * $0 }}.filter {{ $0 % 2 == 0 }}

    for num in squared {{
        aCase += "\(num)\(use.{class_var_name}.prefix(1))"
    }}

    print(aCase, resultCase)
}}
        """

        return "-1", code_template, call_template  
    
    def template_six(in_func_name):
        global_var_name = generate_random_name(0)
        func_var_name = in_func_name[0].upper() + in_func_name[1:]

        code_template = rf"""
let {global_var_name} = 0
        """
        call_template = rf"""
if {global_var_name} == 0 {{
    var result{func_var_name}: Any = {in_func_name}()
    
    if let intVal = result{func_var_name} as? Int {{
        if intVal != 0 && intVal % 2 == 1 {{
            result{func_var_name} = intVal - 1
        }}
    }} else if let strVal = result{func_var_name} as? String {{
        if !strVal.isEmpty && strVal.hasPrefix("H") {{
            result{func_var_name} = strVal + "StartH"
        }}
    }}
}}
        """
        return code_template, call_template


    functions = [template_one, template_two, template_three, template_four, template_five, template_six]
    global_var = "-1"
    global_call = "-1"
    if len(small_identifiers) < 1:
        return "-1", "-1", "-1", "-1"
    if len(small_identifiers) < 2:
        f = random.choice(functions[0:2])
        func_name, decl, call = f()
    elif len(small_identifiers) < 3:
        f = random.choice(functions[0:4])
        func_name, decl, call = f()
    elif len(small_identifiers) < 5:
        f = random.choice(functions[0:4] + functions[5])
        if f == functions[5]:
            use_f = random.choice(functions[0:4])
            func_name, decl, call = use_f()
            global_var, global_call = f(func_name)
        else:
            func_name, decl, call = f()
    elif len(small_identifiers) >= 5 and len(large_identifiers) >= 2:
        f = random.choice(functions)
        if f == functions[5]:
            use_f = random.choice(functions[0:2])
            func_name, decl, call = use_f()
            global_var, global_call = f(func_name)
        else:
            func_name, decl, call = f()
    else:
        return "-1", "-1", "-1", "-1"

    return decl, call, global_var, global_call