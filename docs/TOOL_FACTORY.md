# Tool Factory Contract / 工具定义与执行契约

工具不是可信任的函数调用。模型输出、工具参数、Skill 文本以及外部内容都应被视作不可信输入。

## 1. 工具注册

以下示例展示如何为插件定义类型、文件路径和失败语义：

```python
from tiny_harness import ToolDef
from tiny_harness._tool_outcome import ToolOutcome

def inspect_manifest(args: dict) -> ToolOutcome:
    # args["manifest_path"] 已由 ToolExecutor 规范化为 workspace 内绝对路径。
    with open(args["manifest_path"], encoding="utf-8") as f:
        return ToolOutcome.ok(f.read())

agent.tools.register_from_def(
    ToolDef(
        name="inspect_manifest",
        description="Read a manifest from this agent's workspace",
        risk_level="read_only",
        path_args=("manifest_path",),
        parameters={
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "manifest_path": {"type": "string", "minLength": 1},
            },
            "required": ["manifest_path"],
        },
    ),
    inspect_manifest,
)
```

`path_args` 用于声明路径语义，不限制字段名称为 `path`。多个位置必须全部列出，例如 `("source", "destination")`。每个声明字段必须是参数 Schema 中的字符串属性。旧插件的 `path/source/destination/cwd` 习惯字段仍进行兼容性检查；新代码不要依赖工具名称白名单。

## 2. JSON Schema（Draft 2020-12）

- ToolDef 创建时验证 Schema 是否合法，并要求根 Schema 表示对象。
- ToolExecutor 执行前使用标准 JSON Schema 校验：嵌套对象、数组元素、`required`、`additionalProperties`、`minLength`、范围、枚举、`oneOf` 等均生效。
- 用户审批处理函数若返回修改后的参数，会重新执行 Schema 与路径守卫。
- 支持同一 Schema 内的 `#/$defs/...` 引用；拒绝外部 URL 引用，避免执行过程中隐式获取不可信远程 Schema。
- 不会自动类型转换：`"42"` 不等于整数 `42`，布尔值不当作整数。

## 3. 风险分类与结果

| 风险等级 | 默认行为 |
|---|---|
| `safe`、`read_only` | 通常无需 HITL，但路径守卫仍生效 |
| `mutation` | 需要 HITL |
| `destructive`、`dangerous` | 每次都需要 HITL，不保留会话级批准 |
| 未指定 | 默认 `mutation` |
| 非法/未知等级 | 注册即失败 |

返回 `ToolOutcome.ok(text)` / `ToolOutcome.error(text)`，让错误预算可靠区分成功与失败。现有直接返回字符串的 handler 依旧兼容，但 **字符串内容不用于推断执行成功与否**。详见 [TOOL_OUTCOME.md](TOOL_OUTCOME.md)。

## 4. 不提供的安全保证

`FilesystemGuard` 通过规范化路径阻止显式的工作区外路径；**这不是 OS 沙箱**：不能阻止工具直接访问其他系统资源、TOCTOU 符号链接竞态，也不能限制任意 Shell 的网络/文件系统访问。部署于多租户或不可信环境时，必须另配进程、文件系统和网络隔离。

## 5. Regression checklist

- 参数缺少必需字段、数组/嵌套类型不符，handler 完全不执行。
- 受保护路径的相对值按 `AgentConfig.workspace` 解释，不能按调用 Python 进程的当前工作目录解释。
- 任意多路径中只要有一个越界，整个工具调用即失败。
- HITL 修改过的参数重新校验，不允许绕过风险和路径守卫。
- 任何新工具注册时应具备明确风险分类、Schema、`path_args`（如涉及路径）及成功/失败结果契约。
