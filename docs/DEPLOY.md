# 部署与接入

这份文档讲清楚**三层怎么串起来**，以及两条可选路线。
参数怎么拿见 [HOWTO-CAPTURE.md](HOWTO-CAPTURE.md)。

---

## 1. 三层结构

```text
┌─────────────────────────────────────────────┐
│ QQ 客户端 / 协议端                            │  ← 负责收发 QQ 消息
│ （QQ 官方机器人，或 NapCat 等 OneBot v11 实现） │
└──────────────────┬──────────────────────────┘
                   │ OneBot v11 / 官方 WebSocket
┌──────────────────▼──────────────────────────┐
│ AstrBot                                      │  ← 大脑：消息路由、插件宿主、WebUI
│ 消息平台适配器 + 本插件                        │
└──────────────────┬──────────────────────────┘
                   │ 直接 HTTP
┌──────────────────▼──────────────────────────┐
│ 本插件的技能部分 chaoxing/                    │  ← 取表单、提交、记状态
└─────────────────────────────────────────────┘
```

**AstrBot 自己不会登录 QQ**，它需要一个消息平台适配器。本插件只是 AstrBot 的一个技能，
不参与 QQ 登录，也不碰 QQ 协议。

| 层 | 端口（默认） | 谁提供 |
|---|---|---|
| AstrBot WebUI | 6185 | AstrBot |
| OneBot v11 反向 WebSocket | 6199 | AstrBot 做**服务端** |
| NapCat WebUI | 6099 | NapCat |

---

## 2. 先选路线

| 路线 | 适合谁 | 大概耗时 | 要不要 QQ 机器人 |
|---|---|---|---|
| **A. 只要打卡结果** | 自己一个人用 | 10 分钟 | **不要** |
| **B. AstrBot + QQ 官方机器人** | 想在 QQ 里收结果、用指令 | 30 分钟 | 要（官方） |
| **C. AstrBot + OneBot 协议端** | 想要私聊/群聊完整体验 | 1–2 小时 | 要（第三方） |

> **只是自己打卡，选 A 就够了。** 命令行 + Webhook 把结果推到微信，体验和机器人几乎等价。

---

## 3. 路线 A：命令行 + Webhook（最轻）

不需要 AstrBot，不需要 QQ 机器人。

```bash
pip install requests cryptography

# 1. 准备配置
cp config.example.json config.local.json
# 编辑 config.local.json：填表单四参数、cookie、location

# 2. 验证（不提交）
python standalone/cli.py --config config.local.json --dry-run

# 3. 真跑一次
python standalone/cli.py --config config.local.json
```

### 把结果推到微信

在 `config.local.json` 里填 `webhook_url`：

| 服务 | 填什么 | 效果 |
|---|---|---|
| Server酱 | `https://sctapi.ftqq.com/<你的SENDKEY>.send` | 推到微信 |
| PushPlus | `http://www.pushplus.plus/send?token=<你的token>` | 推到微信 |
| Bark | `https://api.day.app/<你的key>` | 推到 iPhone |
| 自定义 | 任意 URL | 收到 JSON `{title, text, content}` |

代码见 `adapters/webhook.py`：Server酱 / PushPlus 走表单 `{title, desp}`，其余走 JSON。

### 定时

```cron
5 8 * * *  cd /opt/xuexit && python3 standalone/cli.py --config config.local.json >> run.log 2>&1
40 8 * * * cd /opt/xuexit && python3 standalone/cli.py --config config.local.json >> run.log 2>&1
```

第二条是兜底：已提交的会自动跳过，不会重复提交。

---

## 4. 路线 B：AstrBot + QQ 官方机器人

AstrBot 官方文档推荐这条，更稳定。

```text
1. 起 AstrBot（见 README「快速开始」第 1 步）
2. q.qq.com 开放平台创建机器人，拿到 AppID / AppSecret
3. AstrBot WebUI → 机器人 → 创建机器人 → 选「QQ 官方机器人」
4. 填 AppID / AppSecret，保存
5. 在 QQ 里私聊这个机器人发一句话，能收到回复就通了
```

> 官方机器人**不能主动私聊陌生人**：对方必须先跟它说过话，你才能给它发消息。
> 所以配推送会话之前，先让本人私聊机器人发一句 `/checkin_bind`。

