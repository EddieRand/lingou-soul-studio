"""Populate the canonical CSV from this run's explicit evidence mapping."""
from pathlib import Path
import csv
import datetime
import os

ROOT = Path(__file__).resolve().parents[3]
CSV = ROOT / "docs/mvp-test-execution.csv"
RUN = os.getenv("LINGOU_VALIDATION_RUN_ID", "mvp-20260916-02")
STAMP = datetime.datetime.now(datetime.timezone.utc).isoformat()
E = f"docs/validation/{RUN}/"
OLD_BROWSER = "docs/validation/mvp-20260916-01/browser-results.json"


def entry(result, actual, evidence, defect=""):
    return result, actual, evidence, defect


PASS = {
    "E2E-06": entry("通过", "前端源码本轮未修改；自动路径与生产构建重跑通过，上一轮桌面 H5 证据确认单角色入口及旧开发路由回首页。", E+"baseline-test_flow.log; "+E+"baseline-build.log; "+OLD_BROWSER),
    "AUTH-01": entry("通过", "用户名和邮箱登录得到同一 user_id；verify 重复成功且响应不含密码字段。", E+"api-results.json"),
    "AUTH-02": entry("通过", "用户名 1/50 边界成功、空白/51 失败；密码 8/72 字节成功、7/73 失败；并发注册仅一个成功。", E+"api-results.json"),
    "AUTH-03": entry("通过", "无、过期、篡改及 Device-as-user 均返回 401；错误登录不枚举账号。", E+"api-results.json"),
    "AUTH-05": entry("通过", "一次性票据、重放、错误底座、过期和错误传递方式由隔离身份套件覆盖。", E+"baseline-test_auth_security.log"),
    "PAIR-02": entry("通过", "5 类无效/伪造认领码均拒绝，原合法码仍能认领。", E+"api-results.json"),
    "PAIR-03": entry("通过", "A/B 并发认领恰有一个 200、一个 409；成功方三次重放幂等。", E+"api-results.json"),
    "PAIR-04": entry("通过", "已有底座时第二底座返回 409；解绑后可认领。", E+"api-results.json"),
    "PAIR-05": entry("通过", "解绑持久化、角色保留、设备旧身份失权由隔离回归覆盖。", E+"baseline-test_pairing_activation.log"),
    "PAIR-06": entry("通过", "双向跨 owner 激活均 404，伪造 owner 字段 422，原激活关系不变。", E+"api-results.json"),
    "CREATE-03": entry("通过", "前端草稿自动探针本轮重跑通过；上一轮桌面浏览器确认刷新恢复并只创建一个角色。", E+"baseline-test_flow.log; "+OLD_BROWSER),
    "CREATE-06": entry("通过", "丢弃首个成功响应后以同一请求重试，最终角色数为 1 且激活一致。", E+"api-results.json"),
    "CREATE-08": entry("通过", "已有当前角色的恢复决策自动探针本轮重跑通过；上一轮浏览器确认 /create 重定向 /home。", E+"baseline-test_flow.log; "+OLD_BROWSER),
    "PERSONA-04": entry("通过", "稀疏人设使用中性称呼且不注入开发期名字，隔离人设套件通过。", E+"baseline-test_persona_dialogue.log"),
    "PERSONA-05": entry("通过", "文字和语音共用一次完成路径，session/turn 及日志增量由隔离套件覆盖。", E+"baseline-test_persona_dialogue.log"),
    "MEMORY-02": entry("通过", "候选确认前不进入 persona prompt，确认后进入。", E+"api-results.json"),
    "MEMORY-05": entry("通过", "第 10 条成功，第 11 条及满额确认返回 409；删除一条后确认成功。", E+"api-results.json"),
    "MEMORY-07": entry("通过", "10 路并发新增全部成功，异 memory 及同 memory 并发编辑后结构完整、数量仍为 10。", E+"api-results.json"),
    "MEMORY-08": entry("通过", "长对话提交不会覆盖并发记忆更新，由原子合并定向回归覆盖。", E+"baseline-test_memory.log"),
    "MEMORY-09": entry("通过", "B 对 A 的读/增/改/删/确认均 404，伪造 owner 422，A 数据不变。", E+"api-results.json"),
    "MEMORY-10": entry("通过", "候选提取不阻塞、最近 6 轮窗口及旧摘要停用由隔离套件覆盖。", E+"baseline-test_memory.log"),
    "OUTPUT-03": entry("通过", "空音频与浏览器无可交付音频不报成功，无服务器扬声器回退。", E+"baseline-test_audio_delivery.log"),
    "OUTPUT-05": entry("通过", "不回播放回执时约 30 秒进入 audio_failed；显式失败和后续恢复由音频套件覆盖。", E+"session-results.json; "+E+"baseline-test_audio_delivery.log"),
    "DEVAUTH-01": entry("通过", "设备凭据服务端推导 owner/base，设备轮次复用同一对话与记忆入口。", E+"baseline-test_device_voice.log"),
    "DEVAUTH-02": entry("通过", "缺失、篡改、Bearer 和缺 voice scope 均关闭 4401，未进入 provider 检查。", E+"api-results.json"),
    "DEVAUTH-03": entry("通过", "未认领 4401、未激活 4404，激活后可进入 provider 状态。", E+"api-results.json"),
    "DEVAUTH-04": entry("通过", "轮换后旧凭据 WS 4401/HTTP 401，新凭据可握手，当前角色不变。", E+"api-results.json"),
    "DEVAUTH-06": entry("通过", "Device 或把设备 secret 放 Bearer 均不能调用角色、同步、记忆及他人试听入口。", E+"api-results.json"),
    "DEVAUTH-08": entry("通过", "默认测试入口 404；显式开关后可签发；关闭开关后该测试凭据失效。", E+"api-results.json"),
    "CANCEL-01": entry("通过", "提交前取消关闭模型流、抑制迟到输出且不落盘，由语音轮次套件覆盖。", E+"baseline-test_voice_turns.log"),
    "PROTOCOL-01": entry("通过", "9000 字节按 4096/4096/808 有序传输，字节摘要一致且只完成一次。", E+"protocol-results.json"),
    "PROTOCOL-02": entry("通过", "无描述符、长度不匹配、连续描述符均拒绝且未播放。", E+"protocol-results.json"),
    "UX-03": entry("通过", "默认调试写接口返回 404 且无状态修改；前端源码未变，沿用上一轮旧路由回首页的桌面证据。", E+"baseline-test_primary_flow.log; "+OLD_BROWSER),
    "UX-04": entry("通过", "默认对话/触摸不执行关系、streak、冷落或递进，persona 不注入后置规则。", E+"baseline-test_primary_flow.log"),
}

