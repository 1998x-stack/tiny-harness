# Security model / 安全边界

tiny-harness 是可执行工具的 Agent harness，**不是安全沙箱**。模型输出、外部文档内容、工具输出都应视为非可信输入。

## 已有保护（截至 2026-10-28）

- `search_content` 使用 `rg -e PATTERN -- PATH`，并由执行器校验工作区路径；regex 不再被当作命令行选项。
- 文件工具的常规路径受 `FilesystemGuard` canonicalization 与 workspace 边界检查；并非 race-free 的操作系统隔离。
- HITL 默认审核 mutation/destructive/dangerous；destructive/dangerous 不可使用会话级永久批准。回调异常按拒绝处理。
- built-in Shell skill 的 async handler 运行于指定 cwd；POSIX 上超时/取消时终止进程组；不继承 `*_API_KEY` 等未在 allow-list 的环境变量。
- 会话快照使用原子替换与受限文件权限（POSIX `0600`）。

## 未提供的隔离能力

- **Shell 没有操作系统级文件系统隔离**：即使 cwd 在 workspace，命令仍可能访问机器上任何该进程有权限访问的路径；`--no-hitl` 使模型可以无需审批执行 Shell。
- Shell 可能访问网络、用户凭据文件、Git 配置及 SSH agent；环境变量白名单不能覆盖全部隐式凭据路径。
- 历史同步 `run_command` 辅助函数保留用于兼容，并未获得与 registered async Shell 等价的进程组取消保障。
- Path guard 的检查和 handler 的实际打开文件不是一个不可分割的 OS 操作；工作区内容可被外部进程并发替换时仍有 TOCTOU 风险。
- 在 Windows 上，异步 handler 的 `process.kill()` 不提供 POSIX 进程组等价的孙进程终止保障。

## 部署建议

仅对可信工作目录开启工具；不要把 Shell skill 暴露给不可信用户或远程多租户。生产部署应使用用户隔离的容器或沙箱、只读挂载、网络限制、资源配额和单独的工作凭据。真正的默认安全策略应在操作系统/工具执行器层强制，而不是依赖 Skill Prompt 中的禁止语句。

涉及新的 Shell 能力、第三方 Tool 或新的路径参数时，必须补充对抗性回归测试，再允许进入 `main`。
