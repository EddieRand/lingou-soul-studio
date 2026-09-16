# 第 03 步：统一数据归属

## 归属规则

登录用户的 `user_id` 是角色、事件、对话记录、同步队列、云端快照和上传音频的唯一归属依据。
业务接口只从已验证的 Bearer token 取得这个值，不接受请求正文、查询参数或路径中的用户 ID。
底座保存在共享索引目录，但运行时的唯一规范 owner 字段是 `owner_user_id`，记录必须带有
`schema_version: 2`。存储层暂时同步写入值一致的 `bound_user_id` 兼容字段，但接口不会向客户端暴露或接受它；底座上的当前角色也必须属于同一用户。

运行时目录如下：

```text
data/
├── bases/<base_id>.json
└── user_data/<owner_user_id>/
    ├── figures/<figure_id>.json
    ├── events/<YYYY-MM>.json
    ├── dialogue_logs/<YYYY-MM>.json
    ├── sync/sync_queue.json
    ├── sync/cloud_data.json
    └── voice_uploads/<figure_id>/...
```

资源 ID 只允许 1 至 128 个 ASCII 字母、数字、下划线或连字符，并且首字符必须是字母或数字。
运行时不从旧的全局 `figures/`、`events/`、`dialogue_logs/` 或 `sync_queue/` 回退读取；没有 owner
的旧记录也不会因为某个用户先访问就自动归到该用户名下。跨用户访问和资源不存在使用相同的
未找到结果，避免泄露另一个账号是否拥有这个 ID。

同一个 `figure_id` 可以分别存在于两个用户的目录中。需要落盘的语音池与缓存使用
`SHA-256(owner_user_id)` 的截断前缀和 `figure_id` 组成存储键，防止两个账号共享音频或缓存。
音色克隆读取参考音频时，会再次验证真实文件位于当前 owner 和当前 figure 的
`voice_uploads` 目录中；缺失文件、其他角色或账号的文件、符号链接越界及任意绝对路径均被拒绝。

物理底座先以无 owner 的预置记录存在。二维码认领成功后才写入 `owner_user_id`；
解绑会清除 owner、当前灵偶以及角色上的 `base_id`，但保留不可公开的工厂身份哈希。
创建并激活、切换当前灵偶和解绑涉及多个 JSON 文件时，先写入 `data/.transactions/`
redo journal；正常完成后删除，若进程中断则在下次启动或重试前完成剩余写入。

## 为什么旧数据不能自动认领

旧数据中存在全局角色、全局日志、无 owner 底座，以及相同角色 ID 出现在多个用户目录且内容不同的情况。
文件名、底座当前角色或最近登录用户都不足以证明数据属于谁。自动选择任何一个用户都会把另一个人的
记忆或角色暴露给错误账号。因此旧数据迁移只能由操作者根据外部证据逐项登记归属。

迁移工具是离线工具，不是 HTTP API，也不会被服务启动流程调用：

```text
services/companion-server/scripts/ownership_migration.py
```

不要直接对唯一一份生产数据试运行。先停止服务并复制整个数据目录，在副本上完成清点、人工核对、
dry-run 和验收；保留迁移前备份，确认结果后再安排正式迁移窗口。

## 1. 只做清点

`inventory` 是默认命令。它只输出源相对路径、字节数、SHA-256 和推断出的目标类型，
`owner_user_id` 固定为 `null`，不会猜测归属，也不会创建迁移账本或运行时目标文件。

```bash
cd services/companion-server
python -B -m scripts.ownership_migration \
  --data-dir /absolute/path/to/copied-data \
  --output /absolute/path/to/inventory.json
```

当前会清点以下旧路径：

| 旧路径 | 目标类型 | 正常目标 |
|---|---|---|
| `figures/<id>.json` | `figure` | `user_data/<owner>/figures/<id>.json` |
| `bases/<id>.json` | `base` | `bases/<id>.json` |
| `events/<YYYY-MM>.json` | `events` | `user_data/<owner>/events/<YYYY-MM>.json` |
| `dialogue_logs/<YYYY-MM>.json` | `dialogue_logs` | `user_data/<owner>/dialogue_logs/<YYYY-MM>.json` |
| `sync_queue/sync_queue.json` | `sync_queue` | `user_data/<owner>/sync/sync_queue.json` |
| `voice_uploads/<figure_id>/<file>` | `voice_upload` | `user_data/<owner>/voice_uploads/<figure_id>/<file>` |
| `user_data/<旧目录名>/figures/<id>.json` | `figure` | `user_data/<人工确认 owner>/figures/<id>.json` |
| `user_data/<旧目录名>/{events,dialogue_logs}/<YYYY-MM>.json` | `events` / `dialogue_logs` | 对应 owner 的月度目录 |
| `user_data/<旧目录名>/sync/{sync_queue,cloud_data}.json` | `sync_queue` / `cloud_data` | 对应 owner 的 `sync/` 目录 |

