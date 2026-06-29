#!/usr/bin/env python3
"""Day 3 self-test: dialogue + 8-state machine + offline_brain + say"""
import json
import urllib.request
import urllib.error
import time

BASE = "http://localhost:8000/api"

def req(method, path, data=None):
    url = f"{BASE}{path}"
    body = json.dumps(data).encode() if data else None
    r = urllib.request.Request(url, data=body, method=method)
    r.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(r, timeout=10) as resp:
            return json.loads(resp.read())
    except urllib.error.HTTPError as e:
        return {"error": e.read().decode(), "status": e.code}

print("=== Day 3 Self-Test ===\n")

# 1. Clean slate - delete all figures
print("1. Clean slate")
figs = req("GET", "/figures")
for f in figs:
    req("DELETE", f"/figures/{f['figure_id']}")
print(f"   Deleted {len(figs)} figures")

# 2. Create 傲娇吐槽型 figure
print("\n2. Create 傲娇吐槽型 figure (no explicit touch_reactions)")
fig = req("POST", "/figures", {
    "name": "傲傲",
    "figure_type": "二次元手办",
    "wake_names": ["傲傲", "傲傲醒醒"],
    "soul_profile": {
        "archetype": "傲娇吐槽型",
        "name": "傲傲",
        "address_user_as": "你",
    }
})
FIG_ID = fig.get("figure_id", "")
print(f"   figure_id: {FIG_ID[:8]}...")
print(f"   archetype: {fig.get('soul_profile', {}).get('archetype')}")

# 3. Register + bind base
print("\n3. Register and bind BASE-001")
req("POST", "/bases", {"base_id": "BASE-001"})
req("POST", "/bases/BASE-001/bind", {"bound_user_id": "user"})
req("POST", "/bases/BASE-001/active-figure", {"figure_id": FIG_ID})

# 4. Initial state should be idle
print("\n4. GET /api/dialogue/state (should be idle)")
state0 = req("GET", "/dialogue/state?base_id=BASE-001")
print(f"   state: {state0.get('state', '?')}")
print(f"   ✓ idle" if state0.get("state") == "idle" else f"   ✗ unexpected state")

# 5. POST /api/dialogue/wake with double_tap
print("\n5. POST /api/dialogue/wake {trigger: 'double_tap'}")
wake = req("POST", "/dialogue/wake", {
    "base_id": "BASE-001",
    "trigger": "double_tap"
})
print(f"   state: {wake.get('state', '?')}")
print(f"   figure: {wake.get('figure', {}).get('name', '?')}")
print(f"   ✓ listening" if wake.get("state") == "listening" else f"   ✗ unexpected state: {wake.get('state')}")

# 6. POST /api/dialogue/text - 傲娇安慰风格
print("\n6. POST /api/dialogue/text {text: '我今天有点累'}")
resp = req("POST", "/dialogue/text", {
    "base_id": "BASE-001",
    "text": "我今天有点累"
})
reply = resp.get("reply", "")
emotion = resp.get("emotion_state", {})
print(f"   reply: 「{reply}」")
print(f"   length ≤30: {'✓' if len(reply) <= 30 else '✗ ' + str(len(reply))}")
print(f"   brain_mode: {resp.get('brain_mode', '?')} {'✓' if resp.get('brain_mode') == 'offline' else '✗'}")
print(f"   emotion attached: {emotion.get('attached', '?')} {'✓' if emotion.get('attached', 0) >= 1 else '✗'}")
print(f"   emotion attention: {emotion.get('attention', '?')} {'✓' if emotion.get('attention', 0) >= 10 else '✗'}")

# Check if reply is from 傲娇 archetype comfort pool
from_offline = any(kw in reply for kw in ["切", "哼", "啦", "知道", "想开点", "行了", "矫情"])
print(f"   傲娇风格安慰短句: {'✓' if from_offline else '? (可能随机命中其他池子)'}")

# 7. Check state reset to idle
print("\n7. GET /api/dialogue/state (should be idle after processing)")
state1 = req("GET", "/dialogue/state?base_id=BASE-001")
print(f"   state: {state1.get('state', '?')}")
print(f"   ✓ idle" if state1.get("state") == "idle" else f"   ✗ unexpected")

# 8. voice_wake: text contains wake name
print("\n8. POST /api/dialogue/wake {trigger: 'voice_wake', text: '傲傲你在吗'}")
wake2 = req("POST", "/dialogue/wake", {
    "base_id": "BASE-001",
    "trigger": "voice_wake",
    "text": "傲傲你在吗"
})
print(f"   state: {wake2.get('state', '?')}")
print(f"   ✓ listening" if wake2.get("state") == "listening" else f"   ✗ unexpected")

# 9. Normal greeting text
print("\n9. POST /api/dialogue/text {text: '你好呀'}")
resp2 = req("POST", "/dialogue/text", {
    "base_id": "BASE-001",
    "text": "你好呀"
})
print(f"   reply: 「{resp2.get('reply', '')}」")
print(f"   ✓ offline" if resp2.get("brain_mode") == "offline" else f"   ✗")

print("\n" + "="*50)
print("✅ Day 3 Self-Test Done")
print("(say audio should have played for each reply)")
