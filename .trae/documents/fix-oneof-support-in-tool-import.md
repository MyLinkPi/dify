# 修复工具导入时 oneOf 支持问题

## 问题描述

当前项目在导入使用 `oneOf` 的 OpenAPI schema 时存在两个问题：

1. **参数类型识别错误**：`_get_tool_parameter_type` 方法无法识别 `oneOf` 类型，返回 `None`，导致参数类型默认为 STRING
2. **参数值丢失为 null**：`_convert_body_property_type` 方法只处理了 `anyOf`，当 property 使用 `oneOf` 时，方法隐式返回 `null`

## 受影响文件

| 文件 | 方法 | 问题 |
|------|------|------|
| `api/core/tools/utils/parser.py` | `_get_tool_parameter_type` | 不支持 `oneOf` 类型识别 |
| `api/core/tools/custom_tool/tool.py` | `_convert_body_property_type` | 不支持 `oneOf` 类型转换 |

## 修复方案

### 修改 1：parser.py - 支持 oneOf 类型识别

**文件**: `api/core/tools/utils/parser.py`
**方法**: `_get_tool_parameter_type` (第 238-266 行)

**当前代码**:
```python
@staticmethod
def _get_tool_parameter_type(parameter: dict[str, Any]) -> ToolParameter.ToolParameterType | None:
    parameter = parameter or {}
    typ: str | None = None
    if parameter.get("format") == "binary":
        return ToolParameter.ToolParameterType.FILE

    if "type" in parameter:
        typ = parameter["type"]
    elif "schema" in parameter and "type" in parameter["schema"]:
        typ = parameter["schema"]["type"]

    if typ in {"integer", "number"}:
        return ToolParameter.ToolParameterType.NUMBER
    # ... 后续逻辑
    else:
        return None
```

**修改后**:
```python
@staticmethod
def _get_tool_parameter_type(parameter: dict[str, Any]) -> ToolParameter.ToolParameterType | None:
    parameter = parameter or {}
    typ: str | None = None
    if parameter.get("format") == "binary":
        return ToolParameter.ToolParameterType.FILE

    if "type" in parameter:
        typ = parameter["type"]
    elif "schema" in parameter and "type" in parameter["schema"]:
        typ = parameter["schema"]["type"]

    # 支持 oneOf/anyOf 类型识别：取第一个非 null 类型，
    # 同时检查嵌套的 "schema"（OpenAPI 3.0 中 query/path 参数的 oneOf 位于 schema 内）
    if typ is None:
        schema = parameter.get("schema") or {}
        for union_key in ("oneOf", "anyOf"):
            for union_schemas in (parameter.get(union_key), schema.get(union_key)):
                if isinstance(union_schemas, list):
                    for union_schema in union_schemas:
                        if isinstance(union_schema, dict) and union_schema.get("type") not in (None, "null"):
                            typ = union_schema["type"]
                            break
                if typ is not None:
                    break
            if typ is not None:
                break

    if typ in {"integer", "number"}:
        return ToolParameter.ToolParameterType.NUMBER
    # ... 后续逻辑保持不变
```

### 修改 2：tool.py - 支持 oneOf 类型转换

**文件**: `api/core/tools/custom_tool/tool.py`
**方法**: `_convert_body_property_type` (第 341-374 行)

**当前代码**:
```python
def _convert_body_property_type(self, property: dict[str, Any], value: Any):
    try:
        if "type" in property:
            # ... 处理各种类型
        elif "anyOf" in property and isinstance(property["anyOf"], list):
            return self._convert_body_property_any_of(property, value, property["anyOf"])
    except ValueError:
        return value
```

**修改后**:
```python
def _convert_body_property_type(self, property: dict[str, Any], value: Any):
    try:
        if "type" in property:
            # ... 处理各种类型（保持不变）
        elif "anyOf" in property and isinstance(property["anyOf"], list):
            return self._convert_body_property_any_of(property, value, property["anyOf"])
        elif "oneOf" in property and isinstance(property["oneOf"], list):  # 新增
            return self._convert_body_property_any_of(property, value, property["oneOf"])
    except ValueError:
        return value
```

同时在 `_convert_body_property_any_of`（第 304-339 行）中补充嵌套 `oneOf` 的递归处理：

