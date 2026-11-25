# 登录助手（可选）

## 它是干什么的

超星会拦截**云服务器/机房**的 IP，导致服务器打不开登录页、生成不了二维码。
登录助手的作用是：**临时借你电脑的家庭宽带网络**，让服务器完成一次扫码登录。

用完关掉窗口即可，不留任何服务。

## 谁需要它

| 你的情况 | 需要吗 |
|---|---|
| AstrBot 装在自己电脑上 | **不需要**，直接扫码 |
| AstrBot 装在云服务器 | 需要 |
| 只用命令行 + cron | 绑定那一步需要，打卡不需要 |

## 文件说明

```text
login_proxy.py          主程序（纯标准库，不需要 pip 安装）
start-helper.bat        Windows 双击
start-helper.sh         macOS / Linux
helper.example.json     配置样例，复制成 helper.json 后改
```

## 怎么用

1. 复制 `helper.example.json` 为 `helper.json`，把 `server` 改成你的服务器地址：

   ```json
   {
     "server": "root@1.2.3.4",
     "port": 8898,
     "bind": "127.0.0.1",
     "allow": "chaoxing.com,cxstar.com,xuexixing.com",
     "idle_exit": 600,
     "max_life": 3600
   }
   ```

2. Windows 双击 `start-helper.bat`；macOS/Linux：

   ```bash
   chmod +x start-helper.sh && ./start-helper.sh
   ```

3. 窗口会打印一串公钥，复制它 → 打开 AstrBot 面板「登录助手」→ 粘贴 → 提交公钥。
4. 面板点「检测登录通道」，显示 🟢 后即可扫码。
5. 用完关窗口。

## 参数说明

| 字段 | 含义 |
|---|---|
| `server` | SSH 目标，格式 `用户名@公网IP` |
| `port` | 本地与远端端口，默认 8898 |
| `bind` | 远端绑定地址，容器环境填 `127.0.0.1` 即可 |
| `allow` | 允许访问的域名后缀，逗号分隔；留空表示不限制（不建议） |
| `idle_exit` | 空闲多少秒自动退出 |
| `max_life` | 最长运行秒数 |

## 安全说明

- 只允许访问 `chaoxing.com` 等白名单域名，**不能当作通用代理**；
- 只接受 CONNECT（TLS 透传），**不解密、不抓包**；
- 公钥会以受限形式写入服务器：只能开一个端口、不能登录 shell；
- 闲置与超时自动退出，忘记关也不会一直开着；
- **不要把服务器地址发到公开场合**。
