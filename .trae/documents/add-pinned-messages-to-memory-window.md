# 计划：为 MemoryConfig 窗口配置增加"保留最初 M 条消息"功能

## 需求概述

在现有窗口配置（保留最近 N 条消息）基础上，增加"保留最初 M 条消息"（pinned_size）配置：

* 窗口启用时，上下文 = 最早 M 条消息 + 最近 N 条消息
* M（pinned_size）默认 10，N（window.size）沿用前端现有默认值 50
* M + N 重叠时（总消息数 ≤ M+N）按消息 id 去重，等价于保留全部消息

## 现状调研结论（关键事实，原计划的错误根源）

1. **`MemoryConfig` / `WindowConfig` 定义在第三方包 `graphon`（pyproject 中 `graphon~=0.2.2`）中，不能直接修改**。
   `api/core/prompt/entities/advanced_prompt_entities.py` 只是 re-export。

2. **graphon 的 `MemoryConfig.WindowConfig` 未设置 `extra="allow"`，pydantic 默认 ignore**。
   已实测：前端传来的 `window.pinned_size` 在 graphon 校验 `LLMNodeData` 时会被**静默丢弃**。
   因此不能依赖 `node_data.memory.window.pinned_size`，必须从**校验前的原始节点数据**中提取。
   好消息：graphon 的 `BaseNodeData` 设置了 `extra="allow"`，`NodeConfigDictAdapter` 第一次校验时
   整个 `memory` dict 会作为 extra 保留在 `BaseNodeData.model_extra` 上，可在 `node_factory` 中取到。

3. **工作流 LLM / 问题分类器 / 参数提取器节点的历史消息获取发生在 graphon 包内部**
   （`graphon/nodes/llm/llm_utils.py:519,545`、`graphon/nodes/llm/node.py:1864,1890`、
   `question_classifier_node.py:450`、`parameter_extractor_node.py:878,930`）。
   graphon 调用的是注入的 `PromptMessageMemory` 协议方法
   `get_history_prompt_messages(max_token_limit, message_limit)`，**不会传 pinned 参数**。
   因此"给 `get_history_prompt_messages` 加参数 + 在 `prompt_transform.py` 透传"对上述节点**完全无效**
   （`prompt_transform.py` 根本不在这条调用链上）。

   **正确方案：把 `pinned_message_limit` 存在 `TokenBufferMemory` 实例上（构造函数参数），
   在 `get_history_prompt_messages` 内部自动应用。** 这样 graphon 的所有调用点无需修改即可获得该能力，
   协议签名不变，零兼容风险。

4. **`base_app_runner.py:130` 与 `simple_prompt_transform.py:216,261` 构造的都是
   `WindowConfig(enabled=False)`**，窗口未启用，pinned_size 在这些路径无意义，**不需要修改**。

5. **Agent 节点是 dify 自有代码**：`api/core/workflow/nodes/agent/entities.py` 的 `AgentNodeData.memory`
   在 dify 侧校验，可以使用扩展的 MemoryConfig 子类；`runtime_support.py` 自行构造
   `TokenBufferMemory` 并调用 `get_history_prompt_messages`，需要在构造时传入 pinned_size。

6. 工作流图 JSON 按原样存库（运行时只做校验，不回写），前端存入的 `pinned_size` 不会丢失。

## 语义约定

* M、N 均按 `Message` 行计数（1 行 = 1 条 user + 1 条 assistant prompt message），与现有 `window.size` 语义一致。
* `pinned_size` 仅在 `window.enabled = true` 时生效（窗口 = 最早 M 条 + 最近 N 条）。
* 最早 M 条按 `created_at` 升序单独查询（上限同现有逻辑 cap 500）；不做 `extract_thread_messages`
  线程过滤（该函数只适用于从最新消息回溯的场景），与最近 N 条按 `Message.id` 去重后前置。
* 最新的空 answer 消息剔除逻辑保持不变（作用于最近段）。
* Token 裁剪时保护 pinned 段：从 pinned 段之后开始从头部 pop。

## 修改点明细

### 1. 后端

#### 1.1 `api/core/memory/token_buffer_memory.py`（核心）

* `__init__` 增加 `pinned_message_limit: int | None = None` 参数，存为实例属性（其它创建点
  `message_service.py`、`chat/app_runner.py`、`agent_chat/app_runner.py` 不传，默认 None，行为不变）。
* `get_history_prompt_messages` **不改签名**：
  * 当实例 `pinned_message_limit` 有效（not None 且 > 0）时，额外升序查询最早 M 条 Message；
  * 与最近 N 条按 `Message.id` 去重合并，pinned 段在前，整体按时间升序；
  * 构建 prompt messages 时记录 pinned 段对应的 prompt message 数量；
  * Token 裁剪循环改为保护 pinned 段（`pop(pinned_count)`，且 `len(prompt_messages) > pinned_count + 1`）。