---

## 5. 路线 C：AstrBot + OneBot v11 协议端

### 5.1 方向别搞反

**AstrBot 做服务端，协议端做客户端**（反向 WebSocket）。

```text
NapCat ──主动连接──▶ AstrBot:6199/ws
```

不是 AstrBot 去连 NapCat。填反了会一直连不上。

### 5.2 AstrBot 侧

```text
WebUI → 左边栏「机器人」→ 创建机器人 → 选 OneBot v11
  ID                        随意，用于区分实例
  启用                       勾上
  反向 WebSocket 主机地址     0.0.0.0
  反向 WebSocket 端口         6199（默认）
  反向 WebSocket Token       只有协议端设了 token 才填
→ 保存
```

对应的 URL 是 `ws://<你的主机>:6199/ws`。

### 5.3 协议端侧（以 NapCat 为例）

```text
1. 按 NapCat 官方文档部署（一键脚本或 Docker）
2. 打开 NapCat WebUI（默认 6099 端口；地址在它的启动日志里）
3. 扫码登录一个 QQ 号
4. 网络配置 → 新建 → WebSockets 客户端
     启用   勾上
     URL    ws://127.0.0.1:6199/ws
            （同一台机器）
            ws://<AstrBot所在机器IP>:6199/ws（分机部署）
            ws://astrbot:6199/ws（同一 docker compose 网络）
     心跳/重连间隔  1000 毫秒
→ 保存
```

> 具体命令与镜像名请以 NapCat 官方文档为准，本项目不复制它的部署步骤，避免版本过期。

### 5.4 验证

```text
AstrBot WebUI → 数据与日志 → 日志
出现「aiocqhttp(OneBot v11) 适配器已连接」= 成功
出现「aiocqhttp 适配器已被关闭」= 超时失败，检查 URL 和端口
```

### 5.5 两条注意

- **不要在公网暴露协议端端口。** 需要跨机时走内网或 SSH 隧道。
- **第三方协议端不是腾讯官方实现**，用它登录的 QQ 号存在被限制的风险。
  建议用一个**专门的备用号**，不要挂自己的主号；也不要频繁群发。

---

## 6. 接通之后：配主账号与绑定

```text
1. 用你的 QQ 私聊机器人，发：/checkin_bind
   它会回一串会话标识（UMO），形如 qqbot:FriendMessage:XXXX
2. 复制它 → 面板「⑦ 权限与通知」→「主账号 / 会话」→ 添加
   （也可以用 /whoami 拿 openid，填到「主账号 / openid」，换群也认得你）
3. 面板「⑥ 用户」→「扫码添加用户」→ 填名字 → 本人用学习通 App 扫
4. 面板「⑤ 自检」→ 全绿即可
```

加同学：让对方私聊机器人发 `/checkin_bind` 拿到自己的 UMO，
你在「成员」里加上他，再给他扫码绑定。**默认 `ALLOW_SELF_BIND` 关闭，陌生人不能自己绑。**

---

## 7. 云服务器部署的额外一步

数据中心出口 IP 通常过不了平台对登录环境的常规校验，扫码会失败。
这时需要「登录助手」临时借一次你电脑的家庭宽带 —— 见 [helper/README.md](../helper/README.md)。

**AstrBot 装在自己电脑上的用户完全不需要这一步。**

---

## 8. 排查表

| 现象 | 原因 | 处理 |
|---|---|---|
| 日志里没有「适配器已连接」 | URL/端口填反或填错 | 确认是协议端连 AstrBot 的 `6199/ws` |
| 机器人不回消息 | 消息平台没启用，或没加主账号 | 看面板「⑤ 自检」的主账号白名单一项 |
| 发了命令石沉大海 | 门卫按陌生人处理 | 把 openid 或 UMO 加进名单 |
| 扫码生成不了二维码 | 云服务器出口 IP 问题 | 开登录助手，再点「检测登录通道」 |
| 打卡成功但没收到推送 | 推送会话没配，或对方没先私聊过机器人 | 配「③ 结果发给谁」；让对方先发一句话 |
| 提示「已达上限」 | 今天已提交 | 正常，按成功处理 |
