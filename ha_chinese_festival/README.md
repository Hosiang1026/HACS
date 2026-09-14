# 中国节日

Home Assistant 自定义集成（v2.0.0，需 HA ≥ 2024.1.0）：节日/节气/纪念日/生日汇总与证件到期提醒，支持定时 notify、黄历、AI 运势、语音助手。

全屋只添加一次。选项菜单：全局配置、添加、编辑、删除（类型：证件 / 生日 / 纪念日 / 法定节假日）。

## 功能

- 公历/农历节日、节气、国际日、特殊日、复活节
- 法定节假日：放假 / 补班 / 高速免费（增删改，可自动拉取）
- 纪念日：累计阳历 / 倒计阳历 / 倒计阴历
- 生日：农历 / 阳历
- 证件到期临期提醒
- 三伏 / 四九 / 梅雨提示
- 各类「下一节日」独立实体
- 黄历（宜忌、八字、月相等）
- 假期规划、日历点选
- 分类定时 notify（日历 / 节日 / 事项(生日+纪念日) / 证件）
- AI 运势、高级通知规则、语音助手 Intent

## 生成实体

单 Config Entry，下列实体各 1 个。设备制造商：狂欢马克思。

### Sensor

| 实体 ID | 含义 | state | 主要 attributes |
| --- | --- | --- | --- |
| `sensor.chinese_festival` | 汇总下一节日 | 距下一节日天数 | `next_name`、`content`、`today`、`next`、`tips`、`has_near_festival` |
| `sensor.license_expiry` | 证件到期提醒 | 最近证件剩余天数 | `items`、`near`、`content`、`has_near_license` |
| `sensor.day_type` | 今日类型 | `workday` 工作日 / `holiday` 节假日 / `repair` 补班 | `name`、`freeway`、`holiday_day` |
| `sensor.solar_date` | 今日阳历日期 | 如 `2026-09-02` | — |
| `sensor.weekday` | 今日星期 | 如 `星期三` | — |
| `sensor.astro` | 今日星座 | 如 `处女座` | — |
| `sensor.lunar_date` | 今日农历 | 如 `丙午马年七月廿一` | `gz_year`、`gz_month`、`gz_day`、`animal`、`l_year`、`l_month`、`l_day`、`month_cn`、`day_cn`、`is_leap`、`term` |
| `sensor.year_day` | 今年第几天 | 数字 | — |
| `sensor.festival_count` | 节日总数量 | 数字 | `sftv`、`lftv`、`term`、`special`、`internation`、`legal`、`easter` 等分类计数 |
| `sensor.license_count` | 证件条目数量 | 数字 | — |
| `sensor.birthday_count` | 生日条目数量 | 数字 | — |
| `sensor.anniversary_count` | 纪念日条目数量 | 数字 | — |
| `sensor.love_days` | 恋爱累计天数（纪念日类型=累计阳历） | 最大累计天数 | `name`、`items`、`content` |
| `sensor.holiday_plan` | 下一法定假期规划 | 距该假期天数 | 整段 `holiday_plan`（区间、拼假方案等） |
| `sensor.next_solar` | 下一阳历节日 | 距其天数 | `next_name` |
| `sensor.next_lunar` | 下一农历节日 | 距其天数 | `next_name` |
| `sensor.next_term` | 下一节气 | 距其天数 | `next_name` |
| `sensor.next_special` | 下一特殊节日 | 距其天数 | `next_name` |
| `sensor.next_intl` | 下一国际日 | 距其天数 | `next_name` |
| `sensor.next_seasonal` | 下一三伏/四九/梅雨 | 距其天数 | `next_name` |
| `sensor.next_legal` | 下一法定假日 | 距其天数 | `next_name` |
| `sensor.next_birthday` | 下一生日 | 距其天数 | `next_name` |
| `sensor.next_anniversary` | 下一纪念日（倒计类） | 距其天数 | `next_name` |
| `sensor.ai_fortune` | AI 运势 | 摘要 / `disabled` 未启用 / `empty` 暂无 | `prediction`、`model`、`person`、`updated` |

### 黄历 Sensor

今日黄历分项；除标注 diagnostic 外为主实体。

