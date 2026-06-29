#!/usr/bin/env python3
"""Day 4 self-test: online_brain / brain_router fallback + wake bug fix"""
import json
import urllib.request
import urllib.error

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
        return {"error": e.read().decode(), "status": e.code, "_http_status": e.code}

print("=== Day 4 Self-Test ===\n")

# 1. Clean slate
print("1. Clean slate")
figs = req("GET", "/figures")
for f in figs:
    req("DELETE", f"/figures/{f['figure_id']}")
print(f"   Deleted {len(figs)} figures")

# 2. Create 傲娇吐槽型 figure
print("\n2. Create 傲娇吐槽型 figure")
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

# 3. Setup base
req("POST", "/bases", {"base_id": "BASE-001"})
req("POST", "/bases/BASE-001/bind", {"bound_user_id": "user"})
req("POST", "/bases/BASE-001/active-figure", {"figure_id": FIG_ID})

# 4. Brain status - no API key
print("\n4. GET /api/brain/status")
status = req("GET", "/brain/status?base_id=BASE-001")
print(f"   has_api_key: {status.get('has_api_key')}  {'✓' if not status.get('has_api_key') else '✗ (should be False!)'}")
print(f"   fallback_reason: {status.get('fallback_reason', 'none')}")

# 5. Long question → brain_router should try online → fail gracefully → offline
print("\n5. Long question (>30 chars) → should gracefully fallback to offline")
resp = req("POST", "/dialogue/text", {
    "base_id": "BASE-001",
    "text": "我今天很累，想和你聊聊关于工作压力的话题"
})
print(f"   reply: 「{resp.get('reply', '')}」")
print(f"   brain_mode: {resp.get('brain_mode', '?')}  {'✓ offline (fallback)' if resp.get('brain_mode') == 'offline' else '✗'}")
print(f"   has reply: {'✓' if resp.get('reply') else '✗ NO REPLY - crashed!'}")

# 6. Realtime keyword → online attempt → fallback
print("\n6. Realtime keyword (今天天气) → graceful offline fallback")
resp2 = req("POST", "/dialogue/text", {
    "base_id": "BASE-001",
    "text": "今天天气怎么样？"
})
print(f"   reply: 「{resp2.get('reply', '')}」")
print(f"   brain_mode: {resp2.get('brain_mode', '?')}  {'✓ offline' if resp2.get('brain_mode') == 'offline' else '✗'}")
print(f"   has reply: {'✓' if resp2.get('reply') else '✗ NO REPLY - crashed!'}")

# 7. Force offline mode
print("\n7. POST /api/brain/mode {mode: 'offline'}")
mode = req("POST", "/brain/mode?base_id=BASE-001", {"mode": "offline"})
print(f"   mode: {mode.get('mode', '?')}")
resp3 = req("POST", "/dialogue/text", {
    "base_id": "BASE-001",
    "text": "你能帮我分析一下股票走势吗"
})
print(f"   brain_mode: {resp3.get('brain_mode', '?')}  {'✓ offline' if resp3.get('brain_mode') == 'offline' else '✗'}")
print(f"   reply: 「{resp3.get('reply', '')}」")

# 8. Reset to auto
req("POST", "/brain/mode?base_id=BASE-001", {"mode": "auto"})

# 9. Wake with non-matching voice_wake text → 200 {woken: False}, NOT 404
print("\n9. Wake with wrong wake name → 200 {woken: False}, NOT 404")
wake = req("POST", "/dialogue/wake", {
    "base_id": "BASE-001",
    "trigger": "voice_wake",
    "text": "小雪你在吗"
})
print(f"   http_status: {wake.get('_http_status', 200)}  {'✓ 200' if wake.get('_http_status', 200) == 200 else '✗ ' + str(wake.get('_http_status'))}")
print(f"   woken: {wake.get('woken', '?')}  {'✓ False' if wake.get('woken') == False else '✗'}")
print(f"   state: {wake.get('state', '?')}  {'✓ idle' if wake.get('state') == 'idle' else '✗'}")

# 10. Correct wake name → woken: True
print("\n10. Correct wake name → woken: True")
wake2 = req("POST", "/dialogue/wake", {
    "base_id": "BASE-001",
    "trigger": "voice_wake",
    "text": "傲傲你在吗"
})
print(f"    woken: {wake2.get('woken', '?')}  {'✓ True' if wake2.get('woken') == True else '✗'}")
print(f"    state: {wake2.get('state', '?')}  {'✓ listening' if wake2.get('state') == 'listening' else '✗'}")

print("\n" + "="*50)
print("✅ Day 4 Self-Test Done")
