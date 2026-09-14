# FindMy / AirTag 追踪说明

## 1. 和 ha_icloud_cn 的区别

| 项目 | ha_icloud_cn | FindMy 集成 |
|------|--------------|-------------|
| 接口 | Find My iPhone | Find My 物品网络 |
| 支持设备 | iPhone / iPad / Mac / Watch | AirTag、Find My 配件等 |
| 是否支持 AirTag | 否 | 是 |
| 是否支持 iPhone | 是 | 否 |

**结论：**

- 追踪 iPhone → 继续用 `ha_icloud_cn`
- 追踪 AirTag → 需要 FindMy 类集成（如 `malmeloo/hass-FindMy`）
- 两者都要 → 分开装，或用 PresenceSync 一类方案

`ha_icloud_cn` 不能直接追踪 AirTag。AirTag 走另一套 Apple「查找」接口，现有代码改几行实现不了。

---

## 2. FindMy - Home Assistant 集成是什么意思

官方说明（翻译）：

> 实验性自定义集成，为支持 Find My 网络的设备提供 `device_tracker` 实体。

### 安装与启用

1. 把仓库加入 HACS，安装 **FindMy** 集成  
   仓库：`https://github.com/malmeloo/hass-FindMy`
2. 启用集成后，至少添加两个东西：
   - 一个 **Apple Account**（Apple 账号）
   - 至少一个 **tracker device**（要追踪的 AirTag，需上传密钥文件）
3. 添加账号时必须填写 **anisette 服务器**
   - 可用公共服务器，但不稳定，用久了容易报错
   - 更稳的是自己搭私有 anisette 服务器

### 更新频率

- 默认每个账号 **15 分钟** 查一次（降低被 Apple 封禁风险）
- 想更频繁：再加几个 Apple 账号
  - 1 个账号 → 约 15 分钟
  - 2 个账号 → 约 7.5 分钟
  - 3 个账号 → 约 5 分钟

---

## 3. 密钥是什么、为什么要提取

AirTag 的位置数据是加密的。要在 HA 里追踪，必须先从 **Mac 的「查找」应用** 导出每个 AirTag 的**私钥**，HA 才能向 Apple 查询位置。

- **只需提取一次**
- 提取完 Mac 可以关机
- 没有 Mac，基本做不了 AirTag 追踪

### 前提

- Mac 已登录**添加 AirTag 的同一个 Apple ID**
- 已打开过「查找」App，能看到 AirTag
- Mac 已安装 Python 3
- 已开启 iCloud 钥匙串、定位服务

---

## 4. 如何提取密钥

### 方法一：macOS 14 及以下（最简单）

在 Mac 终端执行：

```bash
python3 -m venv ~/findmy-env
source ~/findmy-env/bin/activate
pip install findmy
python3 -m findmy decrypt --out-dir ~/devices/
```

说明：

- 会弹出钥匙串密码提示，输入 Mac 登录密码
- 成功后在 `~/devices/` 生成每个 AirTag 一个 **JSON 文件**

### 方法二：macOS 15 / 16（较麻烦）

系统加强了钥匙串保护，上面命令可能失败。

#### 1）临时关闭安全保护（Recovery 模式）

重启 Mac → 进入 Recovery → 打开终端：

```bash
csrutil disable
```

重启后再执行：

```bash
sudo nvram boot-args="amfi_get_out_of_my_way=1"
```

再重启一次。

#### 2）用提取工具

```bash
git clone https://github.com/manonstreet/findmy-key-extractor
cd findmy-key-extractor
pip3 install -r requirements.txt
./extract.sh
```

说明：

- 会自动打开「查找」App
- 从内存截取加密密钥（可能等 10～90 秒）
- 卡住时可关掉「查找」再重跑几次

#### 3）解密导出 JSON

```bash
source ~/findmy-env/bin/activate
pip install findmy
python3 -m findmy decrypt --out-dir ~/devices/
```

#### 4）恢复 Mac 安全设置（必做）

进入 Recovery：

```bash
nvram -d boot-args
csrutil enable
```

### 常见问题

| 问题 | 处理 |
|------|------|
| `BeaconStore` 找不到 | 先打开「查找」App 等刷新；macOS 15+ 用方法二 |
| 提取脚本卡住 | 关掉「查找」再运行 `./extract.sh` |
| 家庭共享的 AirTag | 要用绑定该 Tag 的 Apple ID 在 Mac 上提取 |
| macOS 26 | 目前最难，可能提取失败 |

