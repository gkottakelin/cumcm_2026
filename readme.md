# 1. 项目信息

## 1.1 项目主要结构

- `data/`：原始数据存放目录。
- `figure/`：外部图片存放目录。
- `mk/vars.mk`：部分 Make 变量定义文件。
- `python-code/`：Python 代码存放目录。
- `python-code/main.py`：Python 代码的执行入口文件。
- `out/`：构建目录。
- `tex/`：LaTeX 论文章节文件存放目录。
- `tex/main.tex`：LaTeX 论文的主文件。

## 1.2 Make 命令

- `make`/`make all`：完成所有构建任务。
- `make artifacts`：运行代码并保存结果。
- `make clean`：清理目录。
- `make fix`: 运行自动修复。
- `make fix-*`: 运行某一自动修复项目。
- `make test`: 运行所有测试项目。
- `make test-*`: 运行某一测试项目。

## 1.3 待修改的 Make 变量（`mk/vars.mk`）

- `ARTIFACTS`：代码产物路径列表，**必须**根据代码实际产物修改。
- `FINAL_NAME`：编译出的论文的文件名，**必须**按照相关要求修改。

# 2. Contributing Guide

## 2.1 Git Repository

- 2.1.1 工作流：[Github Flow](https://githubflow.github.io/)。
- 2.1.2 Commit 规范：[Conventional Commits](https://www.conventionalcommits.org/zh-hans/)。
- 2.1.3 分支命名风格：[Gitflow](https://git-flow.sh/workflows/gitflow/)。
- 2.1.4 构建系统：[GNU Make](https://www.gnu.org/software/make/)。
- 2.1.5 主分支名：master。
- 2.1.6 自动测试 & 构建：[阿里云云效](https://flow.aliyun.com/)，运行成功后，可以在 Artifacts 中下载 `out/` 目录的内容。
- 2.1.7 手动测试 & 构建：`make && make test`。
- 2.1.8 所有任务由仓库管理员通过创建 Issue 进行分配，并指定负责人。
- 2.1.9 Issue 对应的负责人开始任务后**应**把对应 Issue 的状态改为"进行中"。
- 2.1.10 Commit 信息**必须**包括 AI 使用情况，格式为`模型 (使用环境）`，例如 `Assisted by Claude Fable 5 (Claude Code)`，`Assisted by Gemini 3.1 Pro Preview (Web)`。
- 2.1.11 提交 Pull Request 前：
  - **必须**通过阿里云云效。
  - 分支**禁止**落后于 master 分支。
- 2.1.12 若 Pull Request 旨在解决特定 Issue，**必须**在说明的首行写 `Close #<Issue 编号>`。
- 2.1.13 提交 Pull Request 后**建议**在评论中发布关键结果的截图，帮助审查者快速理解变更。
- 2.1.14 在 Gitee 完成需要他人响应的操作后**建议**在团队群中 @ 相关成员，便于相关成员及时查看。
- 2.1.15 引入 Github Star < 1k 的依赖，**必须**提前讨论。
- 2.1.16 修改以下文件之外的文件**必须**提前讨论：
  - `mk/vars.mk`
  - `python-code/*`
  - `tex/*`
  - `pyproject.toml`
  - `reference.bib`
  - `uv.lock`

## 2.2 Python

- 2.2.1 生成图片时，**建议**使用 PDF 格式的矢量图。
- 2.2.2 生成表格时，**建议**使用 CSV 或 Markdown 格式。
- 2.2.3 对于图片形式的结果，**建议**同时生成一份内容等价的文字型结果，便于 AI 辅助写作。

## 2.3 LaTeX

- 2.3.1 项目中使用的所有库或软件，若其提供 BibTeX 引用格式，都**必须**在论文中引用。
- 2.3.2 参考文献选择标准：
  - **建议**选择 [Web of Science](https://mjl.clarivate.com/home) 中 SCIE，SSCI 与 AHCI 数据库里的文献。
  - 引用数**建议**：发表2年内的文献引用数 >= 10，发表2年以上的文献引用数 >= 100。
  - 如需引用不符合以上要求的文献，**必须**提前讨论。
