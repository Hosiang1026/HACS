# ha_icloud_cn

面向中国大陆的 Home Assistant iCloud 自定义集成（当前版本 **2.0.4**）。在官方 icloud 能力基础上内嵌 pyicloud，全程 `china_mainland=True` 访问 `icloud.com.cn`，用于查找 iPhone / iPad / Mac / Watch 等设备位置与电量。不支持 AirTag（见 `FindMy.md`）。

## 背景

2021 年 11 月起，中国大陆 iCloud 域名迁至 `icloud.com.cn`。依赖国际域名的官方集成在大陆无法正常使用；Docker 部署下改系统包也不持久。本集成将适配后的 pyicloud 与配置流一并放在 `/config/custom_components`，升级 HA 或重启容器后仍可继续使用。

感谢 louis_lee 早期分享与维护。

## 与官方 iCloud 集成的区别

| 项目 | 官方 `icloud` | 本集成 `ha_icloud_cn` |
|------|---------------|----------------------|
| 访问域名 | `icloud.com`（国际） | `icloud.com.cn`（大陆，`china_mainland=True`） |
| 依赖方式 | HA 自带 `pyicloud` 包 | 内嵌 pyicloud，不依赖 pip 版并存 |
| 安装位置 | HA Core 内置 | `/config/custom_components`，升级/重启不丢 |
| 大陆可用性 | 域名迁徙后常不可用 | 专为大陆环境可用 |
| 实体 | `device_tracker`、电池传感器 | 每台设备：`device_tracker`、手机电量、今日步数、手机状态、更新时间、位置地址、通勤距离/时间/信息；按钮：播放声音、发送消息、设备丢失；输入：消息内容、联系电话、丢失留言。账号：更新按钮、创建时间、每日定位调用次数、每日高德调用次数 |
| 服务 | `update` / 播放声音 / 显示消息 / 丢失模式 | 同左，域名为 `ha_icloud_cn.*` |
| 配置项 | 家庭设备、刷新间隔等 | 最短刷新间隔（默认 120 分钟）；选项页可配平时/高峰/低谷间隔与时段、通勤、家区域、高德 Key、活动状态实体；密码与 Key 以密码框输入 |
| 会话存储 | 官方 storage | `.storage/ha_icloud_cn/`；失效 reauth 时自动清 cookie/session |
| 设备唯一 ID | 与设备 id 相同 | **与官方相同**，同一账号勿两边同时配置 |
| AirTag | 不支持 | 不支持（见 `FindMy.md`） |

## 安装方法一（git clone）

```bash
cd /config/custom_components
git clone https://github.com/louisslee/icloud888.git ha_icloud_cn
```

重启 HA 后，在「配置 → 设备与服务 → 添加集成」中搜索 `ha_icloud_cn`。用法与官方 iCloud 集成类似。

**注意：** 本集成与官方 `icloud` 的 `unique_id` 相同，同一 Apple 账号请勿两边同时配置。

## 安装方法二（HACS）

1. HACS → 自定义存储库 → `plutosherry/ha_icloud_cn`，类别选「集成」
2. 搜索并下载 `ha_icloud_cn`
3. 重启 HA 后添加集成

## 动作用法

**更新**

设备与服务 → `ha_icloud_cn` → 控制 → 按「更新」。立刻定位该账号下设备。

也可调用服务，`account` 可选（不填则更新全部已配置账号）：

```yaml
action: ha_icloud_cn.update
data:
  account: 你的Apple邮箱
```

**播放声音**

打开对应 iPhone / iPad / Mac / Watch → 控制 → 按「播放声音」。

也可调用服务：

```yaml
action: ha_icloud_cn.play_sound
data:
  account: 你的Apple邮箱
  device_name: 设备名
```

**发送消息**

设备页填「消息内容」，按「发送消息」（会响铃）。也可走服务：

```yaml
action: ha_icloud_cn.display_message
data:
  account: 你的Apple邮箱
  device_name: 设备名
  message: 消息内容
  sound: true
```

**丢失设备**

设备页填「联系电话」「丢失留言」，按「设备丢失」。电话须含国家区号。也可走服务：

```yaml
action: ha_icloud_cn.lost_device
data:
  account: 你的Apple邮箱
  device_name: 设备名
  number: "+8613800138000"
  message: 请联系我
```

`device_name` 填「查找」里的设备名，空格可去掉。

## 更新规则

高峰、低谷默认仅工作日（周一至周五，选项可关）。距离按到最近 HA 区域（一般为家）。有经纬度就写入，不按 GPS 精度丢点。每次轮询都向苹果发起定位（`locate=True`）。

**多台设备（同一账号）**

