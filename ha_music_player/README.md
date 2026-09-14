# HA Music Player

Home Assistant 本地音乐播放器。集成为后端实体，卡片为独立 Lovelace 插件，需分开安装。

## 功能

- 扫描 HA 主机上的本地音乐目录
- 媒体播放器实体：播放 / 暂停 / 停止、上一首 / 下一首、进度、音量、循环、随机、选输出、浏览曲库
- Lovelace 卡片 `custom:ha-music-player-card`（宽度随所在列铺满）
- 输出：本页浏览器、其他 `media_player` 音箱
- 可选小爱音响控制
- 读取标签、内嵌封面、内嵌歌词或同目录 `.lrc`

支持格式：`mp3` `flac` `m4a` `wav` `ogg` `aac` `wma`

## 要求

- Home Assistant 2024.12.0 及以上
- 音乐文件在 **HA 主机** 上可读（本机目录、NAS 挂载、`/media` 等）

## 安装

### HACS

1. HACS → 自定义仓库 → 添加本仓库，类型选 **Integration**
2. 搜索「音乐播放器」并安装
3. 重启 Home Assistant

### 手动

把 `custom_components/ha_music_player` 复制到 HA 的 `config/custom_components/`，重启。

### 卡片

HACS → 自定义仓库 → 添加 `ha-music-player-card` 目录对应仓库，类型选 **Dashboard**。

手动：把 `ha-music-player-card/ha-music-player-card.js` 放到 `config/www/`，仪表盘 → 资源：

```yaml
url: /local/ha-music-player-card.js
type: module
```

已从旧版升级的，删掉资源 `/ha_music_player/ha-music-player.js`。

## 配置

设置 → 设备与服务 → 添加集成 → **音乐播放器**

| 项 | 说明 |
|---|---|
| 音乐目录 | HA 主机路径，如 `/media/music`、`/share/nas/music` |
| 开启小爱音响控制 | 可选，默认关 |

配置完成后生成实体「音乐播放器」。安装卡片后即可在仪表盘播放。

### 选项

集成 → 音乐播放器 → 配置，可改目录，并增加：

| 项 | 说明 |
|---|---|
| 其他音箱 | 要推送播放的普通 `media_player` |
| 小米 Home / Miot | 仅小爱需要，见下方 |

改目录后会重新扫描。也可调用服务 `ha_music_player.scan`。

## 实体

`media_player` 实体「音乐播放器」：播放、暂停、停止、上一首、下一首、进度、音量、循环、随机、选择输出、浏览曲库。

可在开发者工具、自动化、更多信息里控制，与卡片同步。

## 小爱音响

填的是 **Home Assistant 里的媒体播放器实体**，不是设备型号或 IP。

一台小爱在 HA 里常常有两个实体：

| 配置项 | 来源 | 示例 |
|---|---|---|
| 小米 Home | 米家 / Xiaomi Home 集成 | `media_player.xiaomi_speaker` |
| 小米 Miot | Xiaomi Miot Auto 集成 | `media_player.xiaomi_lx06` |

两个都有就都选（一个控不住会走另一个）。只有一个就填一个。

开启后，卡片 / 实体的输出列表里会出现「小爱」。

音箱要能访问 HA 给出的音频地址（一般同一局域网）。

## 卡片

仪表盘 → 添加卡片 → 手动：

```yaml
type: custom:ha-music-player-card
```

宽度跟随仪表盘列宽。

## 播放器

**输出**

- 本页：当前浏览器播放
- 音箱：推到选项里勾选的 `media_player`
- 小爱：推到已配置的 Home / Miot 实体

**控件**：播放 / 暂停、上一首 / 下一首、进度、音量、列表循环 / 单曲循环 / 关闭循环、随机、歌词、列表搜索

刷新页面会尽量续播上一首。

## 服务

```yaml
service: ha_music_player.scan
```

重新扫描音乐目录。

## 目录示例

```
/media/music/
  周杰伦/
    晴天.mp3
    晴天.lrc
  林俊杰/
    江南.flac
```

```
/media/music/
  华语/
    晴天 - 周杰伦.mp3
    晴天 - 周杰伦.lrc
    江南 - 林俊杰.flac
```

文件夹名会作为列表分类显示。歌名、歌手、专辑、封面、时长来自文件标签；没有标签时用文件名。
