#!/usr/bin/env python3
"""
FileHandler 使用示例和 CLI 工具

用法示例:
  # 批量重命名
  python file_handler_use.py rename /path/to/dir "old" "new" --recursive

  # 列出文件
  python file_handler_use.py list /path/to/dir --pattern "*.txt"

  # 备份文件
  python file_handler_use.py backup /path/to/file --backup-dir /path/to/backup

  # 压缩文件
  python file_handler_use.py compress /path/to/files --output archive.zip

  # 查找重复文件
  python file_handler_use.py duplicates /path/to/dir
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path
from typing import Optional

from .file_handler import FileHandler


def setup_logging(verbose: bool = False) -> logging.Logger:
    """配置日志记录器。"""
    logger = logging.getLogger("file_handler")
    logger.setLevel(logging.DEBUG if verbose else logging.INFO)
    
    handler = logging.StreamHandler(sys.stdout)
    formatter = logging.Formatter(
        "%(asctime)s - %(levelname)s - %(message)s",
        datefmt="%H:%M:%S"
    )
    handler.setFormatter(formatter)
    logger.addHandler(handler)
    
    return logger


def create_handler(base_path: Optional[str] = None, verbose: bool = False) -> FileHandler:
    """创建 FileHandler 实例。"""
    logger = setup_logging(verbose)
    return FileHandler(base_path=base_path or ".", logger=logger)


def cmd_rename(args: argparse.Namespace) -> int:
    """批量重命名命令。"""
    fh = create_handler(args.base_path, args.verbose)
    
    print(f"📁 目录: {args.directory}")
    print(f"🔍 模式: {args.pattern}")
    print(f"📝 替换为: {args.replacement}")
    print(f"🔄 递归: {'是' if args.recursive else '否'}")
    print(f"📂 包含目录: {'是' if args.include_dirs else '否'}")
    print(f"👁️  仅预览: {'是' if args.dry_run else '否'}")
    print("-" * 50)
    
    if args.recursive:
        result = fh.batch_rename_recursive(
            args.directory,
            args.pattern,
            args.replacement,
            use_regex=args.regex,
            include_dirs=args.include_dirs,
            dry_run=args.dry_run
        )
    else:
        result = {"renamed": [], "skipped": [], "errors": [], "count_renamed": 0, "count_skipped": 0, "count_errors": 0}
        count = fh.batch_rename(
            args.directory,
            args.pattern,
            args.replacement,
            use_regex=args.regex
        )
        result["count_renamed"] = count
    
    print(f"\n✅ 重命名: {result.get('count_renamed', 0)}")
    print(f"⏭️  跳过: {result.get('count_skipped', 0)}")
    print(f"❌ 错误: {result.get('count_errors', 0)}")
    
    if args.verbose and result.get("renamed"):
        print("\n📋 重命名列表:")
        for item in result["renamed"][:10]:  # 最多显示10个
            print(f"  {item['old_path']} -> {item['new_path']}")
        if len(result["renamed"]) > 10:
            print(f"  ... 还有 {len(result['renamed']) - 10} 个")
    
    return 0 if result.get("count_errors", 0) == 0 else 1


def cmd_list(args: argparse.Namespace) -> int:
    """列出文件命令。"""
    fh = create_handler(args.base_path, args.verbose)
    
    files = fh.list_files(args.directory, args.pattern)
    
    print(f"📁 目录: {args.directory}")
    print(f"🔍 模式: {args.pattern}")
    print(f"📄 找到 {len(files)} 个文件")
    print("-" * 50)
    
    for f in files:
        info = fh.get_file_info(f)
        size = info["size"]
        size_str = f"{size / 1024:.1f} KB" if size > 1024 else f"{size} B"
        print(f"  {info['name']} ({size_str})")
    
    return 0


def cmd_backup(args: argparse.Namespace) -> int:
    """备份文件命令。"""
    fh = create_handler(args.base_path, args.verbose)
    
    backup_path = fh.backup_file(args.file_path, args.backup_dir)
    print(f"✅ 备份完成: {backup_path}")
    
    return 0


def cmd_compress(args: argparse.Namespace) -> int:
    """压缩文件命令。"""
    fh = create_handler(args.base_path, args.verbose)
    
    files: list[str | Path] = [Path(f) for f in args.files]
    output = args.output or "archive.zip"
    
    success = fh.compress_files(files, output, args.format)
    
    if success:
        print(f"✅ 压缩完成: {output}")
        if Path(output).exists():
            size = Path(output).stat().st_size
            print(f"📦 大小: {size / 1024:.1f} KB")
    
    return 0 if success else 1


def cmd_extract(args: argparse.Namespace) -> int:
    """解压文件命令。"""
    fh = create_handler(args.base_path, args.verbose)
    
    success = fh.extract_archive(args.archive, args.output)
    
    if success:
        print(f"✅ 解压完成: {args.output}")
    
    return 0 if success else 1


def cmd_duplicates(args: argparse.Namespace) -> int:
    """查找重复文件命令。"""
    fh = create_handler(args.base_path, args.verbose)
    
    dups = fh.find_duplicate_files(args.directory)
    
    print(f"📁 目录: {args.directory}")
    print("-" * 50)
    
    if not dups:
        print("✅ 未发现重复文件")
        return 0
    
    total_dups = sum(len(files) - 1 for files in dups.values())
    print(f"🔍 发现 {len(dups)} 组重复文件，共 {total_dups} 个重复项\n")
    
    for key, files in dups.items():
        size, name = key.split("_", 1)
        print(f"📄 {name} ({int(size) / 1024:.1f} KB)")
        for f in files:
            print(f"   - {f}")
        print()
    
    return 0


def cmd_info(args: argparse.Namespace) -> int:
    """获取文件信息命令。"""
    fh = create_handler(args.base_path, args.verbose)
    
    info = fh.get_file_info(args.file_path)
    
    print(f"📄 文件: {info['name']}")
    print("-" * 50)
    
    size = info["size"]
    size_str = f"{size / 1024 / 1024:.2f} MB" if size > 1024 * 1024 else f"{size / 1024:.1f} KB"
    
    print(f"  类型: {'目录' if info['is_dir'] else '文件'}")
    print(f"  大小: {size_str} ({size} 字节)")
    print(f"  扩展名: {info['extension'] or '无'}")
    print(f"  绝对路径: {info['absolute_path']}")
    print(f"  创建时间: {info['created']}")
    print(f"  修改时间: {info['modified']}")
    
    return 0


def cmd_delete(args: argparse.Namespace) -> int:
    """删除文件命令。"""
    fh = create_handler(args.base_path, args.verbose)
    
    if not args.force:
        response = input(f"⚠️  确定要删除 {args.path} 吗? [y/N]: ")
        if response.lower() != 'y':
            print("❌ 操作已取消")
            return 1
    
    success = fh.delete_file(args.path)
    
    if success:
        print(f"✅ 已删除: {args.path}")
    
    return 0 if success else 1


def cmd_clean(args: argparse.Namespace) -> int:
    """清理空目录命令。"""
    fh = create_handler(args.base_path, args.verbose)
    
    if not args.force:
        response = input(f"⚠️  确定要清理 {args.directory} 中的空目录吗? [y/N]: ")
        if response.lower() != 'y':
            print("❌ 操作已取消")
            return 1
    
    count = fh.clean_empty_dirs(args.directory)
    print(f"✅ 已清理 {count} 个空目录")
    
    return 0


def interactive_mode():
    """交互式模式。"""
    print("📁 FileHandler 交互式模式")
    print("输入 'help' 查看帮助，'quit' 退出\n")
    
    fh = create_handler()
    
    while True:
        try:
            cmd = input("> ").strip()
            
            if not cmd:
                continue
            
            if cmd == 'quit':
                break
            
            if cmd == 'help':
                print("""