---

## 5. 导入 Home Assistant（hass-FindMy）

1. HACS → 自定义仓库 → 添加 `https://github.com/malmeloo/hass-FindMy`
2. 安装 **FindMy** 集成 → 重启 HA
3. **设置 → 设备与服务 → 添加集成 → FindMy**
4. 先添加 **Apple Account**（邮箱 + 密码 + 双因素验证 + anisette 地址）
5. 再添加 **Rolling Device**，上传 `~/devices/` 里的 JSON（每个 AirTag 一个）
6. HA 会出现 `device_tracker.findmy_xxx`

注意：

- 首次对齐可能要几小时（老 AirTag 更久），之后会快很多
- 默认约 15 分钟更新一次
- 只支持 AirTag / 物品，不支持 iPhone

---

## 6. anisette 私有服务器是什么

登录 Apple 账号时，苹果会验证「是不是一台真正的苹果设备」。  
anisette 服务器就是**模拟一台虚拟 Mac**，帮 HA 通过这项验证。

- 公共服务器：很多人共用一台「假 Mac」，容易被封
- 私有服务器：只有你用，更稳

---

## 7. NAS 上搭建私有 anisette 服务器

前提：NAS 支持 Docker（群晖 / 威联通 / 绿联 / TrueNAS 等）。

### 方法一：一行命令

```bash
docker run -dit \
  --restart always \
  --name anisette \
  -p 6969:6969 \
  --volume /opt/anisette:/home/Alcoholic/.config/anisette-v3/lib/ \
  dadoum/anisette-v3-server
```

### 方法二：docker-compose（推荐）

新建 `docker-compose.yml`：

```yaml
services:
  anisette:
    image: dadoum/anisette-v3-server
    container_name: anisette-v3
    ports:
      - "6969:6969"
    volumes:
      - anisette-v3_data:/home/Alcoholic/.config/anisette-v3/lib/
    restart: unless-stopped

volumes:
  anisette-v3_data:
```

启动：

```bash
docker compose up -d
```

### 验证

浏览器打开：

```
http://你的NAS的IP:6969
```

有返回内容说明已启动。

### 在 FindMy 集成里填写

```
http://192.168.x.x:6969
```

把 `192.168.x.x` 换成 NAS 局域网 IP。  
HA 和 NAS 同一局域网即可，**不需要公网暴露**。

### 注意

| 问题 | 处理 |
|------|------|
| Permission denied | 数据目录改成 `1000:1000`：`chown -R 1000:1000 ./anisette` |
| 端口被占 | 改成如 `6970:6969`，地址填 `:6970` |
| 群晖 Container Manager | 镜像 `dadoum/anisette-v3-server`，端口 `6969`，挂载卷如上 |

---

## 8. 其他相关方案（简要）

| 方案 | 说明 | 现状 |
|------|------|------|
| PresenceSync | HA 插件，可追踪 AirTag；首次需 Mac 提取密钥包 | 需 HA OS / Supervised + MQTT |
| FindMy Fleet | 曾是 HACS 自定义集成 | 仓库已 404，基本不可用 |
| hass-FindMy | HACS 集成，上传 JSON 密钥 | 当前较常用 |

PresenceSync 若用密钥包方式：Mac 用提取工具生成 `.tar.gz`，在 PresenceSync 面板上传 **Upload extractor bundle**。

---

## 9. 怎么选

| 你要追踪的 | 用什么 |
|------------|--------|
| 只有 iPhone | `ha_icloud_cn` |
| 只有 AirTag | hass-FindMy / PresenceSync |
| 两个都要 | iPhone 用 `ha_icloud_cn`，AirTag 用 FindMy；或 PresenceSync 一起覆盖 |
| 没有 Mac | AirTag 方案基本做不了 |

---

## 10. 参考链接

- hass-FindMy：https://github.com/malmeloo/hass-FindMy
- FindMy.py：https://github.com/malmeloo/FindMy.py
- anisette-v3-server：https://github.com/Dadoum/anisette-v3-server
- findmy-key-extractor：https://github.com/manonstreet/findmy-key-extractor
- PresenceSync：https://github.com/PrayerfulDrop/presencesync-addon