工具也会清点 `cloud_data/*.json`。已经带有正确 `schema_version: 2` 和规范 owner 的
`user_data/` JSON 会被跳过；目录名只作为旧路径的一部分展示，`owner_user_id` 仍固定为 `null`，
不会被当作归属证据。已分目录但未写 owner 的旧文件需要和全局旧文件一样人工确认。

清点结果是供人工审核的报告，包含 `size_bytes` 和 `review_status`，不能直接传给 `apply`。
操作者必须删去这些报告字段、逐项填入经过核实且已经存在于同一数据目录 `users.json` 中的用户 ID，
形成严格的迁移清单。这样可以防止把“生成清单”误当成“确认归属”。

## 2. 编写显式迁移清单

清单只接受固定字段，任何遗漏或额外字段都会拒绝：

```json
{
  "schema_version": 1,
  "entries": [
    {
      "source": "figures/FIG-001.json",
      "owner_user_id": "USER-001",
      "sha256": "填写清点报告中的64位小写SHA-256",
      "target": {
        "type": "figure",
        "id": "FIG-001"
      }
    },
    {
      "source": "events/2026-09.json",
      "owner_user_id": "USER-001",
      "sha256": "填写清点报告中的64位小写SHA-256",
      "target": {
        "type": "events",
        "id": "2026-09"
      }
    }
  ]
}
```

每一项同时锁定：

- 数据根目录内的源相对路径；绝对路径、`..`、符号链接越界均被拒绝。
- `users.json` 中已经注册的 owner；不存在或格式错误的用户被拒绝。
- 源文件的精确 SHA-256；人工核对后文件发生一字节变化也会被拒绝。
- 允许的目标类型与 ID；源目录必须与目标类型对应，同一源文件只能分配一次，重复源或重复目标都被拒绝。

源记录如果已经声明了不同 owner、目标已有不同内容、目标或迁移账本路径通过符号链接越界，
都会在写入第一项之前被拒绝。提交前还会再次读取并比对全部源文件；清点后发生变化时整份清单会在首次写入前终止。

## 3. dry-run

即使使用 `apply` 并提供清单，缺少 `--commit` 时也只做完整校验和计划输出：

```bash
python -B -m scripts.ownership_migration apply \
  --data-dir /absolute/path/to/copied-data \
  --manifest /absolute/path/to/reviewed-manifest.json \
  --output /absolute/path/to/dry-run-result.json
```

只有全部项目均为 `ready` 或已确认的 `already_applied` 时，才应进入写入阶段。
`recover_ledger` 表示目标内容与预期逐字节一致、但账本缺项，提交时只补账本；仍应先核查发生原因。

## 4. 显式提交并复验

提交必须额外提供 `--commit`：

```bash
python -B -m scripts.ownership_migration apply \
  --data-dir /absolute/path/to/copied-data \
  --manifest /absolute/path/to/reviewed-manifest.json \
  --commit \
  --output /absolute/path/to/apply-result.json
```

每个输出文件都会先以 `0600` 权限写入同目录临时文件，执行 `fsync` 后再原子替换。
角色、事件、日志、同步和声音上传在目标路径不同于源路径时会保留源文件。旧底座以及已经位于目标目录的
无 owner JSON 需要原地写入；写入 owner 前，工具会把其精确字节按内容哈希保存到：

```text
data/.ownership_migration/legacy_sources/<source_sha256>/<原相对路径>
```

工具不会删除这些旧文件或归档。完成记录写入
`data/.ownership_migration/ledger.json`；同一份清单再次运行时会校验目标哈希并返回
`already_applied`，不会追加重复记录。已经完成的目标若被修改则安全失败，需要先调查数据变更，
不能通过改清单哈希绕过。账本还会锁定完成项的源路径与目标路径；同一源文件不能在另一份清单中
改分配给其他 owner，同一目标也不能由另一项覆盖。上述冲突在 dry-run 与提交模式都会在首次写入前拒绝。

在副本提交后至少检查：

1. 每个目标的 `owner_user_id` 与人工登记一致，底座的 `bound_user_id` 也一致。
2. 月度事件和对话数组中的每一条记录均带 owner；同步队列中的每一项也带 owner。
3. 原全局文件仍存在，底座原字节归档可按 SHA-256 复核。
4. 再次运行同一清单全部返回 `already_applied`。
5. 使用两个测试账号验证账号 A 不能读取、激活或同步账号 B 的资源。

## 隔离测试

迁移测试只在临时目录创建伪造用户和伪造旧数据，不读取或修改项目根目录下的真实 `data/`：

```bash
cd services/companion-server
python -B tests/test_ownership_migration.py
```

测试覆盖默认清点、已分目录旧数据、apply 默认 dry-run、显式提交、重复执行、原地迁移旧字节归档、声音文件逐字节复制、逐条 owner 写入，
以及未注册 owner、非法 ID、路径穿越、符号链接越界、哈希或提交前源文件变化、已有 owner、目标冲突、重复源和重复目标的拒绝。