FIXED_PASS = {
    "DEVAUTH-05": entry("通过", "撤销、轮换、解绑后，存量 WS 的下一条 PCM 均在进入 ASR 前触发复验失败并以 4401 关闭。", E+"session-results.json"),
    "CARRIER-01": entry("通过", "显式索引 0/1 完成 16 kHz 采集、24 kHz 播放和一轮真实声学闭环；25 个输入帧均为 640 字节。", E+"audio-smoke.json; "+E+"live-acoustic.md"),
    "CARRIER-07": entry("通过", "部分初始化失败会关闭已创建输入流；PTY SIGTERM 2 秒内退出；真实声学轮次清理正常。", E+"session-results.json; "+E+"live-acoustic.md"),
    "CANCEL-02": entry("通过", "descriptor 后取消会保留丢弃标记，迟到 binary 被安全消费且不播放。", E+"protocol-results.json"),
    "CANCEL-03": entry("通过", "中段取消后同一 turn/audio 的迟到分片不播放且不回传 completed。", E+"protocol-results.json"),
    "CANCEL-05": entry("通过", "旧 turn 的 stop_audio 不停止或清空当前新轮。", E+"protocol-results.json"),
    "RECOVER-03": entry("通过", "正常 1000 关闭也执行退避，0.4 秒窗口连接次数不超过 2。", E+"protocol-results.json"),
    "RECOVER-08": entry("通过", "新 session 建立前清除旧 final/reply/audio_id 和完成事件。", E+"protocol-results.json"),
    "PROTOCOL-03": entry("通过", "仅接受 24 kHz mono s16le、偶数字节且每帧不超过 4096；所有非法变体拒绝。", E+"protocol-results.json"),
    "PROTOCOL-04": entry("通过", "缺帧、重复、乱序、越界和中途改变 count 均拒绝且不产生虚假完成。", E+"protocol-results.json"),
    "PROTOCOL-05": entry("通过", "旧 session 音频被消费但不播放、不回执，也不能覆盖当前 session。", E+"protocol-results.json"),
    "PROTOCOL-06": entry("通过", "回执严格按 decoded→playback_started→terminal 迁移；乱序、重复及冲突终态幂等拒绝。", E+"session-results.json"),
    "PROTOCOL-08": entry("通过", "播放进入独立可取消队列，400 ms 慢输出期间 stop_audio 在 100 ms 观察窗口内生效。", E+"protocol-results.json"),
}

