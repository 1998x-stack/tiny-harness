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
| Phase 2 | [#14](https://github.com/1998x-stack/tiny-harness/pull/14) | ToolDef 风险等级默认 mutation；拒绝未知等级；safe 路径仍受检查；无 HITL Shell 显式 opt-in | PR CI 通过 |
| Phase 3 | [#15](https://github.com/1998x-stack/tiny-harness/pull/15) | context_window 输入预算、历史工具结果压缩、完整轮次淘汰、超限时拒绝 LLM 请求 | PR CI 通过；估算值非精确 tokenizer |
| Phase 1 | [#16](https://github.com/1998x-stack/tiny-harness/pull/16) | Anthropic SSE 截断检测、message_stop 校验、usage/finish、可配置网关 | PR CI 通过；真实 API 冒烟仍待执行 |
| Phase 2 | [#18](https://github.com/1998x-stack/tiny-harness/pull/18) | ToolOutcome 显式成功/失败契约，文件、搜索、Shell 异常传给 ErrorBudget | PR CI 通过；低层直接调用保留字符串兼容 |
| Phase 1 | [#19](https://github.com/1998x-stack/tiny-harness/pull/19) | OpenAI/Anthropic 流式请求在首次输出前重试 429/5xx/部分网络错误，Retry-After 上限；输出后禁重试 | PR CI 通过；真实 API 冒烟仍待执行 |
| Phase 4 | [#21](https://github.com/1998x-stack/tiny-harness/pull/21) | ToolDef 显式 path_args、所有声明路径规范化、第三方兼容字段全部检查 | PR CI 通过；仍非 OS 沙箱 |
| Phase 4 | [#22](https://github.com/1998x-stack/tiny-harness/pull/22) | Draft 2020-12 JSON Schema（嵌套/组合/数组），注册时检查 Schema，拒绝远程引用 | PR CI 通过；引入 jsonschema 运行时依赖 |
| Phase 5 | [#24](https://github.com/1998x-stack/tiny-harness/pull/24) | Linux Bubblewrap 可选 shell namespace + workspace-only bind, 缺失时 fail-closed | Python CI 通过，实际 namespace smoke 最初被跳过 |
| Phase 5 | [#25](https://github.com/1998x-stack/tiny-harness/pull/25) | prlimit CPU/虚拟内存/单文件大小逐进程资源约束 | Python CI 通过，非 cgroup 总配额 |
| Phase 6 | [#27](https://github.com/1998x-stack/tiny-harness/pull/27) | OCI/Docker 可选后端，固定镜像摘要、只读根、network=none、cgroup CPU/内存/PID 限制及容器回收 | GitHub Runner 实际 Docker 隔离、cgroup、超时/取消清理测试通过 |

## 待完成事项（不应标记为已修复）

### P1：继续按独立 PR 完成

1. **OS 沙箱验证及增强**：已实现可选 Linux Bubblewrap 与 OCI Docker 后端；Docker 的 cgroup 限制及实际网络/工作区隔离已在 GitHub Linux runner 通过。仍需独立宿主环境的恶意负载评估、seccomp/AppArmor/SELinux 强化、daemon 隔离、竞态修复和其他平台后端。默认 off 仍是不隔离的 Shell，**不能**据 CI 单环境验证声称完整生产级沙箱。
2. **ToolDef 参数级策略**：基础风险枚举与 no-HITL Shell 显式 opt-in 已完成；后续引入细粒度 allow/ask/deny、按命令参数审批策略，扩展其他危险工具的无 HITL 拒绝边界。
3. **Provider 全面契约**：Anthropic 自定义 endpoint、截断判断和首次输出前的有限流式重试已完成；仍需统一非流式/流式重试、DeepSeek thinking 透传、HTTP 客户端连接复用及真实 API 冒烟。
4. **上下文窗口**：已提供可配置窗口与启发式压缩；仍需 provider 真实 usage 回收、tokenizer 精确统计、可审计摘要和更精细的窗口分层治理。
5. **ToolResult 失败语义**：内置 File/Search/Shell 的结构化失败状态已接入 ErrorBudget；后续要求新工具优先返回 `ToolOutcome`，逐步覆盖非结构化第三方 handler 和完整日志/事件成功率指标。

### P2：持续质量提升

- 文件工具：有界读取、二进制识别、原子写、拒绝默认覆盖与 edit_file。
- ToolRegistry：JSON Schema 与显式 path 参数契约已落地；进一步清理过渡期遗留工具名称兼容映射，完善工具能力策略与插件迁移。
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
