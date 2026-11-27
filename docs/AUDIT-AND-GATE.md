# 留痕与门卫（v0.6.0）

这份文档说明两件从界面看不出来的事：**谁会看到什么**、**什么时候留下证据**。
写它的原因是——面板上的「已同意」曾经是空壳：默认值就是 true，从来没人点过，
于是 `CONSENT_AT` 一直是空字符串。看起来一切正常，实际什么都没记下来。

## 1. 操作留痕（audit.jsonl）

位置：插件数据目录，与 `accounts.json` 同级，权限 600。

```text
/AstrBot/data/plugin_data/astrbot_plugin_xuexit_checkin/audit.jsonl
```

记录的动作：

| action | 触发时机 | 记了什么 |
|---|---|---|
| `consent_backfill` | 启动时发现「已同意但无时间」 | 说明这次是补记，不是用户操作 |
| `consent` | 面板上勾选 / 取消 | accept / withdraw |
| `config_change` | 保存设置 | 改了哪几个键、改成了什么 |
| `apply_form_url` | 面板粘贴表单链接并解析 | 解析出的 formId 与 enc 前缀 |
| `check_form_source` | 检查远程表单链接 | 读到的链接 |
| `form_url_refresh` | 远程链接变化并自动换参数 | 新的 formId |
| `set_owner` | 设置账号归属 openid | 账号与归属 |
| `set_contact` | 给名单里的 ID 写备注 | 标识与备注 |
| `health_check` | 面板点「体检」（只读） | 账号与结论 |
| `dry_run` | 面板点「试跑」（不提交） | 账号与结论 |
| `run_now` | 面板点「立即」（真提交） | 账号与分类结果 |
| `checkin_manual` | 聊天里手动打卡 | 账号名与结果 |
| `unbind` | 解绑 | 账号名 |
| `purge_user` | 面板「撤回」删除账号 | 账号名与清掉的状态文件 |
| `gate_deny` | 门卫拦下消息 | 谁、哪条命令、为什么拦 |
| `probe_tunnel` | 每次自检 | 探测地址与结果 |
| `self_check` | 每次自检 | 异常 / 注意 / 正常各几条 |

**不记录**：Cookie 内容、表单字段值、聊天原文。只记动作、对象、结论。

轮转：单文件超过 512 KB 时改名为 `.1`，只保留最近一代。

## 2. 同意时间为什么要补记

`CONSENT_ACCEPTED` 在 schema 里默认 `true`（用户要求默认勾选）。
结果是：插件一装上就是「已同意」，但没人点过，`CONSENT_AT` 永远为空。

两种处理方式：

- 把默认值改成 false → 破坏「装上就能用」的体验；
- 保持默认，但显式补记，并标明来源。

选了后者：`CONSENT_AT_SOURCE=backfill`，面板显示「补记，非本人勾选」。
**不伪造「用户在某时同意过」**。要变成真正的留痕，在面板上重新点一次勾选即可，
来源会变成 `user`，并写入当时的 `CONSENT_VERSION`。

> 合规角度：PIPL 第 14 条要求同意应当自愿、明确。预勾选在面向陌生人时风险较高，
> 因此 `ALLOW_SELF_BIND` 默认关闭；面向同学开放前，建议把默认值改成未勾选。

## 3. 门卫（policy.py）

判定过去散在三处：`cmd_gate` 的白名单、每个命令里的 `_is_admin(umo)`、面板文案。
三者口径不同——例如 `/login` 只按 umo 判断，而管理员可能是靠 openid 名单命中的。

现在收敛成两个纯函数：

```python
identity(umo, sender_id, admin_umos, admin_ids, member_umos) -> (role, reason)
gate(text, role, allow_self_bind=False, member_allow_all=False, bare=False)
    -> {allow, command, role, reason}
```

角色：

| role | 判定条件 |
|---|---|
| `admin` | openid 命中 `ADMIN_IDS`，或会话命中 `ADMIN_UMOS`；两个名单都空时视为「开放模式」（危险，自检会标红） |
| `member` | openid 或会话命中 `MEMBERS`（面板「⑦ 权限与通知」里手工加的名单） |
| `guest` | 其他一切人 |

判定顺序：**openid 优先于会话**——openid 是「人」，umo 是「一段对话」。

放行规则：

| 消息 | admin | member（`MEMBER_ALL` 开） | member（关） | guest |
|---|---|---|---|---|
| `/status` `/whoami` `/checkin_bind` | 放行 | 放行 | 放行 | 放行 |
| `/bind` | 放行 | 放行 | `ALLOW_SELF_BIND` 开才放行 | 同左 |
| `/checkin` `/login` `/unbind` `/notify_test` | 放行 | 放行 | 拦下 | 拦下 |
| 普通聊天 | 放行 | 放行 | 拦下 | 拦下 |

两个开关：

- `ALLOW_SELF_BIND`（默认 **关闭**）：控制非主账号能不能自助 `/bind`。
- `MEMBER_ALL`（默认 **打开**）：打开时成员与主账号同权；关掉后成员只剩三条只读指令。

**已知边界**：

- 「成员」是**手工名单**，不是「已绑定账号」的同义词。绑了账号但没进名单的人，仍按 `guest` 处理。
- 没有邀请码机制：名单靠主账号在面板里手工维护。
- 两个主账号名单都为空时进入「开放模式」，谁都能用全部命令——自检会标红提醒。

## 4. 自助检（面板「自检」）

一次运行会做：

1. **配置检查**：主账号名单、表单 ID / enc / uuid、打卡时间、推送会话、演练与总开关。
2. **账号检查**：数量、是否有过期。
3. **留痕检查**：同意时间是用户勾选还是补记。
4. **通道检查**：先 TCP、再真的走一次代理 HTTP。
   只测 TCP 会误报——`socat` 中继即使电脑那头没上线，也会接受连接。
5. **门卫矩阵**：用同一个 `gate()` 算出四种身份 × 八条命令的放行表。

自检不会真的打卡，也不会修改任何配置。

## 5. 自检输出的判读

| 现象 | 含义 | 处理 |
|---|---|---|
| 主账号白名单 = 异常 | 两个名单都空，任何人都能用全部命令 | 到「权限与通知」补一个 openid |
| 登录通道 = 中继在但出口不通 | 服务器侧中继在，你电脑上的助手没开 | 双击 start-helper，再点自检 |
| 同意留痕 = 补记 | 同意时间不是本人点出来的 | 重新点一次勾选 |
| Chaoxing 账号 = 过期 | Cookie 失效 | 重新扫码 |
