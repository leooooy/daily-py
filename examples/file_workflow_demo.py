#!/usr/bin/env python3
"""DailyPy - 简易工作流演示脚本
演示从创建到清理一个完整的文件工作流，使用 daily_py.file_handler.FileHandler。
"""

import shutil
from pathlib import Path
from daily_py import FileHandler


def print_tree(root: Path, prefix: str = ""):
    if not root.exists():
        return
    items = sorted([p for p in root.iterdir()], key=lambda p: p.name)
    for i, p in enumerate(items):
        connector = "└── " if i == len(items) - 1 else "├── "
        print(prefix + connector + str(p.name))
        if p.is_dir():
            extension = "    " if i == len(items) - 1 else "│   "
            print_tree(p, prefix + extension)


def main() -> int:
    base = Path("demo_workflow")
    if base.exists():
        shutil.rmtree(base)

    fh = FileHandler(base_path=base)

    print("=== DailyPy 工作流演示：从创建到清理 ===")

    # 1. 创建目录
    fh.create_directory("data/input")
    fh.create_directory("data/output")
    fh.create_directory("data/archive")
    fh.create_directory("output")

    # 2. 创建示例文件
    (base / "data" / "input" / "a.txt").write_text("这是文件 A。\n第一行文本。\n", encoding="utf-8")
    (base / "data" / "input" / "b.txt").write_text("这是文件 B。\n第二行文本。\n", encoding="utf-8")

    # 3. 列出目录
    print("3. 当前 data/input 下的 txt 文件:")
    for p in fh.list_files("data/input", pattern="*.txt"):
        print(" -", str(p))

    # 4. 复制文件
    fh.copy_file("data/input/a.txt", "data/input/a_copy.txt")

    # 5. 重命名文件
    fh.rename_file("data/input/a_copy.txt", "data/input/a_copy_renamed.txt")

    # 6. 移动文件
    fh.move_file("data/input/a_copy_renamed.txt", "data/output/a_copy_renamed.txt")

    # 7. 备份文件
    backup_path = fh.backup_file("data/input/b.txt")
    print("备份文件:", str(backup_path))

    # 8. 压缩
    fh.compress_files(["data/input/a.txt", "data/input/b.txt"], "data/archive/workflow.zip")

    # 9. 解压
    fh.extract_archive("data/archive/workflow.zip", "output/workflow_extracted")

    # 10. 批量重命名
    renamed = fh.batch_rename("data/input", "b", "b_renamed")
    print("批量重命名数量:", renamed)

    # 11. 清理空目录
    removed = fh.clean_empty_dirs("demo_workflow")
    print("清理的空目录数量:", removed)

    # 12. 最终结构展示
    print("\n最终目录结构：")
    print_tree(base)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
