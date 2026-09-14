# 通知管理 (ha_msg_notify)

Home Assistant 自定义集成（v1.0.0，需 HA ≥ 2024.1.0）：统一管理通知渠道与消息轮播。

全屋只添加一次；是否推送由各自动化自行决定，本集成只负责渠道配置、发送与轮播。

## 功能

- 通知渠道增删改
- 支持九种渠道类型：企业微信 / 钉钉 / 飞书 / SMTP / REST / Shell / HA notify / 语音播报 / 屏幕显示
- 企微、钉钉、飞书、SMTP 自动注册为 `notify.{渠道ID}`；REST / Shell 注册为 `rest_command.{渠道ID}` / `shell_command.{渠道ID}`
- 每个渠道独立开关
- 消息轮播队列（Store 持久化，无 input_text 255 字符限制）
- Lovelace 自定义卡片：固定高度，文字自下而上滚完后轮播下一条
- 服务调用：`send` 发送通知、`carousel` 仅入队、`clear` 清空队列、`remove` 按索引删除

## 安装

复制到 `custom_components/ha_msg_notify`，或通过 HACS 安装。重启后在「设置 → 设备与服务 → 添加集成」搜索「通知管理」。卡片已独立，需单独把 `ha-msg-notify-card.js` 放到 `www` 并添加 Lovelace 资源 `/local/ha-msg-notify-card.js`。

## 配置

### 首次添加

1. 填写名称与轮播全局设置
2. 添加第一个通知渠道（基础信息 → 渠道参数）

### 轮播设置

| 项 | 说明 | 默认 |
| --- | --- | --- |
| 轮播间隔 | 自动切换间隔（秒） | 5 |
| 启用轮播 | 是否定时轮播 | 开 |
| 最大消息数 | 队列上限，超出删最旧 | 20 |
| 入队模式 | `append` 追加 / `replace` 替换整队 | append |

### 通知渠道（可多个）

基础字段：

| 项 | 说明 |
| --- | --- |
| 渠道名称 | 显示名 |
| 渠道 ID | 自动化引用用，仅小写字母、数字、下划线；同时作为自动注册服务名 |
| 渠道类型 | 见下方渠道类型 |
| 启用 | 是否启用 |
| 加入轮播队列 | 该渠道发送成功后是否自动入队 |

按类型填写参数：

| 类型 | 参数 |
| --- | --- |
| `wework_robot` | Webhook 密钥 |
| `dingtalk` / `feishu` | Webhook 密钥、加签密钥（可选） |
| `smtp` | 服务器、端口、超时、发件人、加密、用户名、密码、收件人、发件人名称 |
| `rest_command` | URL、请求方法（GET/POST/PUT/DELETE）、超时 |
| `shell_command` | 命令 |
| `notify` | 目标 notify 服务 |
| `announce` | 目标 media_player（可多选） |
| `display` | 目标 text / input_text 实体 |

### 选项菜单

- 轮播设置
- 添加渠道
- 编辑渠道
- 删除渠道
- 删除轮播消息

## 生成实体

### 轮播（全局）

| 实体 | 说明 |
| --- | --- |
| `sensor.{实例}_current_message` | 当前消息 |
| `sensor.{实例}_current_source` | 当前来源 |
| `sensor.{实例}_message_time` | 当前消息时间 |
| `sensor.{实例}_message_count` | 队列条数 |
| `sensor.{实例}_message_queue` | 队列（attributes 含完整列表） |
| `number.{实例}_carousel_interval` | 轮播间隔 |
| `switch.{实例}_carousel_enabled` | 轮播开关 |

### 每个渠道

| 实体 | 说明 |
| --- | --- |
| `switch.{实例}_channel_{渠道ID}` | 渠道启用开关 |
| `button.{实例}_channel_{渠道ID}_test` | 渠道测试发送 |

## Lovelace 卡片

独立安装卡片后，仪表盘「添加卡片」搜索「通知消息轮播」，或 YAML：

```yaml
type: custom:ha-msg-notify-card
entity: sensor.message_queue
height: 120
```

| 项 | 必填 | 说明 |
| --- | --- | --- |
| entity | 是 | 消息队列实体，推荐 `sensor.message_queue`（attributes.messages） |
| source_entity | 否 | 来源实体；`entity` 非队列时用，默认推断 `*_current_source` |
| height | 否 | 固定高度（px），默认 120 |

卡片高度固定；每条消息从下往上滚动，全文显示后停留约 2.5 秒再切下一条；新消息入队立即切到最新。也可把 `entity` 设为 `sensor.current_message`（单条，不按队列轮播）。

## 服务

### ha_msg_notify.send

发送通知，可选加入轮播。

```yaml
action: ha_msg_notify.send
data:
  title: Fang到家通知
  message: "当前位置：{{ states('sensor.fang_addr') }}"
  source: Fang到家通知
  channels:
    - wework
    - mobile_fang
  carousel: true
```

| 参数 | 必填 | 说明 |
| --- | --- | --- |
| title | 否 | 通知标题 |
| message | 否 | 通知正文 |
| content | 否 | 轮播内容，未填时用 message |
| source | 否 | 轮播来源 |
| channels | 否 | 渠道 ID 列表，留空推送到所有已启用渠道 |
| carousel | 否 | 是否加入轮播 |
| entry_id | 否 | 多实例时指定 |

### 渠道自动服务

启用后按类型注册，可直接当原生服务用：

```yaml
action: notify.wework
data:
  title: 标题
  message: 正文
```

| 渠道类型 | 注册服务 |
| --- | --- |
| wework_robot / dingtalk / feishu / smtp | `notify.{渠道ID}` |
| rest_command | `rest_command.{渠道ID}` |
| shell_command | `shell_command.{渠道ID}` |

### ha_msg_notify.carousel

仅加入轮播，不推送。

```yaml
action: ha_msg_notify.carousel
data:
  content: "{{ states('sensor.fang_addr') }}"
  source: Fang到家通知
```

### ha_msg_notify.clear

清空轮播队列。

```yaml
action: ha_msg_notify.clear
```

### ha_msg_notify.remove

按索引删除一条轮播消息。

```yaml
action: ha_msg_notify.remove
data:
  index: 0
```

## 渠道类型说明

| 类型 | 行为 |
| --- | --- |
| wework_robot | POST Webhook，企微文本消息；配置填密钥，地址自动拼接 |
| dingtalk | POST Webhook，可选加签；配置填密钥，地址自动拼接 |
| feishu | POST Webhook，可选加签；配置填密钥，地址自动拼接 |
| smtp | 发邮件 |
| rest_command | 请求指定 URL（不传消息体） |
| shell_command | 执行本地命令（不传消息体） |
| notify | 调用已有 notify 服务或 notify 实体 |
| announce | 小爱 intelligent_speaker，否则 tts.speak |
| display | 写入 text / input_text |

## 与 ha_commute_stats 协作

通勤统计负责业务逻辑（到家、上班等），通知管理负责发送与轮播。通勤自动化可改为调用 `ha_msg_notify.send`，渠道在 UI 配置一次即可。

## 已知限制

- 首次安装需至少添加 1 个渠道
- display 类型使用 `input_text` 实体时仍有 255 字符限制
- 队列仅 1 条消息时不自动轮播
- REST / Shell 渠道触发时不携带 title/message
- 自动注册服务名若与系统已有服务冲突则跳过注册
