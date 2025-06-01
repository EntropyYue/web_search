import ast
import os
import json


def replace_imports(
    modules, main_file_path="src/main.py", output_dir="dist", output_filename=None
):
    """
    将主脚本中导入了指定模块的语句替换为这些模块的实际内容，
    并将结果写入 dist/ 目录下的自定义文件名（如：output_main.py）。

    :param modules: 模块名列表，例如 ['module1', 'module2']。
    :param main_file_path: 主脚本路径，默认是 "src/main.py"。
    :param output_dir: 输出目录，用于保存处理后的结果，默认为 "dist"。
    :param output_filename: 导出文件的名称（不含路径），默认使用原主文件名（如 'main.py'）。
    """

    # 确保输出目录存在
    os.makedirs(output_dir, exist_ok=True)

    # 读取并解析目标模块内容（所有在初始 modules 列表中的）
    preloaded_modules = {}
    for module_name in modules:
        file_path = f"src/{module_name}.py"
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                code = f.read()
            ast_module = ast.parse(code, filename=file_path)
            preloaded_modules[module_name] = ast_module
        except Exception as e:
            print(f"❌ 读取/解析模块 {file_path} 失败: {e}")

    # 读取并解析主文件内容
    try:
        with open(main_file_path, "r", encoding="utf-8") as f:
            main_code = f.read()
        main_ast = ast.parse(main_code, filename=main_file_path)
    except Exception as e:
        print(f"❌ 解析 {main_file_path} 失败: {e}")
        return

    # 初始化已处理模块集合
    processed_modules = set()

    while True:
        found_new_module = False  # 标记是否在本轮中找到了新的可替换的导入语句

        for i in range(len(main_ast.body) - 1, -1, -1):
            node = main_ast.body[i]

            if isinstance(node, ast.Import):
                replace_flag = False
                module_name = None
                # 遍历所有别名，找到第一个匹配的模块，并处理它
                for alias in node.names:
                    if alias.name in modules and alias.name not in processed_modules:
                        replace_flag = True
                        module_name = alias.name
                        break

                if replace_flag and module_name in preloaded_modules:
                    target_body = preloaded_modules[module_name].body
                    main_ast.body[i : i + 1] = target_body  # 替换导入语句为模块内容
                    processed_modules.add(module_name)
                    found_new_module = True

            elif isinstance(node, ast.ImportFrom):
                module_name = node.module
                if module_name in modules and module_name not in processed_modules:
                    if module_name in preloaded_modules:
                        target_body = preloaded_modules[module_name].body
                        main_ast.body[i : i + 1] = target_body  # 替换导入语句为模块内容
                        processed_modules.add(module_name)
                        found_new_module = True

        # 如果本轮没有发现新的可替换的模块，退出循环
        if not found_new_module:
            break

    # 设置输出文件路径和名称
    base_main_filename = os.path.basename(main_file_path)  # 如 'main.py'
    default_output_name = (
        base_main_filename.split(".")[0] + ".py"
    )  # 默认使用原主文件名（如 main.py）

    if output_filename is None:
        final_output_name = default_output_name
    else:
        final_output_name = output_filename

    output_file_path = os.path.join(output_dir, final_output_name)

    try:
        with open(output_file_path, "w", encoding="utf-8") as f:
            f.write(ast.unparse(main_ast))
        print(f"✅ 处理完成，结果已写入 {output_file_path}")
    except Exception as e:
        print(f"❌ 将修改后的内容写入 {output_file_path} 失败: {e}")


if __name__ == "__main__":
    with open("modules.json", "r") as f:
        preloaded_modules = json.load(f)
    replace_imports(
        modules=preloaded_modules,
        main_file_path="src/main.py",
        output_dir="dist",
        output_filename="plugin.py",
    )
