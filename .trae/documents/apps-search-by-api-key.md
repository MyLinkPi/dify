# /apps 页面搜索框支持按 API 密钥筛选应用

## 摘要

在 /apps 页面现有搜索框基础上扩展能力：输入内容同时按「应用名模糊匹配 **OR** API 密钥精确匹配」筛选应用。不新增 UI 控件、不新增 API 参数，复用现有 `name` 查询参数，仅扩展后端查询逻辑并更新搜索框占位文案。

## 已确认的决策

| 决策点 | 结论 |
|---|---|
| 交互方式 | 同一搜索框同时匹配应用名与 API 密钥（不新增控件） |
| 密钥匹配方式 | 完整精确匹配（安全，避免前缀试探密钥） |
| 密钥范围 | 仅 `type="app"` 且属于当前租户（`tenant_id`）的 ApiToken |
| 接口参数 | 复用现有 `name` 参数，前后端接口契约不变 |

## 现状分析

完整链路（已核实）：

```
list.tsx 搜索框（500ms 防抖）
  → useInfiniteAppList → GET /console/api/apps?name=...
  → AppListApi.get（api/controllers/console/app/app.py:444）
  → AppListQuery 校验（app.py:62-91）
  → app_service.get_paginate_apps（api/services/app_service.py:34-78）
  → App 表查询：App.name.ilike('%kw%')，name 截断 30 字符
```

关键事实：
- `ApiToken` 模型在 [model.py](file:///home/xufan/trea_project/dify/api/models/model.py#L2159-2182)，字段含 `app_id`、`tenant_id`、`type`、`token`，已有 `api_token_tenant_idx(tenant_id, type)` 索引。
- 应用 API 密钥由 [apikey.py](file:///home/xufan/trea_project/dify/api/controllers/console/apikey.py#L106) 生成：前缀 `app-` + 24 字符 = **28 字符**，小于后端 `name[:30]` 截断（app_service.py），精确匹配不受截断影响。
- 基础 Input 组件（[input/index.tsx](file:///home/xufan/trea_project/dify/web/app/components/base/input/index.tsx#L102)）支持传入自定义 `placeholder` 覆盖默认值；当前 [list.tsx](file:///home/xufan/trea_project/dify/web/app/components/apps/list.tsx#L266-273) 未传 placeholder。

## 修改方案

### 1. 后端：扩展 `get_paginate_apps` 的名称过滤逻辑

**文件**：[app_service.py](file:///home/xufan/trea_project/dify/api/services/app_service.py#L34-78)

将现有的 name 过滤（约第 60-63 行）：

```python
if args.get("name"):
    name = args["name"][:30]
    filters.append(App.name.ilike(f"%{escape_like_pattern(name)}%", escape="\\"))
```

改为「名称模糊 OR 密钥精确」：

```python
if args.get("name"):
    name = args["name"][:30]
    filters.append(
        sa.or_(
            App.name.ilike(f"%{escape_like_pattern(name)}%", escape="\\"),
            App.id.in_(
                sa.select(ApiToken.app_id).where(
                    ApiToken.type == ApiTokenType.APP,
                    ApiToken.tenant_id == tenant_id,
                    ApiToken.token == name,
                )
            ),
        )
    )
```

- 补充导入：`ApiToken`（来自 `models.model`，确认现有 import 行后追加）、`ApiTokenType`（来自 `models.enums`）。
- `AppListQuery` / controller 无需改动（`name` 参数透传）。
- 安全性：`tenant_id` 条件保证跨租户隔离；精确匹配避免密钥被逐字符试探。

### 2. 前端：更新搜索框占位文案

**文件**：[list.tsx](file:///home/xufan/trea_project/dify/web/app/components/apps/list.tsx#L266-273)

给 Input 增加显式 placeholder：

```tsx
<Input
  showLeftIcon
  showClearIcon
  wrapperClassName="w-[200px]"
  placeholder={t('searchByNameOrApiKey', { ns: 'app' })}
  value={keywords}
  onChange={e => handleKeywordsChange(e.target.value)}
  onClear={() => handleKeywordsChange('')}
/>
```

### 3. i18n 文案

- [en-US/app.ts](file:///home/xufan/trea_project/dify/web/i18n/en-US/app.ts)：新增 `searchByNameOrApiKey: 'Search by name or API key'`
- [zh-Hans/app.ts](file:///home/xufan/trea_project/dify/web/i18n/zh-Hans/app.ts)：新增 `searchByNameOrApiKey: '按名称或 API 密钥搜索'`

（其余语言运行时回退到 en-US，不在本次范围内。）

### 4. 测试（后端）

**文件**：[test_app_service.py](file:///home/xufan/trea_project/dify/api/tests/test_containers_integration_tests/services/test_app_service.py)

在现有 `get_paginate_apps` 测试基础上新增用例：
1. 创建应用 + `type="app"` 的 ApiToken（`tenant_id` 一致），用完整密钥作为 `name` 查询 → 返回该应用。
2. 用密钥的子串（如去掉末位）查询 → 不返回（验证精确匹配）。
3. 用应用名片段查询 → 仍按模糊匹配返回（验证原行为不回归）。
4. 另一租户的相同密钥场景 → 不返回（验证租户隔离）。

## 不做的事

- 不新增独立筛选控件 / 搜索模式下拉。
- 不修改 `AppListParams`、`AppListQuery`、API 契约。
- 不匹配 `type="dataset"` 的密钥。
- 不做密钥的部分/前缀匹配。

## 验证步骤

1. 后端：运行 `cd api && uv run pytest tests/test_containers_integration_tests/services/test_app_service.py -k paginate`（或项目现有的测试命令），确认新旧用例通过。
2. 前端：`cd web && pnpm lint`（及类型检查）确认无错误。
3. 手动验证：启动前后端，在 /apps 搜索框输入某应用的完整 API 密钥 → 仅显示该应用；输入应用名 → 原有模糊搜索正常。