* `get_history_prompt_text` 不改（自动生效）。

#### 1.2 `api/core/prompt/entities/advanced_prompt_entities.py`

* 新增 `ExtendedWindowConfig(MemoryConfig.WindowConfig)`，添加 `pinned_size: int | None = None`；
* 新增 `ExtendedMemoryConfig(MemoryConfig)`，字段 `window: ExtendedWindowConfig`；
* 更新 `__all__`。**仅供 dify 侧校验的实体（Agent 节点）使用**；LLM 类节点用不到（见调研结论 2）。

#### 1.3 `api/core/workflow/node_factory.py`

* `fetch_memory(...)` 增加 `pinned_message_limit: int | None = None` 参数，传给 `TokenBufferMemory` 构造函数；
* `_build_memory_for_llm_node` 增加 `raw_node_data: BaseNodeData` 参数，从原始 extras 中读取
  `memory.window.pinned_size`（`raw_node_data` 是 `NodeConfigDictAdapter` 校验出的 `BaseNodeData`，
  extra="allow" 保留了原始 memory dict），并传给 `fetch_memory`；
* `_build_llm_compatible_node_init_kwargs` 调用 `_build_memory_for_llm_node` 时把校验前的 `node_data` 传入。

#### 1.4 `api/core/workflow/nodes/agent/entities.py`

* `memory` 字段类型改为 `ExtendedMemoryConfig | None`。

#### 1.5 `api/core/workflow/nodes/agent/runtime_support.py`

* `fetch_memory(...)` 增加 `pinned_message_limit: int | None = None` 参数并传给 `TokenBufferMemory`；
* 调用点（约 185-193 行）传入 `node_data.memory.window.pinned_size`（注意 window.enabled 判断）。

#### 明确不需要修改

* `api/core/prompt/prompt_transform.py`（不在工作流节点调用链上；实例方案下也无需透传）
* `api/core/app/apps/base_app_runner.py`、`api/core/prompt/simple_prompt_transform.py`（window 均为 disabled）

### 2. 前端

#### 2.1 `web/app/components/workflow/types.ts`

* `Memory.window` 增加 `pinned_size?: number | string | null`。

#### 2.2 `web/app/components/workflow/nodes/_base/components/memory-config.tsx`

* 在 Window Size 控件下方新增 Pinned Size 行，复用现有 Slider + Input 风格：
  * 常量 `PINNED_SIZE_MIN = 1`、`PINNED_SIZE_MAX = 100`、`PINNED_SIZE_DEFAULT = 10`；
  * 不设独立开关，仅当 `window.enabled` 时可用；`pinned_size` 为 `null`/空表示不启用 pinned；
  * blur 时为空则回落到 `null`（区别于 window.size 回落到默认值）。
* 注意现有 `WINDOW_SIZE_DEFAULT = 50`，N 的默认值保持不变。

#### 2.3 i18n（key 为扁平点号字符串，与 `nodes.common.memory.windowSize` 同级）

* `web/i18n/en-US/workflow.json`：`"nodes.common.memory.pinnedSize": "Pinned Size"`（+ `pinnedSizeTip`）；
* `web/i18n/zh-Hans/workflow.json`：对应中文翻译。

### 3. 测试

#### 3.1 `api/tests/unit_tests/core/memory/test_token_buffer_memory.py`（在现有用例基础上补充）

* `pinned_message_limit` 为 None 时行为与现状完全一致；
* 最早 M 条 + 最近 N 条都被保留且顺序正确（pinned 在前、整体升序）；
* 总消息数 ≤ M+N 时去重后等于全量，无重复；
* Token 裁剪时 pinned 段不被裁掉，只裁剪中间部分；
* 最新空 answer 消息剔除逻辑不受影响。

#### 3.2 node_factory 相关测试

* 原始节点数据中的 `memory.window.pinned_size` 能正确传入 `TokenBufferMemory`
  （覆盖 graphon 校验丢弃该字段的回归场景）。

#### 3.3 agent `runtime_support` 测试

* `ExtendedMemoryConfig` 解析 `pinned_size` 并透传到 `TokenBufferMemory`。

### 4. 修改记录

* 在 `trae_history_xufan.md` 中记录本次修改。

## 实现步骤

1. 改造 `TokenBufferMemory`（构造函数参数 + 查询合并 + 去重 + 裁剪保护）
2. 新增 `ExtendedWindowConfig` / `ExtendedMemoryConfig`
3. 改造 `node_factory.py`（`fetch_memory` + `_build_memory_for_llm_node` 从原始 extras 提取 pinned_size）
4. 改造 agent 节点（`entities.py` + `runtime_support.py`）
5. 前端类型 + MemoryConfig 组件 + i18n
6. 编写后端单元测试
7. 更新 `trae_history_xufan.md` 修改记录
