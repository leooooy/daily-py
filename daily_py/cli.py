#!/usr/bin/env python3
"""DailyPy - 命令行界面的文件处理器入口

提供一个简易 CLI，方便在命令行进行常用的文件操作。"""

import argparse
from daily_py import FileHandler
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser(prog="dailypy", description="DailyPy 文件处理 CLI")
    sub = parser.add_subparsers(dest="cmd", required=True)

    # delete
    del_p = sub.add_parser("delete", help="删除文件或目录")
    del_p.add_argument("--path", required=True, help="要删除的文件或目录路径")

    # rename
    rn = sub.add_parser("rename", help="重命名文件或目录")
    rn.add_argument("--old", required=True, help="源路径")
    rn.add_argument("--new", required=True, help="目标路径")

    # move
    mv = sub.add_parser("move", help="移动文件或目录")
    mv.add_argument("--src", required=True, help="源路径")
    mv.add_argument("--dst", required=True, help="目标路径")

    # copy
    cp = sub.add_parser("copy", help="复制文件或目录")
    cp.add_argument("--src", required=True, help="源路径")
    cp.add_argument("--dst", required=True, help="目标路径")

    # mkdir
    md = sub.add_parser("mkdir", help="创建目录")
    md.add_argument("--path", required=True, help="要创建的目录路径")
    md.add_argument("--parents", action="store_true", help="若需要，创建父目录")

    # list
    ls = sub.add_parser("list", help="列出目录中的文件")
    ls.add_argument("--path", required=True, help="目标目录路径")
    ls.add_argument("--pattern", default="*", help="文件模式，如 *.txt")

    # info
    info = sub.add_parser("info", help="获取文件信息")
    info.add_argument("--path", required=True, help="目标文件路径")

    # backup
    bk = sub.add_parser("backup", help="备份文件")
    bk.add_argument("--path", required=True, help="要备份的文件路径")
    bk.add_argument("--backup-dir", dest="backup_dir", default=None, help="备份目录（可选）")

    # compress
    comp = sub.add_parser("compress", help="压缩文件")
    comp.add_argument("--files", nargs="+", required=True, help="要压缩的文件列表")
    comp.add_argument("--archive", required=True, help="输出归档路径")
    comp.add_argument("--format", default="zip", help="归档格式，zip 为默认格式")

    # extract
    ext = sub.add_parser("extract", help="解压归档文件")
    ext.add_argument("--archive", required=True, help="要解压的归档文件")
    ext.add_argument("--dest", required=True, help="解压目标目录")

    # batch-rename
    br = sub.add_parser("batch-rename", help="批量重命名文件")
    br.add_argument("--directory", required=True, help="目标目录")
    br.add_argument("--pattern", required=True, help="要替换的模式")
    br.add_argument("--replacement", required=True, help="替换文本")
    br.add_argument("--use-regex", action="store_true", help="是否使用正则表达式")

    # rename-recursive
    rr = sub.add_parser("rename-recursive", help="递归批量重命名（可选包含目录名）")
    rr.add_argument("--directory", required=True, help="起始目录")
    rr.add_argument("--pattern", required=True, help="替换模式（文本或正则）")
    rr.add_argument("--replacement", required=True, help="替换文本")
    rr.add_argument("--use-regex", action="store_true", help="是否将 pattern 视为正则表达式")
    rr.add_argument("--include-dirs", action="store_true", help="是否对目录名也应用重命名")
    rr.add_argument("--dry-run", action="store_true", help="仅预览，不执行重命名")

    args = parser.parse_args()
    fh = FileHandler()

    try:
        import json
        if args.cmd == "delete":
            print(fh.delete_file(args.path))
        elif args.cmd == "rename":
            print(fh.rename_file(args.old, args.new))
        elif args.cmd == "move":
            print(fh.move_file(args.src, args.dst))
        elif args.cmd == "copy":
            print(fh.copy_file(args.src, args.dst))
        elif args.cmd == "mkdir":
            print(fh.create_directory(args.path, parents=args.parents))
        elif args.cmd == "list":
            for p in fh.list_files(args.path, args.pattern):
                print(p)
        elif args.cmd == "info":
            info = fh.get_file_info(args.path)
            for k, v in info.items():
                print(f"{k}: {v}")
        elif args.cmd == "backup":
            bp = fh.backup_file(args.path, args.backup_dir)
            print(bp)
        elif args.cmd == "compress":
            print(fh.compress_files(args.files, args.archive, format=args.format))
        elif args.cmd == "extract":
            print(fh.extract_archive(args.archive, args.dest))
        elif args.cmd == "batch-rename":
            renamed = fh.batch_rename(args.directory, args.pattern, args.replacement, use_regex=args.use_regex)
            print(renamed)
        elif args.cmd == "rename-recursive":
            res = fh.batch_rename_recursive(
                args.directory,
                args.pattern,
                args.replacement,
                use_regex=args.use_regex,
                include_dirs=args.include_dirs,
                dry_run=args.dry_run,
            )
            print(json.dumps(res, ensure_ascii=False, indent=2))
        else:
            parser.print_help()
            return 2
    except Exception as e:
        print(f"错误: {e}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
