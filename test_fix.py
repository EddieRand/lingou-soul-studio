#!/usr/bin/env python3
import urllib.request, json

BASE = "http://localhost:8000/api"

def req(method, path, data=None):
    url = f"{BASE}{path}"
    body = json.dumps(data).encode() if data else None
    r = urllib.request.Request(url, data=body, method=method)
    r.add_header("Content-Type", "application/json")
    with urllib.request.urlopen(r, timeout=15) as resp:
        return json.loads(resp.read())

print("=== Bug Fix Verification ===\n")

# 1. Brain status - dotenv loaded
s = req("GET", "/brain/status?base_id=BASE-001")
print(f"1. api_key_set:   {s.get('api_key_set')}   {'✓' if s.get('api_key_set') else '✗ MISSING'}")
print(f"   endpoint_id_set: {s.get('endpoint_id_set')}  {'✓' if s.get('endpoint_id_set') else '✗ MISSING'}")

# 2. Figure exists
figs = req("GET", "/figures")
if not figs:
    fig = req("POST", "/figures", {
        "name": "傲傲", "figure_type": "二次元手办", "wake_names": ["傲傲"],
        "soul_profile": {"archetype": "傲娇吐槽型", "name": "傲傲", "address_user_as": "你"}
    })
    fid = fig["figure_id"]
    req("POST", "/bases", {"base_id": "BASE-001"})
    req("POST", "/bases/BASE-001/bind", {"bound_user_id": "u"})
    req("POST", "/bases/BASE-001/active-figure", {"figure_id": fid})
    print(f"2. Created figure: {fid[:8]}")
else:
    fid = figs[0]["figure_id"]
    print(f"2. Using figure: {fid[:8]}")

# 3. online mode + real Doubao call
req("POST", "/brain/mode?base_id=BASE-001", {"mode": "online"})
resp = req("POST", "/dialogue/text", {
    "base_id": "BASE-001",
    "text": "我今天心情很低落，可以陪我说说话吗"
})
mode = resp.get("brain_mode", "?")
reply = resp.get("reply", "")
online_ok = mode == "online"
print(f"\n3. brain_mode:  {mode}  {'✓ ONLINE - Doubao called!' if online_ok else '✗ expected online'}")
print(f"   reply:       「{reply[:60]}...」" if len(reply) > 60 else f"   reply:       「{reply}」")
print(f"   real Doubao: {'✓ YES' if online_ok and len(reply) > 0 else '✗ NO'}")

# Offline fallback already verified from Day4 test (network errors gracefully fallback)
print("\n=== Verification Complete ===")
