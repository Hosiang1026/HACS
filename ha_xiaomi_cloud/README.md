# ha_xiaomi_cloud

> Home Assistant 自定义集成，通过小米云服务「查找设备」获取账号下多台设备的定位、状态与控制。

## 功能概览

- 一个小米账号自动发现**多台设备**，动态创建实体
- 周期性触发「查找设备」并拉取 GPS 坐标、电量、在线状态
- 集成级 **定位设置**（刷新间隔、高峰/低谷时段；电量低于 10% 自动减缓定位）
- 集成级 **高德设置**（逆地理编码、通勤距离/时间/路况）
- 每台设备提供 **按钮**（更新、播放声音、查找、丢失模式）与 **文本**（联系电话、丢失留言、云剪贴板）
- 配置时校验账号密码，无设备时给出明确提示
- 选项分菜单保存，定位与高德配置互不影响、保存后不丢失

## 安装

### HACS（推荐）

1. 安装 [HACS](https://hacs.xyz/)
2. HACS → 集成 → 右上角 ⋮ → **自定义仓库**
3. 添加 `https://github.com/MagicStarTrace/xiaomi-cloud`，类别选 **Integration**
4. 搜索 **ha_xiaomi_cloud** 并安装
5. 重启 Home Assistant

### 手动安装

1. 下载最新版本
2. 将仓库中的 `ha_xiaomi_cloud` 文件夹复制到 Home Assistant 的 `custom_components/ha_xiaomi_cloud`
3. 重启 Home Assistant

## 配置

### 添加集成

1. **设置 → 设备与服务 → 添加集成**
2. 搜索 **小米云服务**
3. 输入小米账号与密码（提交时会登录验证）
4. 验证通过后自动创建集成；账号下所有已开启「查找设备」的手机会陆续出现

### 选项菜单

集成卡片 → **配置**，进入选项菜单：

- **定位设置**：刷新间隔、高峰/低谷时段
- **高德设置**：Key、家区域、通勤、活动状态

保存任一菜单后集成会自动 reload 使新配置生效。

### 选项：定位设置

| 选项 | 说明 | 默认 |
|------|------|------|
| 平时刷新间隔 | 非高峰/低谷时段的最大定位间隔（分钟） | 120 |
| 高峰时段 ×3 | 可设 3 段开始/结束时间与刷新间隔 | 07:00–09:00、17:00–20:00 / 10 分钟 |
| 低谷时段 ×2 | 可设 2 段开始/结束时间与刷新间隔 | 20:00–00:00 / 60 分钟 |
| 仅工作日 | 高峰/低谷是否只在周一至周五生效 | 开 |

> 任一设备电量低于 10% 且不在家/公司时，自动将定位间隔放慢为当前间隔的 2 倍（且不低于平时刷新间隔）。在家或公司（活动状态为「在家」「公司」，或位于已配置的家区域）时不受低电量减缓影响。

### 选项：高德设置

| 选项 | 说明 |
|------|------|
| 是否启用 | 开启通勤计算（需 Key + 家区域） |
| 家区域 | 选择一个或多个 `zone` 实体作为「家」 |
| 活动状态 | 可选，绑定人员活动传感器；值 `在家`/`公司` → 骑行， `外出`/`外地` → 驾车 |
| 高德 Key | [高德开放平台](https://lbs.amap.com/) Web 服务 Key（密码框） |

未填 Key 时：地址传感器、通勤相关传感器不会更新（定位追踪仍正常）。

### 配置持久化

- 首次添加集成时写入全部默认选项
- **定位设置**与**高德设置**分开保存，互不影响
- 保存时合并已有配置，不会覆盖另一菜单的选项
- 高德 Key 留空表示保留已保存的 Key
- 家区域、活动状态校验失败时保留上次有效值
- 读取优先级：`options` → `data` → 内置默认值

## 坐标系

定位与高德 API **统一使用 GCJ-02**（国测局坐标，与高德地图一致）。组件从小米云获取 GCJ-02 坐标后直接用于设备追踪与逆地理编码，无需手动选择坐标系。

## 实体说明

集成会为**每个小米账号**创建一个 Hub 设备（`ha_xiaomi_cloud`），并为账号下**每台手机**创建一个设备条目。

### Hub 实体（每账号 4 个）

| 实体 ID 建议名 | 类型 | 说明 |
|----------------|------|------|
| `ha_xiaomi_cloud_created_at` | 传感器 | 集成创建时间 |
| `ha_xiaomi_cloud_locate_count` | 传感器 | 当日定位 API 调用次数 |
| `ha_xiaomi_cloud_amap_count` | 传感器 | 当日高德 API 调用次数 |
| `button.ha_xiaomi_cloud_update` | 按钮 | 立即刷新全部设备定位 |

### 每台设备实体（动态创建，示例型号 `redmi_k60`）

| 建议实体 ID 后缀 | 类型 | 说明 |
|------------------|------|------|
| `_xiaomi` | 设备追踪 | GPS 经纬度、精度、电量 |
| `_xiaomi_battery` | 传感器 | 电量 % |
| `_xiaomi_phone_status` | 传感器 | 在线 / 离线 / 未知 |
| `_xiaomi_update_time` | 传感器 | 最后定位时间 |
| `_xiaomi_address` | 传感器 | 高德逆地理地址（需 Key） |
| `_xiaomi_commute_distance` | 传感器 | 到家/离家通勤距离 km |
| `_xiaomi_commute_time` | 传感器 | 预计通勤时间（分钟） |
| `_xiaomi_commute_info` | 传感器 | 路况/路线摘要 |
| `_xiaomi_play_sound` | 按钮 | 播放提示音 |
| `_xiaomi_find_device` | 按钮 | 查找设备并更新定位 |
| `_xiaomi_lost_device` | 按钮 | 开启丢失模式（需先填文本实体） |
| `_xiaomi_lost_number` | 文本 | 丢失模式联系电话 |
| `_xiaomi_lost_message` | 文本 | 丢失模式锁屏留言 |
| `_xiaomi_clipboard` | 文本 | 云剪贴板（写入后发送到账号） |

设备追踪属性还包括：`imei`、`last_update`、`coordinate_type`（固定 `gcj02`）、`device_phone` 等。

## 服务

域：`ha_xiaomi_cloud`

### `ha_xiaomi_cloud.update`

立即刷新定位。`account` 可选，省略则刷新全部已配置账号。

```yaml
service: ha_xiaomi_cloud.update
data:
  account: "your@email.com"
```

### `ha_xiaomi_cloud.play_sound`

播放提示音。`imei` 与 `device_name` 二选一。

```yaml
service: ha_xiaomi_cloud.play_sound
data:
  account: "your@email.com"
  device_name: "redmi_k60"
```

### `ha_xiaomi_cloud.find_device`

触发查找并更新定位。

```yaml
service: ha_xiaomi_cloud.find_device
data:
  account: "your@email.com"
  imei: "设备IMEI"
```

### `ha_xiaomi_cloud.lost_device`

开启丢失模式。

```yaml
service: ha_xiaomi_cloud.lost_device
data:
  account: "your@email.com"
  device_name: "redmi_k60"
  phone: "13800138000"
  message: "捡到手机请联系我"
  onlinenotify: true
```

### `ha_xiaomi_cloud.clipboard`

发送云剪贴板（账号级，非单设备）。

```yaml
service: ha_xiaomi_cloud.clipboard
data:
  account: "your@email.com"
  text: "要同步的文字"
```

## 工作原理

1. 按配置间隔向小米云发送「查找设备」指令
2. 等待设备响应后拉取坐标、电量、状态
3. 若配置了高德 Key，则进行逆地理编码；启用通勤时计算到家路线
4. 新设备首次出现在账号下时，自动追加对应实体

## 常见问题

**Q：添加集成时报「账号下未找到设备」**  
A：确认小米账号已在手机上登录，且「查找设备 / 查找手机」功能已开启。

**Q：有 device_tracker 但没有 address**  
A：在「高德设置」中填写 Key；通勤功能还需启用并选择家区域。

**Q：修改定位设置后高德 Key 没了（或反之）**  
A：2.0.0 起已修复。若仍异常，请重新保存一次对应菜单；Key 留空表示不修改。

**Q：丢失模式按钮无效**  
A：先在对应设备的 `lost_number`、`lost_message` 文本实体中填写内容，再按丢失模式按钮。

**Q：从旧版 `xiaomi_cloud` 升级**  
A：集成域已改为 `ha_xiaomi_cloud`，请删除旧集成后重新添加（实体 ID 会变化，自动化需相应调整）。

## 更新日志

### 2.0.0

- **重命名**：集成域由 `xiaomi_cloud` 改为 `ha_xiaomi_cloud`，安装目录同步变更
- **坐标系**：固定 GCJ-02（高德），移除坐标系选项，定位与高德 API 直接对齐
- **多设备**：单账号下所有设备自动发现，动态创建/移除实体
- **架构**：引入 Account 层，统一设备状态分发与选项热更新
- **定位设置**：高峰/低谷时段、平时刷新间隔（选项菜单）；电量低于 10% 且不在家/公司时自动减缓定位间隔
- **高德设置**：逆地理地址、通勤距离/时间/路况、活动状态联动、家区域（选项菜单）
- **配置持久化**：定位/高德分菜单保存，合并写入不丢项；Key 留空保留旧值
- **新增平台**：`button`（Hub 更新 + 设备播放声音/查找/丢失模式）、`text`（联系电话/留言/剪贴板）
- **Hub 传感器**：创建时间、每日定位次数、每日高德调用次数
- **设备传感器**：电量、在线状态、更新时间、地址、通勤三件套
- **服务**：`update` / `play_sound` / `find_device` / `lost_device` / `clipboard`
- **配置验证**：添加集成时登录校验账号密码与设备列表
- **其他**：配置失败保留用户名、无设备错误独立提示、实体更新时序优化

### 历史版本（xiaomi_cloud）

- 2025.4.22：初始版本，单账号定位追踪、地址/电量传感器、基础服务与选项
