# 更新记录

## 0.6.0

**权限**
- 三档身份：主账号 / 成员 / 陌生人，判定收敛到 `policy.py`
- 成员可配「全部权限」开关；关闭时只能聊天 + 3 条只读指令
- 陌生人只放行 `/status` `/whoami` `/checkin_bind`，其余消息直接丢弃
- 修复：唤醒前缀被框架吃掉后，裸命令名（`whoami`）认不出来

**安全**
- Cookie 以 Fernet 加密落盘（`enc:v1:` 前缀），密钥 `secret.key` 权限 600
- 撤回账号时一并删除状态文件，避免"删了还在打"
- 恢复门卫生效：默认不允许陌生人自助绑定

**可观测**
- 面板自检 13 项：配置 / 账号 / 同意留痕 / 通道 / 加密 / 成员 / 门卫矩阵
- 操作留痕 `audit.jsonl`：同意、改配置、增删用户、拦人、体检、打卡
- 失败原因八分类（already / cookie / form / config / network / limit / submit / unknown），每条带下一步建议

**功能**
- 面板「粘贴表单链接」一键更新 formId / enc / fidEnc / stateFid
- 面板「体检」（只读）/「试跑」（dry-run）/「立即」（真提交）
- 账号归属 openid：当事人可查自己的账号，也给本人发通知
- 「今天已提交」按成功处理，不再误报失败

**文档**
- `docs/HOWTO-CAPTURE.md` 抓包四条路（抄现成 / 复制链接 / 设备模拟 / 手机抓包）
- `docs/PRIVACY.md`、`docs/DISCLAIMER.md`、`docs/AUDIT-AND-GATE.md`

## 0.5.0

- 统一门卫判定（`policy.py`）、操作留痕（`audit.jsonl`）、面板自检
- 修复：调度缺少 `import time` 导致 NameError
- 修复：重启补跑空转 40 分钟、重复排期

## 0.4.0

- 自动同步表单参数（`last/info`），只覆盖 uuid / version / 模板
- 扫码绑定、多账号、结果推送、幂等跳过
