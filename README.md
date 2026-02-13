# DailyPy 文件批量重命名工具使用指南

本文档总结了在 IntelliJ IDEA / PyCharm 环境中，以不同方式快速、方便地进行批量重命名操作的方案，以及已实现的具体实现。可以直接复制粘贴命令，也可以通过图形界面、右键工具和外部工具集成来使用。

目录
- 方案总览
- 方案 A：直接以模块运行（最稳妥）
- 方案 B：IDEA 外部工具（External Tools）
- 方案 C：快速图形界面（Tkinter）
- 方案 D：批处理脚本（右键/桌面快捷）
- 安装与运行要点
- 快速对比

方案总览
- 方案 A: 直接以模块运行 daily_py.file_handler_use，命令形式最稳定，路径问题最少。
- 方案 B: 通过 External Tools 调用一个 Launcher 脚本，方便在右键菜单中快速执行。
- 方案 C: Tkinter GUI，拖放/填参数，一键执行，适合不想写命令行的人。
- 方案 D: Windows 批处理脚本，方便拖拽或右键调用，适合简单工作流。

方案 A：直接以模块运行（推荐在 IDEA 里使用）
命令示例（复制粘贴即可）：
```
python -m daily_py.file_handler_use rename "D:\ftp\260128putput" "26" "99" -r --include-dirs --dry-run
```
实际执行时移除 --dry-run 即可。

在 IDEA / PyCharm 中的配置要点：
- Run/Debug Configurations → + → Python Module 或 Python → Module name: daily_py.file_handler_use
- Parameters: 你需要的参数，例如上述命令中的部分
- Working directory: 项目根目录，例如 D:\JAVA\pythonProject\DailyPy
- 这样你就可以直接点击 Run 来执行了。

方案 B：External Tools（右键/工具栏快速执行）
实现要点：通过一个 Launcher 脚本调用批量重命名。
- Launcher 脚本：tools/rename_ext_launcher.py
- 你可以在 External Tools 中配置 Program 为 python，Arguments 为
  tools/rename_ext_launcher.py <dir> <pattern> <replacement> [--recursive] [--include-dirs] [--regex] [--dry-run]
- 也可以使用 $Prompt$ 让 IDE 弹出输入框，填写参数后执行。
- 我也实现了一个简易 GUI 版本的外部工具入口，方便一键执行。

方案 C：快速图形界面（Tkinter）
GUI 文件： daily_py/ui/rename_gui.py
- 启动方式（IDEA 直接运行模块也可）：python -m daily_py.ui.rename_gui
- GUI 提供字段：目标目录、模式、替换文本、递归、正则、包含目录、dry-run
- 运行后在下方输出区域显示执行结果。
- 也提供了一个批处理启动器：tools/rename_gui.bat

方案 D：批处理快速入口
- Windows 下的批处理包装：tools/rename_batch.bat
- 直接粘贴命令即可快速执行（可改为固定参数的快捷版）
- 以及一个简单的 GUI 启动器：tools/rename_gui.bat

- 备注: 路径包含空格时请确保使用引号包裹。
- 如需，我可以把以上方案整合成一个统一的最小化入口来替代重复的命令。

后续步骤
- 你可以告诉我你偏好的入口（IDEA 方案、External Tools 方案、GUI 方案），我再进一步精炼具体的配置和示例。
- 需要我把 README 也同步到各分支、或把配置示例做成一个模板吗？

---
End of README