一个账号只有一套轮询，不是每台各查各的。每次到期向苹果拉整账号设备列表，有电量的一起更新。下次间隔取所有设备里算出来最短的那个。

- 9 台在家睡觉（120 分钟），1 台早高峰在路上（10 分钟）→ 全账号 10 分钟查一次，在家的也会跟着刷
- 8 台在家，1 台本地加班（60 分钟），1 台出远门 500 公里（1~5 小时随机）→ 取最短，可能短于 60 分钟
- 10 台都出远门 → 取各台随机间隔的最短

**人在家（已在 zone）**

| 何时 | 间隔 |
|------|------|
| 工作日 07:00–09:00、17:00–20:00 | 10 分钟（抓出门） |
| 其余（含夜里、低谷、周末） | 120 分钟 |

**人不在家，且离家不足 30 公里（本地）**

| 何时 | 间隔 |
|------|------|
| 工作日 07:00–09:00、17:00–20:00 | 10 分钟 |
| 工作日 20:00–00:00 | 60 分钟（加班） |
| 其余 | 1~120 分钟（随机） |

**出远门（离家超过 50 公里）**

不再走高峰/低谷。电量 ≤20% 时间隔再 ×2。

| 离家 | 间隔 |
|------|------|
| 50–100 公里 | 1~2 小时（随机） |
| 100–200 公里 | 1~3 小时（随机） |
| 200–300 公里 | 1~4 小时（随机） |
| 300–800 公里 | 1~5 小时（随机） |
| 800–2000 公里 | 1~6 小时（随机） |
| 2000 公里以上 | 1~12 小时（随机） |

30–50 公里用滞回：已算出远门须回到 30 公里以内才改本地；本地须超过 50 公里才算出远门。进 zone 一律按「人在家」，并清出远门状态。

**特例**

- 设备 pending：30 秒，只重试 1 次
- API 异常：5 分钟
- 算间隔失败：回退平时 120 分钟
- 定位未完成：下次 1 分钟
- 手动 `update`：立刻定位，最多等 5×4 秒
- 全家都出远门：调度不被高峰/低谷边界截短

默认值可在选项页改：平时间隔默认 120 分钟，高峰默认 07:00–09:00/17:00–20:00、间隔 10 分钟，低谷默认 20:00–00:00、间隔 60 分钟，高峰/低谷默认仅工作日。已有配置不会自动改默认值。

## 通勤

选项页开启通勤后，填写家区域与高德 Key。交通方式不再手选：

- 填写活动状态实体：可多选，按设备名 / 机主 / 关联 person 匹配；`在家`、`公司` 用骑车；`外出`、`外地` 用驾车
- 未填写或匹配不上：离家不足 10 公里用骑车，大于等于 10 公里用驾车

开启后每台有定位的设备写入位置地址（属性 `poi` / `city` / `district`）、通勤距离、通勤时间、通勤信息。未开启或未填 Key 时不调高德。接口为逆地理编码与路径规划（驾车或电动车）。定位没变、仍在约 400 米同一网格、或已在家区域时跳过；路径规划进家后也不打。账号上的「每日定位调用次数」「每日高德调用次数」按自然日累计，跨日清零。

默认轮询下估算（每台）：

| 场景 | 次数 |
|------|------|
| 工作日正常通勤 | 约 30 次/天（两种接口大约各半） |
| 周末待在家 | 约 0–3 次/天 |
| 理论上限（间隔落到 1 分钟且每轮换格、不在家） | 可达约 1440 次/天 |

3 台都按工作日通勤、周末在家，一个月大约 **2000** 次。个人认证 Key 基础 LBS（逆地理与路径规划共用）免费额度 15 万次/月，这个用量大约 1%。实际以「每日高德调用次数」为准。

## 更新日志

[2.0.4]
- 密码、高德 Key 配置项改为密码框输入
- 定位设置平时间隔默认 120 分钟
- 账号定位/高德调用次数改为按日累计（跨日清零，重启可恢复）

[2.0.3]
- 每次轮询都向苹果发起定位；未完成则 1 分钟后再查
- 本地其余、出远门间隔改为 1~对应上限随机
- 账号增加定位次数、高德次数（按日清零，重启可恢复）

[2.0.2]
- 去掉 GPS 精度配置与按精度丢点/10 分钟重试；有经纬度就写入
- 更新时间改为 timestamp 实体，取苹果定位 `timeStamp`
- 每台设备增加位置地址、通勤距离/时间/信息；账号增加创建时间
- 设备页增加消息内容、联系电话、丢失留言输入，以及发送消息、设备丢失按钮
- 活动状态实体可多选，按设备名/机主/关联 person 匹配

[2.0.1]
- 通勤去掉交通方式配置；改为选填活动状态实体（在家/公司骑车，外出/外地驾车）；未填则按离家 10 公里自动选择