FIXED_BLOCK = {
    "E2E-05": entry("阻塞", "取消、旧帧隔离和重连退避的受控子项已通过；仍缺 T3 三轮对话加断网 30 秒恢复的综合录音与日志。", E+"protocol-results.json"),
    "CARRIER-05": entry("阻塞", "真实扬声器→麦克风脚本已多次完成且清理正常；仍缺测试定义要求的真人连续 3 轮对照，自动脚本不能替代。", E+"live-acoustic.md"),
}

BLOCK_REASON = {
    "E2E": "缺少完整 T3 独立部署、真人连续操作或本轮真实声学成功证据。",
    "AUTH": "需要同浏览器双账号残留或活动 H5 语音退出资源证据，本轮未满足全部前置。",
    "PAIR": "需要摄像头扫码、UI 存储故障或删除当前角色的完整端到端证据。",
    "CREATE": "需要逐变体 UI、浏览器进程关闭、localStorage 故障或双标签真实操作。",
    "PERSONA": "需要真实 H5/设备多次语义抽样或 provider 故障注入，当前仅有隔离逻辑证据。",
    "MEMORY": "缺少真实跨端语义问答、重启/旧历史窗口或 DOM 特殊字符的全部证据。",
    "H5VOICE": "隔离 UI 的 ASR 状态不可用，真实 H5 麦克风/WS/权限/后台场景未执行。",
    "OUTPUT": "缺少本轮真实 H5 试听、末声同步录音或系统输出路由切换证据。",
    "DEVAUTH": "该用例仍缺未知消息或完整运行态证据。",
    "CARRIER": "缺少对应 USB 热插拔、权限拒绝、半双工或后台信号完整实测。",
    "CANCEL": "缺少规定轮数、多端 T3 竞争或提交边界的完整执行证据。",
    "RECOVER": "缺少 T3 网络/DNS/TLS/provider/慢链路的受控故障环境。",
    "PROTOCOL": "缺少超大消息/非法 JSON 或该用例要求的完整受控协议证据。",
    "STARTUP": "未在实际 Linux systemd 或 macOS launchd 环境安装并冷启动服务；模板测试不能代替。",
    "UX": "缺少移动端、键盘无障碍、保存失败或多浏览器真实环境。",
}


def main():
    with CSV.open(encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
        fields = list(rows[0])
    for row in rows:
        cid = row["用例编号"]
        if row["阶段"] != "当前MVP（第01—11步）":
            continue
        if cid in FIXED_PASS:
            result, actual, evidence, defect = FIXED_PASS[cid]
        elif cid in FIXED_BLOCK:
            result, actual, evidence, defect = FIXED_BLOCK[cid]
        elif cid in PASS:
            result, actual, evidence, defect = PASS[cid]
        else:
            prefix = cid.rsplit("-", 1)[0]
            result, actual, evidence, defect = (
                "阻塞",
                BLOCK_REASON[prefix],
                E+"manifest.json",
                "",
            )
        row.update({
            "环境与设备": "T1 隔离逻辑 + T2 macOS 26.6.2 / MacBook Pro 内置声卡（按实际覆盖）",
            "源码版本或快照": "HEAD a68b2bffd734eaaca658d380fd364f91c9733afa + manifest.json 中未提交源码 SHA-256",
            "运行编号": RUN,
            "结果": result,
            "实际结果": actual,
            "证据路径": evidence,
            "缺陷编号": defect,
            "执行人": "TRAE",
            "执行时间": STAMP,
            "备注": "未覆盖的子场景不外推为通过。",
        })
    tmp = CSV.with_suffix(".csv.tmp")
    with tmp.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)
    tmp.replace(CSV)
    totals = {}
    for row in rows:
        totals[row["结果"]] = totals.get(row["结果"], 0) + 1
    print(totals)
    assert totals.get("未执行") == 10
    assert totals.get("失败", 0) == 0
    assert totals.get("通过") == len(PASS) + len(FIXED_PASS)
    assert totals.get("阻塞") == 63


if __name__ == "__main__":
    main()
