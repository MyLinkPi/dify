# 计划：在调用自定义工具时在请求头附加 conversation_id

## 目标

当 Dify 调用自定义工具（ApiTool）时，在 HTTP 请求头中附加 `X-Conversation-Id` 头，使外部工具服务可以获取到会话 ID 上下文。

## 背景分析

### 当前调用链

```
ToolEngine.agent_invoke / generic_invoke
  → Tool.invoke(conversation_id=...)
    → ApiTool._invoke(conversation_id=...)
      → assembling_request(tool_parameters) → headers  # ← 不接收 conversation_id
      → do_http_request(url, method, headers, tool_parameters)
        → ssrf_proxy.make_request(headers=headers)
```

### 关键发现

1. `conversation_id` 已经通过 `ToolEngine` → `Tool.invoke()` → `ApiTool._invoke()` 传递下来，但 `_invoke()` 中没有将其添加到请求头。
2. `assembling_request()` 方法只接收 `parameters` 参数，不接收 `conversation_id`。
3. `do_http_request()` 方法也不接收 `conversation_id`。
4. 最简洁的修改点是在 `ApiTool._invoke()` 中，在调用 `assembling_request()` 获取 headers 后，将 `conversation_id` 注入到 headers 中。

## 实现步骤

### 步骤 1：修改 `ApiTool._invoke()` 方法

**文件**: `api/core/tools/custom_tool/tool.py`

在 `_invoke()` 方法中，获取 headers 后、调用 `do_http_request()` 前，将 `conversation_id` 添加到请求头：

```python
def _invoke(self, user_id, tool_parameters, conversation_id=None, app_id=None, message_id=None):
    headers = self.assembling_request(tool_parameters)
    # 新增：将 conversation_id 附加到请求头
    if conversation_id:
        headers["X-Conversation-Id"] = conversation_id
    response = self.do_http_request(...)
    ...
```

选择在 `_invoke()` 中直接添加而非修改 `assembling_request()` 的签名，原因：
- `assembling_request()` 是公开方法，被 `validate_credentials()` 等其他地方调用，修改签名影响范围大
- `conversation_id` 不是认证信息，不应放在 `assembling_request()` 中
- 在 `_invoke()` 中添加最符合单一职责原则，影响最小

### 步骤 2：编写单元测试

**文件**: `api/tests/unit_tests/core/tools/test_custom_tool.py`

在现有测试文件中添加测试用例，验证：
1. 当 `conversation_id` 不为 None 时，请求头中包含 `X-Conversation-Id`
2. 当 `conversation_id` 为 None 时，请求头中不包含 `X-Conversation-Id`
3. 完整的 `_invoke` 流程中 `conversation_id` 被正确传递到 HTTP 请求

### 步骤 3：运行测试验证

运行相关单元测试确保修改正确且无回归。

### 步骤 4：记录修改

在 `trae_history_xufan.md` 中记录本次修改。

## 影响范围

- **修改文件**: `api/core/tools/custom_tool/tool.py`（仅 `_invoke` 方法，约 2 行代码）
- **新增测试**: `api/tests/unit_tests/core/tools/test_custom_tool.py`
- **无破坏性变更**: `conversation_id` 参数已是可选的，仅在非 None 时添加请求头
- **不影响其他工具类型**: MCPTool、BuiltinTool、WorkflowTool 等不受影响