[2.0.0]
- 适配 HA 2026.6+：修正 `ConfigFlowResult`、`DeviceInfo`/`TrackerEntity` 导入；内嵌 pyicloud 相对导入，manifest 声明 certifi/srp/fido2 等依赖，不再与 pip 版 pyicloud 并存；选项变更走 `config_entries.async_reload`
- 改进登录与会话：全程 `china_mainland=True` 走 `.cn` 域名；首次 reauth 清 `.storage/ha_icloud_cn` 下 `.cookiejar`/`.session` 并弹窗，重复触发只停轮询/API；`user_info`/配置流拉设备遇 2FA·2SA·AuthRequired 按需 reauth 或回登录表；验证码错误先清会话再登录，按 `requires_2fa`/`requires_2sa` 重进对应步骤，否则回密码表；验证码通过后 reauth 走 `reauth_confirm` 写回；保留已存密码，约月过期后只需再输验证码
- 改进生命周期与并发：`keep_alive`/设备更新/远程操作共用 `_update_lock`；轮询用 `async_track_point_in_utc_time`，线程侧 `call_soon_threadsafe` 调度/取消；触发用 `async_create_background_task`；`_stop_api`/shutdown 等 monitor 最多 30 秒；`shutdown` 先取消轮询与午夜重置、清 listeners 再持锁停 API，listener 退订回事件循环；卸载先置 `_shutdown` 并取消轮询，再卸平台后 executor `shutdown`，失败则恢复轮询；末账号卸完注销全部服务；配置流 `_async_release_api()`；待 reauth 时 `_trigger`/`async_keep_alive` 直接返回
- 改进轮询与定位：经纬度缺一仍待定位；pending 30 秒、API 异常 5 分钟重试；算间隔失败回退平时间隔；zone 坐标经事件循环 `_zone_coordinates` 拉取（`active_zone`/读 zone 超时 10 秒跳过），按距离与低电量动态间隔；选项页可开高峰（默认 07:00–09:00/17:00–20:00、间隔 10 分钟，最多 3 段）与低谷（默认 20:00–00:00、间隔 60 分钟，最多 2 段），调度不超过下一时段边界
- 改进认证链路：拉设备/遍历 status、`keep_alive` 认证与 locate、远程操作均识别 2FA·2SA·AuthRequired 与 `requires_2fa`/`requires_2sa`，统一 reauth；`setup(schedule_update=False)` 重连不重复刷设备；密码/认证失效抛 `ConfigEntryAuthFailed`，无设备或服务不可用抛 `ConfigEntryNotReady`；`keep_alive` 遇前者直接返回、后者按间隔重试
- 改进设备与实体：每台设备提供 `device_tracker`、手机电量、今日步数、手机状态、更新时间；实体名固定中文；`device_object_slug` 取末汉字+机型，entity_id 统一 `{slug}_icloud[_后缀]`（tracker/`_battery`/`_steps`/`_status`/`_update_time`），更新时间 unique_id `{slug}_icloud_update_time`，同步清旧 `_location_time`/非 icloud `_update_time`；入网后 `apply_suggested_entity_id` 校正；无有效电量不建档并移出跟踪，`_purge_unavailable_devices` 删孤儿实体/设备并校正 id（保留 `{unique_id}_hub` 服务设备），实体侧设备消失则 `force_remove`；同步收尾 `_finish_device_sync` 回事件循环发信号；定位写入 `timestamp`（毫秒，缺省补当前）；刷新 AppleDevice 句柄；电量失效清百分比；步数由相邻定位 haversine 估算（滤基站/过近/过快、按走跑步长与路径系数、日切与午夜 `async_track_time_change` 清零、`RestoreSensor` 恢复当日），更新时间取 `timeStamp`，手机状态按 online 显示在线/离线；家庭成员/owner/status 防空；设备遍历与间隔计算异常各自捕获；`add_entities` 遇 `_shutdown` 跳过、字典迭代 `RuntimeError` 则 1 秒后重试；`icloud.com.cn` 链接、不轮询，电池未知 `mdi:battery-unknown`；setup 注册 `ha_icloud_cn` hub（厂商狂欢马克思）
- 改进服务：阻塞调用改 executor；远程操作锁等待最多 60 秒否则 `busy`；`update` 走 `force_locate`：持锁、`refresh(locate=True)` 后最多轮询 5×4 秒等定位结果；待 reauth/未认证/已卸载/`PyiCloudServiceUnavailable` 时 `ServiceValidationError`；`display_message` 标题 Find My iPhone Alert；`lost_device` 不支持抛错；`update` account 可选、全卸载后不 KeyError；服务防重复注册
