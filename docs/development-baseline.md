# 第 01 步：开发基线与隔离验证

验证平台：macOS arm64，Python 3.12.14，Node 22.23.2，npm 10.9.8。
Python 项目要求为 3.11+，本轮只实际验证了 3.12。系统自带的 Python 3.9 不适用。

## 安装与运行检查

后端从独立虚拟环境安装。`pyproject.toml` 是手工维护的直接依赖来源；
`requirements.txt` 是生成的完整精确版本清单，常规安装不要分别维护两份版本。

```bash
cd services/companion-server
python3.12 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python -m pip check
.venv/bin/python -B tests/test_baseline.py
```

最后一个命令运行 8 项基线检查：真实应用导入与 ASGI 启动、根路由/健康检查/OpenAPI、
临时存储与上传、音频缓存路径、假 provider 注入、认证依赖执行、回环 WebSocket 握手，
以及对外联网和越界数据访问的阻断。无需创建 `.env`、启动现有开发服务或提供模型密钥。

脚本只允许临时目录内写入和回环地址连接，运行前清理继承的配置，禁止读取真实 `.env`
和已有运行数据，禁止启动外部播放器或其他子进程。测试结束自动清理临时数据。
它按显式文件路径运行，不会自动执行项目根目录那些会修改演示数据的旧脚本。

前端保留当前版本与既有 `.npmrc` 策略，用已有锁文件重建：

```bash
cd apps/soul-studio-h5
npm ci
node node_modules/typescript/bin/tsc --noEmit
npm run build
```

构建包含页面直接引用的 5 张既有图片。`.gitignore` 仅放行这些必要资源，其他 public 文件
继续沿用忽略策略。`data/store.py` 也被精确放行，运行数据仍不应加入版本控制。
本次调整只使这些文件可被 Git 跟踪，没有替用户暂存或提交改动；分享仓库前应检查它们与锁文件均已加入提交。

若之前出现 `@rollup/rollup-darwin-arm64` 缺失，先用 `npm ci` 重建安装。
现有锁文件已经包含平台包，无需为了该问题升级 React 或重写前端。

## 隔离配置

| 配置 | 默认行为 | 基线测试使用 |
|---|---|---|
| `LINGOU_DATA_DIR` | 项目根目录的 `data/` | 新建临时目录；用户、角色、历史、上传、同步及音频缓存共用该根目录 |
| `LINGOU_LOAD_DOTENV` | 加载 companion-server 的 `.env` | `0`，跳过文件加载 |
| `LINGOU_WARMUP_ON_STARTUP` | 默认 `0`；显式设为 `1` 才预热在线模型 | `0`，跳过预热 |
| `LINGOU_JWT_SECRET` | JWT 签名密钥，必须至少 32 字节 | 显式测试值；不读取真实密钥 |

两个开关接受 `0`、`false`、`no`、`off`（大小写不敏感）作为关闭值。
目录配置应使用绝对路径，并在导入应用前设置。未设置时仍使用原有数据与音频目录。
开关只控制上述行为；测试脚本另外安装了联网和文件访问保护。仅设置这些环境变量，
不等于给任意业务调用提供了网络隔离。

`LINGOU_DATA_DIR` 管运行数据和音频缓存；现有独立声线目录文件仍按原路由的静态路径读取。
基线不调用该资源接口。声线资源的整理留到其对应步骤。

## 更新后端锁文件

仅需要改变依赖时，在单独的工具环境安装 `pip-tools==7.6.1`，使用 Python 3.12：

```bash
python -m piptools compile --strip-extras --output-file=requirements.txt pyproject.toml
```

命令在 `services/companion-server` 执行；随后用新的空虚拟环境安装 `requirements.txt`，
执行 `pip check` 和基线检查。当前清单在 macOS arm64 生成，包含 uvicorn 的平台依赖；
其他平台需要单独验证，不宣称此轮已完成跨平台验收。

`websockets` 显式约束在支持当前 `additional_headers` 用法的版本范围。
`bcrypt` 暂留 4.x；第 02 步已在注册入口显式限制密码的 UTF-8 编码不超过 72 字节。

## 本步边界与已知待修项

- 环境和基线检查通过，不表示创建、绑定、记忆、语音交互或账号安全已经修复。
- 本文建立时记录的创建激活目录不一致和绑定 Mock 已在第 03、04 步解决；记忆覆盖、摘要停止更新、人设未进入 prompt、TTS 假成功和旧轮覆盖仍保留在后续步骤清单。
- 前端 `liquid-glass-react` 的 peer 声明要求 React 19，项目仍使用 React 18 与原有 `legacy-peer-deps=true`。本轮构建与静态资源通过，组件实际交互兼容性尚未验证。
- FastAPI 的 `on_event` 等接口存在弃用提示，当前锁定组合仍能运行。生命周期重构按后续实际范围处理。
- 没有调用真实模型、打开麦克风、运行实机或触碰原始用户数据。第 02 步已另行完成身份边界验证；资源 owner 统一仍属于第 03 步。
