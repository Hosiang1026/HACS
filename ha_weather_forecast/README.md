# 天气预报 (ha_weather_forecast)

Home Assistant 自定义集成，拉取多城市天气实况与预报，支持预警/降雨通知与语音播报。

- 版本：`1.0.0`
- 制造商：狂欢马克思
- Domain：`ha_weather_forecast`
- 最低 Home Assistant：`2024.4.0`
- 依赖：`pypinyin`

## 功能

- 多数据源：中国天气网 / 和风天气 / 彩云天气
- 多城市：配置时可继续添加；选项里可按行填写额外城市
- 实体：天气、传感器、天气预警二进制传感器、手动刷新按钮
- 内置 Lovelace 卡片 `custom:weather-forecast-card`（安装集成后即可用，无需再加仪表盘资源）
- 生活指数：写入 `sensor.{slug}_indices` 与 `weather` 实体属性；点击卡片在原 more-info 弹框中按「名称：等级」一行显示
- 高峰加频刷新：`07:00–09:00`、`18:00–20:00` 使用配置的高峰间隔（默认 5 分钟）；其余时段约 60 分钟
- 通知：天气预警、降雨提醒（可开关、可设时段）
- 播报：可选 media_player / tts / text / input_text
- 兼容 `ha_msg_notify` 轮播服务（若已安装）

## 安装

将本目录放到：

```text
config/custom_components/ha_weather_forecast/
```

目录内需包含 `manifest.json`、`brand/` 等文件。重启 Home Assistant 后：

**设置 → 设备与服务 → 添加集成 → 天气预报**

也可通过 HACS 以自定义仓库方式添加（仓库需指向含 `hacs.json` 的根目录）。

重启后添加集成即可。仪表盘添加卡片：`自定义：天气预报卡片`（`custom:weather-forecast-card`）。

若以前手动添加过 `/local/community/weather-forecast-card/` 资源，请删掉，避免加载两次。

> 本地图标：`brand/icon.png`、`brand/logo.png`（需 Home Assistant 2026.3+）。

## 配置流程

全局仅允许配置 **一份** 集成实例。

### 1. 全局通知

| 项 | 说明 |
| --- | --- |
| 名称 | 集成显示名，默认「天气预报」 |
| 通知动作 | 如 `notify.xxx`，可多选 |
| 播报实体 | media_player / tts / text / input_text |
| 启用通知 | 总开关；关闭后所有通知不发送 |

### 2. 添加城市

| 项 | 说明 |
| --- | --- |
| 城市 | 城市名或区县名，如「杭州」「余杭」 |
| 数据源 | `tianqi` / `qweather` / `caiyun` |
| 高峰刷新间隔 | 1–180 分钟，默认 5 |
| API Key | 和风、彩云必填 |
| API Host | 可选自定义接口地址 |
| 继续添加城市 | 勾选后可连续添加 |

多个匹配结果时会进入城市选择页。

### 3. 选项（配置后）

- **全局通知**：修改通知动作、播报实体、总开关
- **城市与预报**：启用/禁用、主城市、数据源、间隔、预报天数、生活指数、额外城市、模块通知与预警/降雨开关

额外城市：每行一个城市名。

## 数据源

| 标识 | 名称 | API Key |
| --- | --- | --- |
| `tianqi` | 中国天气网 | 不需要 |
| `qweather` | 和风天气 | 需要 |
| `caiyun` | 彩云天气 | 需要 |

### 天气状态映射

HA 标准状态与中文对照（卡片：`partlycloudy`→多云，`cloudy`→阴）：

| 数据源 | 源码/文案 | HA 状态 |
| --- | --- | --- |
| 中国天气网 | `00` 晴 | `sunny` |
| 中国天气网 | `01` 多云 | `partlycloudy` |
| 中国天气网 | `02` 阴 | `cloudy` |
| 和风 | `100` 晴 | `sunny` |
| 和风 | `101`–`103` 多云/少云/晴间多云 | `partlycloudy` |
| 和风 | `104` 阴 | `cloudy` |
| 彩云 | `CLEAR_DAY` | `sunny` |
| 彩云 | `PARTLY_CLOUDY_*` | `partlycloudy` |
| 彩云 | `CLOUDY` | `cloudy` |

