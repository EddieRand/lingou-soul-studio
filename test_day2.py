#!/usr/bin/env python3
"""Day 2 acceptance tests"""
import json
import urllib.request
import urllib.error

BASE = "http://localhost:8000/api"

def req(method, path, data=None):
    url = f"{BASE}{path}"
    body = json.dumps(data).encode() if data else None
    req = urllib.request.Request(url, data=body, method=method)
    req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return json.loads(resp.read())
    except urllib.error.HTTPError as e:
        return {"error": e.read().decode(), "status": e.code}

# 1. GET /api/archetypes
print("=== 验收1: GET /api/archetypes ===")
archs = req("GET", "/souls/archetypes")
print(f"  count: {len(archs)}")
for a in archs:
    tpls = a["response_templates"]
    ok = all(len(tpls[k]) >= 2 for k in ["figure_placed","light_touch","heavy_press","double_tap"])
    print(f"  {a['archetype']}: figure_placed={len(tpls['figure_placed'])} light_touch={len(tpls['light_touch'])} heavy_press={len(tpls['heavy_press'])} double_tap={len(tpls['double_tap'])} {'✓' if ok else '✗'}")

# 2. Create 2 figures with different archetypes
print("\n=== 验收2: 不同 archetype 的 light_touch reply 不同 ===")

# Create 御姐 figure
fig_yejia = req("POST", "/figures", {
    "name": "叶姐",
    "figure_type": "二次元手办",
    "wake_names": ["叶姐"],
    "soul_profile": {
        "archetype": "御姐照顾型",
        "name": "叶姐",
        "address_user_as": "你",
        "persona": {
            "traits": ["温柔"],
            "greeting": "回来了",
            "speaking_style": "casual",
            "response_templates": {
                "figure_placed": ["欢迎回家~"],
                "light_touch": ["乖，别闹~", "姐姐知道了"],
                "heavy_press": ["轻点嘛~"],
                "double_tap": ["什么事呀？"]
            }
        }
    }
})
print(f"  Created 御姐照顾型: {fig_yejia.get('figure_id', '?')[:8]}...")

# Create 傲娇 figure
fig_aoxiao = req("POST", "/figures", {
    "name": "傲傲",
    "figure_type": "二次元手办",
    "wake_names": ["傲傲"],
    "soul_profile": {
        "archetype": "傲娇吐槽型",
        "name": "傲傲",
        "address_user_as": "你",
        "persona": {
            "traits": ["傲娇"],
            "greeting": "哼！",
            "speaking_style": "casual",
            "response_templates": {
                "figure_placed": ["切~"],
                "light_touch": ["动手动脚干嘛啦！", "别乱摸！"],
                "heavy_press": ["喂！你弄疼我了！"],
                "double_tap": ["有话快说。"]
            }
        }
    }
})
print(f"  Created 傲娇吐槽型: {fig_aoxiao.get('figure_id', '?')[:8]}...")

# Set BASE-001 -> 御姐
req("POST", f"/bases/BASE-001/active-figure", {"figure_id": fig_yejia["figure_id"]})

# light_touch 御姐
resp_a = req("POST", "/events", {"base_id": "BASE-001", "event_type": "light_touch"})
print(f"  御姐 light_touch reply: {resp_a.get('reply', '?')}")

# Switch to 傲傲
req("POST", f"/bases/BASE-001/active-figure", {"figure_id": fig_aoxiao["figure_id"]})

# light_touch 傲傲
resp_b = req("POST", "/events", {"base_id": "BASE-001", "event_type": "light_touch"})
print(f"  傲娇 light_touch reply: {resp_b.get('reply', '?')}")

same = resp_a.get('reply') == resp_b.get('reply')
print(f"  reply 不同: {'✓' if not same else '✗ (相同!)'}")

# 3. Mood delta test
print("\n=== 验收3: 情绪增减 ===")

# Switch to 御姐, check baseline
req("POST", f"/bases/BASE-001/active-figure", {"figure_id": fig_yejia["figure_id"]})

# Get current mood
fig_before = req("GET", f"/figures/{fig_yejia['figure_id']}")
mood_before = fig_before.get("soul_profile", {}).get("persona", {}).get("emotion_state", {})
print(f"  御姐 light_touch 前 mood: happy={mood_before.get('happy','?')} attached={mood_before.get('attached','?')}")

# light_touch
resp_c = req("POST", "/events", {"base_id": "BASE-001", "event_type": "light_touch"})
mood_c = resp_c.get("mood", {})
print(f"  御姐 light_touch 后 mood: happy={mood_c.get('happy','?')} attached={mood_c.get('attached','?')}")
print(f"  happy +5: {'✓' if mood_c.get('happy', 0) == mood_before.get('happy', 0) + 5 else '✗'}")
print(f"  attached +2: {'✓' if mood_c.get('attached', 0) == mood_before.get('attached', 0) + 2 else '✗'}")

# Now test heavy_press annoyed +8
# Get fresh mood
fig_fresh = req("GET", f"/figures/{fig_yejia['figure_id']}")
mood_fresh = fig_fresh.get("soul_profile", {}).get("persona", {}).get("emotion_state", {})
print(f"  御姐 heavy_press 前 mood: annoyed={mood_fresh.get('annoyed','?')}")
resp_d = req("POST", "/events", {"base_id": "BASE-001", "event_type": "heavy_press"})
mood_d = resp_d.get("mood", {})
print(f"  御姐 heavy_press 后 mood: annoyed={mood_d.get('annoyed','?')}")
print(f"  annoyed +8: {'✓' if mood_d.get('annoyed', 0) == mood_fresh.get('annoyed', 0) + 8 else '✗'}")

# 4. /hardware/simulate same as /events
print("\n=== 验收4: /hardware/simulate 与 /events 行为一致 ===")
resp_sim = req("POST", "/hardware/simulate", {"base_id": "BASE-001", "event_type": "double_tap"})
print(f"  simulate double_tap reply: {resp_sim.get('reply', '?')}")
print(f"  led_effect: {resp_sim.get('led_effect', '?')}")

# 5. GET /api/archetypes check
print("\n=== 验收5: /api/archetypes 11项4事件齐全 ===")
print(f"  总数: {len(archs)} {'✓' if len(archs)==11 else '✗'}")
all_ok = all(
    all(len(a["response_templates"][k]) >= 2 for k in ["figure_placed","light_touch","heavy_press","double_tap"])
    for a in archs
)
print(f"  所有模板至少2句: {'✓' if all_ok else '✗'}")

print("\n✅ Day 2 验收完成")
