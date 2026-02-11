# DailyPy - 日常Python工具

一个用于日常文件和数据处理的实用工具库。

## 功能特性

- 文件处理：删除、重命名、移动、复制等常用操作
- 错误处理：完善的异常处理机制
- 类型安全：完整的类型注解支持

## 安装

```bash
pip install -e .
```

## 使用示例

```python
from daily_py import FileHandler

# 创建文件处理器
handler = FileHandler()

# 删除文件
handler.delete_file("path/to/file.txt")

# 重命名文件
handler.rename_file("old_name.txt", "new_name.txt")
```

## 开发

```bash
# 安装开发依赖
pip install -e ".[dev]"

# 运行测试
pytest

# 代码格式化
black .
isort .

# 类型检查
mypy .
```

## 许可证

MIT License