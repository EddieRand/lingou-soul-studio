# 第 02 步：稳定身份

当前唯一登录方式是用户名（或同一账号的邮箱）加密码。注册用于创建本地受控测试账号；
模拟微信、Apple、短信验证码、直接返回重置令牌的找回密码和公开用户列表均已关闭，
对应路径不再出现在 OpenAPI 中。

## 服务端配置

服务启动必须提供至少 32 字节的私有签名密钥。密钥必须跨重启保持一致，不能提交到仓库：

```bash
cd services/companion-server
.venv/bin/python -c "import secrets; print(secrets.token_urlsafe(48))"
```

把输出填入 `.env`：

```text
LINGOU_JWT_SECRET=<private-random-value>
```

应用会在启动阶段校验配置。缺失或过短时直接启动失败，不会退回仓库内固定密钥。
更换密钥会让此前签发的全部令牌失效。Access token 当前有效期为 24 小时；
`POST /api/auth/logout` 只确认客户端退出，服务端尚未维护撤销表，因此客户端必须立即清理令牌。

默认 CORS 来源只有 `http://localhost:3000` 和 `http://127.0.0.1:3000`。
需要其他开发来源时，用逗号分隔设置 `LINGOU_CORS_ORIGINS`。同源部署无需额外来源。
模型启动预热默认关闭，只有显式设置 `LINGOU_WARMUP_ON_STARTUP=1` 才会发生启动期模型调用。

## HTTP 边界

匿名白名单：

- `GET /`
- `GET /health`
- `POST /api/auth/register`
- `POST /api/auth/login`

除开发期 API 文档和下述设备入口外，其余 `/api/**` HTTP 入口统一要求
`Authorization: Bearer <access_token>`。缺失、畸形、过期、错误用途以及指向不存在用户的令牌
统一返回 `401`，并携带 `WWW-Authenticate: Bearer`。`POST /api/device/events` 使用
`Authorization: Device <credential>`，错误响应携带 `WWW-Authenticate: Device`。
该判断由 ASGI 边界在路由匹配及请求体解析前执行，匿名上传不会先解析或落盘；
路由依赖仍保留为第二层校验，并向业务处理函数提供当前用户。

JWT 的身份来自 `sub=user_id`，并要求 `typ=access`、`iat` 和 `exp`。
密码使用 bcrypt 保存；新密码至少 8 位，UTF-8 编码最多 72 字节，避免依赖库的长度边界产生歧义。
本地 `users.json` 在服务启动、新建及读取时会收紧为仅当前系统用户可读写的 `0600`。
用户名和邮箱共用一个大小写不敏感的登录标识空间，注册时会做跨字段冲突检查；
旧数据若已经存在歧义标识，登录会安全失败，不会按文件顺序猜测账号。

## 浏览器登录恢复

前端启动时先读取本地 token，再调用 `/api/auth/verify` 获取服务端保存的用户信息。
校验完成前受保护页面保持在恢复状态，不会先跳登录页。明确的 `401` 会清理本地身份；
网络错误或服务端 `5xx` 会保留 token 并显示重试，不会把临时故障误判成退出。

全部业务 HTTP 请求都通过统一客户端附加 Bearer。请求返回 `401` 时，只有发起该请求的 token
仍是当前 token 才能清理登录状态，避免旧请求的迟到响应清掉刚刚建立的新会话。

## ASR WebSocket 票据

浏览器先携带 Access token 调用 `POST /api/auth/ws-ticket`，请求中提供本次 `base_id`。
服务端返回 60 秒有效的一次性 JWT，包含用户、用途、底座和唯一 `jti`。

连接 `/api/asr/stream?base_id=...` 时，浏览器通过 `Sec-WebSocket-Protocol` 提供：

- `lingou.asr.v1`
- `lingou.ticket.<short-ticket>`

长期 Access token 不进入 URL。服务端在 ASR 配置检查、会话构造和供应商任务之前完成票据校验及原子消费。
若校验失败，服务端只完成 WebSocket 协议握手并立即关闭，使真实浏览器可以收到身份关闭码；
不会创建业务会话或调用供应商。票据与底座不匹配时关闭码为 `4403`，重放为 `4409`，
其他身份错误为 `4401`。前端收到身份关闭码或异常断开时都会释放麦克风、WebSocket 和音频资源。

同一个底座只能有一个活动语音连接。新连接通过认证后替换旧连接，旧连接收到
`session_replaced` 并以 `4410` 关闭；该关闭码是明确替换，不应触发自动重连。
每个连接使用独立 `session_id`，每轮使用独立 `turn_id`。

用户 JSON 的读改写锁和一次性票据消费表当前都只在单个服务进程内生效，
因此当前部署必须只运行一个 worker。扩展到多 worker 前，应把身份数据与票据消费状态
放入具备事务和原子写入能力的共享存储。

## 设备凭据

`hardware_adapter.serial_bridge` 不再复用用户 Bearer。开发验证时，它调用
`POST /api/device/events`，并通过 `Authorization: Device <credential>` 提供独立的
设备凭据。生产凭据由离线预置命令生成，通过 `--device-credential` 或环境变量
`LINGOU_DEVICE_CREDENTIAL` 提供；请求正文包含 `event_type`、唯一 `event_id` 和
带时区的 `occurred_at`。服务端从凭据映射底座身份，不接受客户端指定 owner。
非 dry-run 模式还必须显式传入 `--base-id`，缺少任一项都会在打开串口前失败。

生产事件 ID 在每个底座最近 128 条窗口内去重，时间戳超出服务器前后 5 分钟会被拒绝。
解绑后设备凭据因底座没有 owner 而立即失效；重新绑定后恢复。用户可以显式永久撤销该凭据，
撤销后需要重新安全预置，不能通过重新扫码恢复。

独立语音载体使用同一设备身份连接 `WS(S) /api/asr/device-stream`，但服务端额外要求
`voice:stream` 权限、`lingou.device.voice.v1` 子协议、已认领底座及当前角色。
设备凭据只能访问设备事件和设备语音，不能访问角色、记忆或其他用户 HTTP API。
旧凭据不会自动扩权，需通过离线 `scripts.rotate_device_credential` 显式轮换。

测试设备凭据仍可由 `LINGOU_TEST_DEVICE_CREDENTIAL` 提供，但只有服务端显式设置
`LINGOU_ENABLE_TEST_DEVICE_AUTH=1` 时有效，并可省略事件 ID 和时间戳。它具有
`events:write`、`voice:stream` 两项设备域权限，仅用于隔离开发验证。

## 隔离验证

```bash
cd services/companion-server
.venv/bin/python -B tests/test_baseline.py
.venv/bin/python -B tests/test_auth_security.py

cd ../../apps/soul-studio-h5
npm run test:auth
npm run build
```

认证测试使用临时数据目录、测试专用密钥和假 provider，不读取真实 `.env`、既有用户数据或模型密钥。
第 03 步的角色、底座、历史、同步和音频 owner 规则及离线迁移流程见
[统一数据归属](data-ownership.md)。