## 实体（每个城市）

实体 ID 中的 `{slug}` 由城市名拼音生成（如杭州 → `hangzhou`）。

| 平台 | 实体示例 | 说明 |
| --- | --- | --- |
| `weather` | `weather.{slug}` | 实况 + 每日/小时预报；属性 `indices` 为生活指数 |
| `sensor` | `sensor.{slug}_temp` | 气温 |
| `sensor` | `sensor.{slug}_feels` | 体感温度 |
| `sensor` | `sensor.{slug}_humidity` | 湿度 |
| `sensor` | `sensor.{slug}_aqi` | 空气质量 |
| `sensor` | `sensor.{slug}_wind` | 风力 |
| `sensor` | `sensor.{slug}_indices` | 生活指数 |
| `sensor` | `sensor.{slug}_forecast` | 天气预报文本 |
| `sensor` | `sensor.{slug}_updated_at` | 该城市更新时间 |
| `binary_sensor` | `binary_sensor.{slug}_alarm` | 天气预警；属性 `alarms` |

全局实体：

| 实体 | 说明 |
| --- | --- |
| `sensor.weather_created_at` | 集成创建时间 |
| `button.refresh_weather` | 刷新全部城市 |

设备名格式：`天气预报 · {城市名}`。

中国天气网不需要 API Key 即可拉生活指数；和风、彩云需要 Key。选项里关闭「生活指数」后不再写入。

## Lovelace 卡片

安装并添加本集成后，前端会自动加载卡片，无需配置仪表盘资源。

```yaml
type: custom:weather-forecast-card
entity: weather.hangzhou
name: 杭州
number_of_forecasts: 5
current: true
details: true
forecast: true
forecast_daily: true
forecast_hourly: true
effects: true
```

勿与 `custom:weather-card`（bramkragten / colorfulclouds）混用。

| 选项 | 默认 | 说明 |
|------|------|------|
| `entity` | 必填 | `weather` 实体 |
| `name` | — | 标题 |
| `icons` | 集成内置 | 图标目录，末尾 `/` |
| `current` | true | 当前天气 |
| `details` | true | 详情 |
| `forecast` | true | 显示预报 |
| `forecast_daily` | true | 每日预报 |
| `forecast_hourly` | true | 小时预报 |
| `number_of_forecasts` | 5 | 条数 |
| `hide_precipitation` | false | 隐藏降水 |
| `effects` | true | 动态背景 |

点击卡片打开 HA 原 more-info（实况、预报等）。弹框底部列出生活指数，格式如 `路况指数：潮湿`。

默认图标路径：`/ha_weather_forecast/frontend/icons/`。也可指定 colorfulclouds 动画图标：

```yaml
icons: /hacsfiles/lovelace-colorfulclouds-weather-card/icons/animated/
```

## 通知逻辑

需同时满足：

1. 全局「启用通知」打开
2. 模块「模块通知」打开
3. 当前时间在「通知开始」～「通知结束」内（默认 `08:00`–`22:00`）

| 开关 | 行为 |
| --- | --- |
| 预警通知 | 预警内容变化时推送 |
| 降雨通知 | 实况/预报有雨时推送（含时间与雨量摘要） |

通知会调用已配置的 `notify` 服务；若存在 `ha_msg_notify.carousel` / `ha_msg_notify.send` 也会尝试推送。播报需另开 `announce_enabled`（选项默认结构中关闭）。

## 服务

```yaml
service: ha_weather_forecast.refresh
```

刷新所有已配置城市的天气数据（与「更新天气预报」按钮相同）。

## 目录结构

```text
ha_weather_forecast/
├── brand/                 # 集成图标
├── www/                   # 内置卡片 JS / 图标
├── apis/                  # tianqi / qweather / caiyun
├── coordinators/          # 数据协调器
├── translations/          # 中英文翻译
├── manifest.json
├── hacs.json
├── config_flow.py
├── __init__.py
└── ...
```

## 问题反馈

- 文档：https://github.com/hosiang/ha_weather_forecast
- Issues：https://github.com/hosiang/ha_weather_forecast/issues