| 实体 ID | 含义 | state |
| --- | --- | --- |
| `sensor.suit` | 今日宜 | 宜事项文本 |
| `sensor.avoid` | 今日忌 | 忌事项文本 |
| `sensor.eight_char` | 今日八字 | 干支文本 |
| `sensor.hour` | 今日时辰 | 时辰文本 |
| `sensor.clash` | 今日冲煞 | 冲煞文本 |
| `sensor.moon_phase` | 今日月相 | 月相名；attributes 含月相详情 |
| `sensor.solar_term` | 今日节气 | 节气名（无则空） |
| `sensor.taboo` | 彭祖百忌 | 文本（diagnostic） |
| `sensor.good_spirit` | 吉神 | 文本（diagnostic） |
| `sensor.bad_spirit` | 凶煞 | 文本（diagnostic） |
| `sensor.fetus` | 胎神 | 文本（diagnostic） |
| `sensor.tone` | 纳音 | 文本（diagnostic） |
| `sensor.triad` | 三合 | 文本（diagnostic） |
| `sensor.hexad` | 六合 | 文本（diagnostic） |
| `sensor.grade` | 宜忌等第 | 文本（diagnostic） |
| `sensor.zodiac_sign` | 黄历星座 | 文本（diagnostic） |
| `sensor.season` | 农历季节 | 文本（diagnostic） |

### Binary Sensor

| 实体 ID | 含义 | state |
| --- | --- | --- |
| `binary_sensor.is_holiday` | 今日是否节假日 | on / off |
| `binary_sensor.is_repair` | 今日是否补班 | on / off |

### Date

| 实体 ID | 含义 | state | 主要 attributes |
| --- | --- | --- | --- |
| `date.chinese_festival_tap` | 日历点选日期（可改写查看某日） | 所选日期 | `selected_date`、`month_grid`、`tap_solar`、`tap_lunar`、`almanac` |

## 配置

首次添加时填写名称 + 全局项；之后在选项里维护。

### 全局

| 配置项 | 键名 | 默认 | 说明 |
| --- | --- | --- | --- |
| 语言切换 | `language` | `zh-Hans` | `zh-Hans` / `zh-Hant` |
| 日历通知 | `notify_calendar` | `true` | 是否推送日历类通知 |
| 日历通知时间 | `notify_calendar_time` | `08:00:00` | — |
| 节日通知 | `notify_festival` | `true` | 临近节日是否推送 |
| 节日通知时间 | `notify_festival_time` | `08:00:00` | — |
| 事项通知 | `notify_memorial` | `true` | 生日 / 纪念日 / 恋爱累计 |
| 事项通知时间 | `notify_memorial_time` | `08:00:00` | — |
| 证件到期通知 | `notify_license` | `true` | 证件临期是否推送 |
| 证件到期通知时间 | `notify_license_time` | `08:00:00` | — |
| 通知动作 | `notify` | 空 | `notify.xxx`（可多选） |
| 节日临近天数 | `near_festival_days` | `8` | 1–60 |
| 生日临近天数 | `near_birthday_days` | `7` | 1–60 |
| 纪念日临近天数 | `near_anniversary_days` | `7` | 1–60 |
| 证件临期天数 | `near_license_days` | `31` | 1–365 |
| 自动假期数据 | `holiday_auto` | `true` | 自动拉取法定假期 |
| 启用AI运势 | `ai_enabled` | `false` | — |
| AI接口地址 | `ai_api_url` | `https://api.chatanywhere.tech` | — |
| AI密钥 | `ai_api_key` | 空 | — |
| AI模型 | `ai_model` | `deepseek-r1` | 可选列表或自定义 |
| 高级通知 | `notify_rules_enabled` | `false` | — |
| 通知规则(YAML) | `notify_rules` | 空 | YAML 字典 |
| 启用语音助手 | `intent_enabled` | `true` | — |

### 添加 / 编辑 / 删除

先选类型，再填表单：

| 类型 | 字段 |
| --- | --- |
| 证件 | `name` + `date(YYYY-MM-DD)` 到期日 |
| 生日 | `name` + `date(YYYY-MM-DD)` + `type`：`0` 农历 / `1` 阳历 |
| 纪念日 | `name` + `date(YYYY-MM-DD)` + `type`：`0` 累计阳历 / `1` 倒计阳历 / `2` 倒计阴历 |
| 法定节假日 | `name` / `date(MM-DD)` / `freeway(0收费/1免费)` / `repair` / `holiday`（`MM-DD,MM-DD` 或空） |

### 选项菜单

全局配置、添加、编辑、删除。

## 内置只读

`sftv` / `lftv` / `term` / `special` / `internation`、三伏 / 四九 / 梅雨 / 复活节、结婚周年文案表。随版本更新，不进配置；在全局设备上以 `next_*` 实体展示下一发生。

## 更新与通知

- 数据每小时刷新；每日 `00:05` 再刷一次
- 各类通知按各自开关与时间独立触发；存在临近项时向所选 notify 推送

## 安装

复制到 `custom_components/ha_chinese_festival`，或通过 HACS 安装。重启后在「设置 → 设备与服务」添加「中国节日」。
