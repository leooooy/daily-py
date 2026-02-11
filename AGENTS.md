# AGENTS.md

本文件包含在此代码库中工作的智能编码代理的指南。

## 开发命令

### 基本命令
```bash
# 安装依赖
# 命令因语言而异：
# Node.js: npm install
# Python: pip install -r requirements.txt
# Rust: cargo build
# Go: go mod tidy

# 运行应用程序
npm run dev          # Node.js
python main.py       # Python
cargo run            # Rust
go run main.go       # Go

# 生产环境构建
npm run build        # Node.js
python -m build      # Python
cargo build --release # Rust
go build             # Go
```

### 测试命令
```bash
# 运行所有测试
npm test             # Node.js
pytest               # Python
cargo test           # Rust
go test ./...        # Go

# 运行单个测试文件
npm test -- path/to/test.js
pytest path/to/test.py
cargo test test_name
go test ./path/to/package

# 监听模式运行测试
npm test -- --watch
pytest --watch
cargo watch -x test
```

### 代码检查和格式化
```bash
# 代码检查
npm run lint         # Node.js
flake8 .             # Python
cargo clippy         # Rust
golangci-lint run    # Go

# 格式化代码
npm run format       # Node.js
black .              # Python
rustfmt .            # Rust
gofmt .              # Go

# 类型检查
npm run typecheck    # Node.js
mypy .               # Python
cargo check          # Rust
go vet ./...         # Go
```

## 代码风格指南

### 导入组织
- 按类型分组导入：外部库、内部模块、相对导入
- 使用语言的一致导入语法
- 移除未使用的导入
- 优先选择特定导入而不是通配符导入

### 格式化和风格
- 遵循语言的标准格式化约定
- 使用一致的缩进（大多数语言2个空格，Python4个空格）
- 保持一致的行长度（通常80-120个字符）
- 使用有意义的变量和函数名

### 类型安全
- 在可用时使用类型注解
- 优先选择显式类型而不是隐式类型推断
- 优雅地处理类型错误
- 使用接口或协议作为契约

### 命名约定
- 变量和函数使用camelCase（JavaScript、Go、Rust）
- 类和类型使用PascalCase
- Python变量和函数使用snake_case
- 常量使用UPPER_SNAKE_CASE
- 具有描述性，避免缩写

### 错误处理
- 明确而优雅地处理错误
- 提供有意义的错误消息
- 使用特定语言的错误处理模式
- 适当记录错误以供调试
- 对关键错误快速失败

### 代码组织
- 遵循单一职责原则
- 保持函数小而专注
- 使用一致的目录结构
- 分离关注点（UI、逻辑、数据）
- 适当使用模块/包

### 文档
- 编写清晰简洁的注释
- 记录公共API和接口
- 为函数和类使用文档字符串
- 在文档中包含示例
- 保持文档最新

### 性能考虑
- 避免过早优化
- 在优化前进行性能分析
- 使用适当的数据结构
- 考虑内存使用
- 优化关键路径

### 安全最佳实践
- 永远不要提交密钥或API密钥
- 验证所有输入
- 使用安全的默认值
- 遵循特定语言的安全指南
- 保持依赖项更新

## 测试指南

### 测试结构
- 编写描述性的测试名称
- 使用AAA模式（Arrange、Act、Assert）
- 测试边界条件和错误情况
- 保持测试独立和确定性
- 模拟外部依赖

### 测试覆盖率
- 力求高代码覆盖率
- 专注于关键路径
- 测试公共接口
- 包括集成测试
- 测试错误处理路径

## Git工作流

### 提交消息
- 使用约定式提交格式（可选）
- 描述性但简洁
- 适用时引用问题编号
- 用空行分隔主题和正文

### 分支管理
- 为新工作使用功能分支
- 保持主分支稳定
- 使用描述性分支名称
- 清理已合并的分支

## 工具特定指南

### IDE/编辑器配置
- 配置一致的格式化设置
- 使用语言服务器获得更好的IDE支持
- 设置调试配置
- 为常见模式配置代码片段

### 构建工具
- 为语言使用适当的构建工具
- 配置高效的开发构建
- 优化生产构建
- 设置持续集成

## 自定义项目规则

*此部分应根据在以下位置找到的项目特定规则和约定进行自定义：*
- `.cursor/rules/` 目录
- `.cursorrules` 文件
- `.github/copilot-instructions.md` 文件
- 任何现有项目文档

## 入门检查清单

在此代码库中工作时：
1. [ ] 安装依赖项
2. [ ] 运行代码检查和格式化
3. [ ] 运行现有测试
4. [ ] 遵循代码风格指南
5. [ ] 为新代码编写测试
6. [ ] 根据需要更新文档

记住：目标是编写遵循既定模式和约定的干净、可维护的代码。