```python
elif "oneOf" in option and isinstance(option["oneOf"], list):  # 新增
    # Recursive call to handle nested oneOf
    return self._convert_body_property_any_of(property, value, option["oneOf"], max_recursive - 1)
```

## 测试用例

### 测试 1：parser.py - oneOf 类型识别

**文件**: `api/tests/unit_tests/core/tools/utils/test_parser.py`

```python
def test_get_tool_parameter_type_with_oneof():
    """测试 oneOf 类型识别"""
    # oneOf 取第一个非 null 类型
    assert (
        ApiBasedToolSchemaParser._get_tool_parameter_type({
            "oneOf": [{"type": "integer"}, {"type": "null"}]
        })
        == ToolParameter.ToolParameterType.NUMBER
    )
    assert (
        ApiBasedToolSchemaParser._get_tool_parameter_type({
            "oneOf": [{"type": "string"}, {"type": "integer"}]
        })
        == ToolParameter.ToolParameterType.STRING
    )
    assert (
        ApiBasedToolSchemaParser._get_tool_parameter_type({
            "oneOf": [{"type": "null"}, {"type": "string"}]
        })
        == ToolParameter.ToolParameterType.STRING
    )
```

### 测试 2：tool.py - oneOf 类型转换

**文件**: `api/tests/unit_tests/core/tools/test_custom_tool.py`

```python
def test_convert_body_property_type_with_oneof():
    """测试 oneOf 类型转换"""
    tool = _build_tool()
    assert tool._convert_body_property_type({"oneOf": [{"type": "integer"}]}, "2") == 2
    assert tool._convert_body_property_type({"oneOf": [{"type": "string"}]}, 1) == "1"
    assert tool._convert_body_property_type({"oneOf": [{"type": "boolean"}]}, "true") is True
    assert tool._convert_body_property_type({"oneOf": [{"type": "null"}]}, "") is None
```

### 测试 3：集成测试 - 完整流程

```python
def test_do_http_request_with_oneof_body(monkeypatch):
    """测试 request body 中 oneOf 参数的完整处理流程"""
    openapi = {
        "parameters": [],
        "requestBody": {
            "content": {
                "application/json": {
                    "schema": {
                        "type": "object",
                        "properties": {
                            "value": {
                                "oneOf": [{"type": "integer"}, {"type": "string"}]
                            }
                        }
                    }
                }
            }
        }
    }
    tool = _build_tool(openapi=openapi)
    # ... 验证 value 被正确转换
```

## 验证步骤

1. 运行现有测试确保无回归：
   ```bash
   cd api && python -m pytest tests/unit_tests/core/tools/utils/test_parser.py -v
   cd api && python -m pytest tests/unit_tests/core/tools/test_custom_tool.py -v
   ```

2. 运行新增测试验证修复：
   ```bash
   cd api && python -m pytest tests/unit_tests/core/tools/utils/test_parser.py::test_get_tool_parameter_type_with_oneof -v
   cd api && python -m pytest tests/unit_tests/core/tools/test_custom_tool.py::test_convert_body_property_type_with_oneof -v
   ```

3. 手动测试：导入包含 `oneOf` 的 OpenAPI schema，验证参数类型正确且值能正确传递

## 风险评估

- **低风险**：修改仅在原有逻辑基础上增加对 `oneOf` 的支持，不影响现有 `type` 和 `anyOf` 的处理
- **向后兼容**：所有修改都是增量式的，不改变现有行为

## 实施记录（2026-07-21）

- 修改 1 在原方案基础上补充了对嵌套 `schema` 内 `oneOf`/`anyOf` 的识别（OpenAPI 3.0 中 query/path 参数的 union 类型位于 `schema` 内），并顺带支持了 `anyOf` 识别
- 修改 2 额外在 `_convert_body_property_any_of` 中补充了嵌套 `oneOf` 的递归处理
- 顺带修复了 `test_parser.py` 中过时的断言：`{"type": "object"}` 自提交 `8f21b4d35b` 起返回 `OBJECT` 而非 `None`
- 验证结果：`tests/unit_tests/core/tools/utils/test_parser.py` 与 `tests/unit_tests/core/tools/test_custom_tool.py` 共 27 个测试全部通过
