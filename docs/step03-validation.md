# 第 03 步实施与验证报告

日期：2026-09-15。

结论：第 03 步“统一用户、角色、设备的数据归属”在本步约定范围内验证通过。
第 04 步未开始，等待用户单独批准。

## 源码与范围

- 实际续做目录：`/Users/bytedance/Downloads/LINGOU`。
- IDE 原目录 `/Users/bytedance/Documents/trae_projects/LINGOU` 是旧副本，本轮未修改。
- 本轮承接 GPT 已有的 owner 存储、HTTP/WS 授权、测试设备身份及离线迁移实现，不把这些已有改动计为本轮新增。
- 仅验证数据归属及第 01、02 步回归；不实施真实配对、语音轮次重构或长期记忆改造。

## 本轮修改

| 文件 | 改动 |
|---|---|
| `services/companion-server/data/store.py` | 增加参考音频路径校验，只允许当前 owner 和当前角色的上传目录内实际存在的文件 |
| `services/companion-server/app/api/voice.py` | 克隆准备入口校验参考音频；其他用户、其他角色、越界链接和缺失文件返回 404 |
| `services/companion-server/app/core/voxcpm_adapter.py` | 读取及发送参考音频前再次检查作用域，防止直接伪造 ready 档案绕过准备入口；关闭原读取句柄泄漏 |
| `services/companion-server/scripts/ownership_migration.py` | 除清单条目哈希外，再用账本锁定已分配源路径与目标路径，阻止换清单重复分配 |
| `services/companion-server/tests/test_data_ownership.py` | 新增 3 项 API 回归；补充外部网络与播放器进程阻断 |
| `services/companion-server/tests/test_ownership_migration.py` | 新增 2 项迁移回归，验证跨清单拒绝及正常后续迁移 |

文档同步：本报告、`docs/data-ownership.md`、`PLAN.md`，以及原 Codex 输出目录中的 MVP 分步实施清单。

## 缺陷分析与回归证据

1. 参考音频归属绕过：账户 A 可以把自己的 `voice_profile` 指向 B 的音频，再通过克隆准备或直接设置 ready 状态触发读取。
   修复前，准备入口对跨用户、跨角色、越界链接和缺失文件均返回 200；运行时探针观察到假 provider 收到了调用。
   修复后，准备入口返回 404，伪造 ready 路径不读取或发送他人的音频；正常上传与假 provider 合成路径仍通过。
2. 跨清单重复分配：迁移账本原先只识别整条清单的哈希，更换 owner 会形成新条目。
   修复前，同一全局源文件先分配给 A 后，另一份清单仍可写入 B。
   修复后，dry-run 与 commit 均在首次写入前拒绝；原有目标、源文件和账本保持不变。

迁移单测生成流程已执行准备、上下文、范围、缺陷分析、生成验证和报告阶段，并执行 `utree flush`。
生成阶段保留了失败证据，随后在已批准的实现任务中修复生产逻辑，没有删除或放宽失败断言。

## 生成的用例

- `test_completed_source_cannot_be_reassigned_by_a_new_manifest`
- `test_new_source_can_follow_a_completed_manifest`
- `test_clone_start_rejects_foreign_missing_and_symlinked_references`
- `test_forged_ready_clone_cannot_send_another_owners_audio_to_provider`
- `test_own_uploaded_reference_can_be_cloned_with_owner_scoped_output`

## 验证结果

| 验证 | 结果 |
|---|---|
| 第 01 步隔离基线 | 8/8 |
| 第 02 步身份安全，含真实临时 Uvicorn 的 WS 拒绝码 | 18/18 |
| 数据归属及 API 回归 | 10/10 |
| 离线迁移 | 18/18 |
| 串口桥协议，使用假适配器与假 HTTP | 6/6 |
| Python 合计 | 60/60，其中本轮新增 5 项 |
| 前端 `npm run test:auth` | PASS |
| 前端 `npm run build`，含 TypeScript | PASS，58 个模块 |
| Python AST 语法检查 | 55/55 |
| `pip check` | PASS |
| `git diff --check` | PASS |

归属测试确认：A 不能读取、修改、删除或激活 B 的资源；历史和同步按 Bearer 身份隔离；
客户端归属字段不能覆盖服务端身份；测试设备凭据只可写入对应底座事件，不能当用户凭据；
WS 票据在签发及消费时检查底座 owner；同名角色的缓存和队列隔离；40 个并发事件追加不丢失。

本机复现命令：

```bash
cd /Users/bytedance/Downloads/LINGOU
PYTHON=/Users/bytedance/Documents/Codex/2026-09-08/du/work/step-01/runtime-venv/bin/python
"$PYTHON" -B services/companion-server/tests/test_baseline.py
"$PYTHON" -B services/companion-server/tests/test_auth_security.py
"$PYTHON" -B services/companion-server/tests/test_data_ownership.py
"$PYTHON" -B services/companion-server/tests/test_ownership_migration.py
"$PYTHON" -B -m unittest discover -s hardware_adapter/tests -v
"$PYTHON" -m pip check
cd apps/soul-studio-h5
npm run test:auth
npm run build
```

测试使用临时目录和虚构账户，不加载真实 `.env`，不调用真实 ASR、LLM、TTS、麦克风或硬件。
原运行数据共 646 个文件，其相对路径、大小、修改时间和权限的元数据摘要前后相同：
`d0c093a91cecb31dc43b4a3ee5d40bf915742335ba784c5a37f51963604f0959`。
没有执行真实数据迁移，没有暂存或提交 Git，也没有覆盖 GPT 原有未提交变更。

## 边界与下一步

- 测试设备凭据不是生产配对方案。扫码、解绑持久化、设备凭据撤销和防重放留在第 04 步。
- 旧数据未自动认领；原声线引用若仍指向全局旧路径，需要显式处理或重新上传，不能回退读取。
- 当前仍要求单 worker；跨进程存储事务、语音取消与终端播放、记忆可靠性按后续步骤验证。
- 前端认证探针与构建不代替本轮未执行的浏览器交互或实机验收。
- FastAPI 生命周期、部分 datetime 和测试依赖的弃用提示仍存在，本步不升级框架。
- 下一步范围：第 04 步“真实配对与创建激活”。本报告不授予下一步执行许可。
