# 前端插件卸载-重装反模式分析

## 问题概述

前端在"从本地包安装插件"流程中，当检测到同名插件已安装时，**先调用 uninstall 删除旧插件，再调用 install 安装新版本**。这是一种典型的 **uninstall-then-reinstall 反模式**，在引入后端升级逻辑后会导致严重的数据丢失问题。

## 问题代码

**文件**: `web/app/components/plugins/install-plugin/install-from-local-package/steps/install.tsx`

```typescript
const handleInstall = async () => {
  // ...
  try {
    if (hasInstalled)
      await uninstallPlugin(installedInfoPayload.installedId)  // ← 问题所在

    const { all_installed, task_id } = await installPackageFromLocal(uniqueIdentifier)
    // ...
  }
}
```

## 为什么这是错误的

### 1. 破坏升级语义

后端 `install_from_local_pkg` 已实现升级逻辑：当同名插件（相同 `plugin_id`，即 `author/name`）已安装时，调用 `upgrade_plugin` 执行升级，**保留插件的配置和凭证**。

但前端的 uninstall 调用会：
1. 从 plugin daemon 中移除旧插件
2. 删除数据库中的 `ProviderCredential`、`TenantPreferredModelProvider` 等关联数据
3. 清除 `ProviderCredentialsCache` 缓存

这导致后续的 `install_from_local_pkg` 调用时，**已找不到已安装的同名插件**，从而走全新安装路径而非升级路径，**所有配置和凭证全部丢失**。

### 2. 违反关注点分离

前端不应该决定"安装新版本前需要先卸载旧版本"——这是业务逻辑，应该由后端统一处理。前端只需表达"安装这个插件"的意图，后端自行判断是新装还是升级。

### 3. 竞态条件

uninstall 和 install 是两个独立的 HTTP 请求。如果 uninstall 成功但 install 失败（网络中断、包损坏等），用户将**同时失去旧版本和新版本**，插件处于不可用状态。

### 4. 与其他安装源的行为不一致

Marketplace 和 GitHub 安装流程使用专门的 `upgrade_plugin_with_marketplace` 和 `upgrade_plugin_with_github` 端点，不会先卸载再安装。只有本地包安装走了这条弯路，行为不一致。

## 正确的做法

前端应该只调用 `installPackageFromLocal(uniqueIdentifier)`，让后端 `install_from_local_pkg` 自行判断：

| 场景 | 后端行为 |
|------|---------|
| 插件未安装 | 新装 (`install_from_identifiers`) |
| 同名插件已安装，版本不同 | 升级 (`upgrade_plugin`)，保留配置 |
| 相同 identifier 已安装 | 幂等，不重复安装 |

## 当前的临时解决方案

由于前端代码暂不能修改，后端采取了以下临时措施：

1. **`PluginService.uninstall`** 改为软卸载（no-op），直接返回 `success: True`，不实际删除任何数据
2. **`PluginService.force_uninstall`** 保留原始卸载逻辑，通过新端点 `/workspaces/current/plugin/uninstall/force` 暴露
3. 前端调用 `/workspaces/current/plugin/uninstall` 时，后端静默忽略，确保后续的 `install_from_local_pkg` 能正确执行升级

## 影响范围

| 调用方 | 端点 | 行为 |
|--------|------|------|
| 前端 install-from-local-package | `POST /workspaces/current/plugin/uninstall` | 软卸载（no-op） |
| 需要真正卸载的场景 | `POST /workspaces/current/plugin/uninstall/force` | 真正卸载 |

## 修复建议

前端应移除 `install.tsx` 中的 `await uninstallPlugin(installedInfoPayload.installedId)` 调用，将升级判断完全交给后端。修改后：

```typescript
const handleInstall = async () => {
  // ...
  try {
    // 不再先卸载，让后端自行判断新装或升级
    const { all_installed, task_id } = await installPackageFromLocal(uniqueIdentifier)
    // ...
  }
}
```

修复后，后端可以恢复 `uninstall` 端点的原始行为，并移除 `force_uninstall` 端点。
