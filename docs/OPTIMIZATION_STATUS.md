# tiny-harness 分阶段优化执行记录

> 审查基线：`master@19cbcc7`（2026-09-21）
> 执行分支：`main`；使用独立 feature branch + PR + GitHub Actions（Python 3.11–3.13）后合并。
> 状态更新时间：2026-10-28。

## 已验证并合并

| 阶段 | PR | 实施内容 | 验证 |
|---|---|---|---|
| Phase 0 | [#2](https://github.com/1998x-stack/tiny-harness/pull/2) | ripgrep 参数隔离、搜索路径工作区约束、建立测试 CI | PR CI 通过 |
| Phase 0 | [#3](https://github.com/1998x-stack/tiny-harness/pull/3) | 动态 Skill system prompt 同步 | PR CI 通过 |
| Phase 0 | [#4](https://github.com/1998x-stack/tiny-harness/pull/4) | Provider endpoint/key-env 正确路由、密钥 repr 脱敏 | PR CI 通过 |
| Phase 0 | [#5](https://github.com/1998x-stack/tiny-harness/pull/5) | HITL 高危操作逐次审批、clear 清除授权 | PR CI 通过 |
| Phase 0 | [#6](https://github.com/1998x-stack/tiny-harness/pull/6) | 工具/审批异常 fail-closed，transcript 工具结果补齐 | PR CI 通过 |
| Phase 0 | [#7](https://github.com/1998x-stack/tiny-harness/pull/7) | Shell cwd 绑定 AgentConfig.workspace | PR CI 通过 |
| Phase 1 | [#8](https://github.com/1998x-stack/tiny-harness/pull/8) | Anthropic 消息转换与 SSE 工具调用组装 | PR CI 通过，未进行真实 API 冒烟 |
| Phase 3 | [#9](https://github.com/1998x-stack/tiny-harness/pull/9) | run_stream 取消子任务、订阅回收、保存最终答案 | PR CI 通过 |
| Phase 1 | [#10](https://github.com/1998x-stack/tiny-harness/pull/10) | OpenAI 流式 JSON/usage/finish 边界与截断保护 | PR CI 通过，未进行真实 API 冒烟 |
| Phase 2 | [#11](https://github.com/1998x-stack/tiny-harness/pull/11) | Shell 异步进程组终止、输出上限、环境变量最小化 | PR CI 通过，POSIX 专项测试 |
| Phase 3 | [#12](https://github.com/1998x-stack/tiny-harness/pull/12) | Session 幂等原子保存、工具 ID/结果往返、0600 | PR CI 通过 |

## 待完成事项（不应标记为已修复）

### P1：继续按独立 PR 完成

1. **真正的执行沙箱**：Shell 的 cwd、HITL 和环境过滤均不是 filesystem/network sandbox。评估 Linux bubblewrap/container；对 Windows/macOS 另定明确边界。**禁止**宣传当前 Shell 已沙箱化。
2. **ToolDef 风险声明及策略**：拒绝未知 risk level，默认 fail-closed；用结构化策略管理 read/mutation/dangerous；`--no-hitl` + Shell 需额外明确选择。
3. **Provider 全面契约**：流式重试（仅首输出前）、`Retry-After`、Anthropic 可配置 endpoint、DeepSeek thinking 透传、真实 API 冒烟。
4. **上下文窗口**：可配置 context_window、usage 回收、OVER_CAPACITY 明确响应与历史压缩。
5. **ToolResult 失败语义**：内部 handler 返回 `Error: ...` 时不应无条件标记成功；改用结构化失败而非文本启发式。

### P2：持续质量提升

- 文件工具：有界读取、二进制识别、原子写、拒绝默认覆盖与 edit_file。
- ToolRegistry：完整 JSON Schema 与 path 参数契约；消除静态白名单。
- EventBus：事件成功状态、耗时与稳定的 finish/usage 契约。
- 错误预算与循环检测：区分失败重复与成功的合法重复，避免错误的长期封禁。
- Session：旧格式兼容迁移、增量写入、CLI `/resume`、大结果 sidecar 与索引。
- 工程质量：ruff、mypy、coverage、README 与 USER-GUIDE 一致性、独立的性能基准。

## 合并门禁

- 每个修复分支必须写至少一个对准故障的回归测试。
- GitHub Actions 3.11、3.12、3.13 必须全部通过；涉 Provider 的真实 API 测试另标记 `integration`。
- 不在模型输出截断时执行不完整工具参数；审批异常必须 fail-closed；每个 tool_call 对应恰好一个 tool result。
- 合并前确认 PR base = `main`，合并后确认 `main` HEAD 已更新。
- 保留 `master` 作为旧仓库默认分支时，需显式快进同步以免默认克隆旧版本；后续可在 GitHub 仓库设置中切换默认分支为 `main`。