可用命令:
  ls <目录> [模式]     - 列出文件
  info <文件>          - 显示文件信息
  rm <文件>            - 删除文件
  mv <源> <目标>       - 移动文件
  cp <源> <目标>       - 复制文件
  backup <文件>        - 备份文件
  clean <目录>         - 清理空目录
  quit                 - 退出
                """)
                continue
            
            parts = cmd.split()
            action = parts[0]
            
            if action == 'ls' and len(parts) >= 2:
                directory = parts[1]
                pattern = parts[2] if len(parts) > 2 else "*"
                files = fh.list_files(directory, pattern)
                for f in files[:20]:
                    print(f"  {f.name}")
                if len(files) > 20:
                    print(f"  ... 还有 {len(files) - 20} 个文件")
            
            elif action == 'info' and len(parts) >= 2:
                info = fh.get_file_info(parts[1])
                for k, v in info.items():
                    print(f"  {k}: {v}")
            
            elif action == 'rm' and len(parts) >= 2:
                fh.delete_file(parts[1])
                print(f"✅ 已删除")
            
            elif action == 'mv' and len(parts) >= 3:
                fh.move_file(parts[1], parts[2])
                print(f"✅ 已移动")
            
            elif action == 'cp' and len(parts) >= 3:
                fh.copy_file(parts[1], parts[2])
                print(f"✅ 已复制")
            
            elif action == 'backup' and len(parts) >= 2:
                path = fh.backup_file(parts[1])
                print(f"✅ 已备份到: {path}")
            
            elif action == 'clean' and len(parts) >= 2:
                count = fh.clean_empty_dirs(parts[1])
                print(f"✅ 清理了 {count} 个空目录")
            
            else:
                print("❌ 未知命令或参数不足，输入 'help' 查看帮助")
        
        except KeyboardInterrupt:
            print("\n使用 'quit' 退出")
        except Exception as e:
            print(f"❌ 错误: {e}")


def main():
    """主函数。"""
    parser = argparse.ArgumentParser(
        prog='file_handler_use.py',
        description='文件处理器 CLI 工具',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  %(prog)s rename ./mydir "old" "new" --recursive --dry-run
  %(prog)s list ./mydir --pattern "*.txt"
  %(prog)s backup ./important.txt --backup-dir ./backups
  %(prog)s compress file1.txt file2.txt --output archive.zip
  %(prog)s duplicates ./downloads
  %(prog)s interactive
        """
    )
    
    parser.add_argument('-v', '--verbose', action='store_true', help='显示详细日志')
    parser.add_argument('-b', '--base-path', default='.', help='基础路径 (默认: 当前目录)')
    
    subparsers = parser.add_subparsers(dest='command', help='可用命令')
    
    # rename 命令
    rename_parser = subparsers.add_parser('rename', help='批量重命名文件')
    rename_parser.add_argument('directory', help='目标目录')
    rename_parser.add_argument('pattern', help='要查找的模式')
    rename_parser.add_argument('replacement', help='替换为')
    rename_parser.add_argument('-r', '--recursive', action='store_true', help='递归处理子目录')
    rename_parser.add_argument('-d', '--include-dirs', action='store_true', help='同时重命名目录')
    rename_parser.add_argument('--regex', action='store_true', help='使用正则表达式')
    rename_parser.add_argument('-n', '--dry-run', action='store_true', help='仅预览，不实际修改')
    rename_parser.set_defaults(func=cmd_rename)
    
    # list 命令
    list_parser = subparsers.add_parser('list', help='列出目录中的文件')
    list_parser.add_argument('directory', help='目标目录')
    list_parser.add_argument('-p', '--pattern', default='*', help='文件匹配模式 (默认: *)')
    list_parser.set_defaults(func=cmd_list)
    
    # backup 命令
    backup_parser = subparsers.add_parser('backup', help='备份文件')
    backup_parser.add_argument('file_path', help='要备份的文件')
    backup_parser.add_argument('-d', '--backup-dir', help='备份目录')
    backup_parser.set_defaults(func=cmd_backup)
    
    # compress 命令
    compress_parser = subparsers.add_parser('compress', help='压缩文件')
    compress_parser.add_argument('files', nargs='+', help='要压缩的文件')
    compress_parser.add_argument('-o', '--output', help='输出文件名')
    compress_parser.add_argument('-f', '--format', default='zip', choices=['zip', 'tar', 'gztar'], help='压缩格式')
    compress_parser.set_defaults(func=cmd_compress)
    
    # extract 命令
    extract_parser = subparsers.add_parser('extract', help='解压文件')
    extract_parser.add_argument('archive', help='压缩文件')
    extract_parser.add_argument('-o', '--output', default='.', help='解压目录')
    extract_parser.set_defaults(func=cmd_extract)
    
    # duplicates 命令
    dup_parser = subparsers.add_parser('duplicates', help='查找重复文件')
    dup_parser.add_argument('directory', help='要扫描的目录')
    dup_parser.set_defaults(func=cmd_duplicates)
    
    # info 命令
    info_parser = subparsers.add_parser('info', help='获取文件信息')
    info_parser.add_argument('file_path', help='文件路径')
    info_parser.set_defaults(func=cmd_info)
    
    # delete 命令
    delete_parser = subparsers.add_parser('delete', help='删除文件')
    delete_parser.add_argument('path', help='要删除的文件或目录')
    delete_parser.add_argument('-f', '--force', action='store_true', help='强制删除，不确认')
    delete_parser.set_defaults(func=cmd_delete)
    
    # clean 命令
    clean_parser = subparsers.add_parser('clean', help='清理空目录')
    clean_parser.add_argument('directory', help='目标目录')
    clean_parser.add_argument('-f', '--force', action='store_true', help='强制清理，不确认')
    clean_parser.set_defaults(func=cmd_clean)
    
    # interactive 命令
    interactive_parser = subparsers.add_parser('interactive', help='进入交互式模式')
    
    args = parser.parse_args()
    
    if args.command == 'interactive':
        interactive_mode()
        return 0
    
    if args.command is None:
        parser.print_help()
        return 0
    
    try:
        return args.func(args)
    except FileNotFoundError as e:
        print(f"❌ 文件不存在: {e}")
        return 1
    except FileExistsError as e:
        print(f"❌ 文件已存在: {e}")
        return 1
    except Exception as e:
        print(f"❌ 错误: {e}")
        if args.verbose:
            import traceback
            traceback.print_exc()
        return 1


if __name__ == "__main__":
    sys.exit(main())
