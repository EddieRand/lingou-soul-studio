#!/usr/bin/env python3
"""Bug fix verification: archetype drives replies, emotion at soul_profile.emotion_state"""
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

# Clean slate: delete all existing figures and bases
print("=== Clean slate ===")
figs = req("GET", "/figures")
for f in figs:
    req("DELETE", f"/figures/{f['figure_id']}")
    print(f"  deleted {f['name']}")

# Create figureA: archetype=御姐照顾型, NO explicit touch_reactions
print("\n=== Create figureA (御姐照顾型) - no explicit touch_reactions ===")
figA = req("POST", "/figures", {
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
            "speaking_style": "casual"
        }
    }
})
print(f"  figureA id: {figA.get('figure_id', '?')[:8]}")
# Verify: touch_reactions come from archetype template
print(f"  light_touch from archetype template: {figA.get('touch_reactions', {}).get('light_touch', [])}")
print(f"  soul_profile.persona.response_templates.light_touch: {figA.get('soul_profile', {}).get('persona', {}).get('response_templates', {}).get('light_touch', [])}")
print(f"  soul_profile.emotion_state (Bug2 - should exist): {figA.get('soul_profile', {}).get('emotion_state', 'MISSING')}")
print(f"  soul_profile.persona.emotion_state (Bug2 - should NOT exist): {'persona' in figA.get('soul_profile', {}) and 'emotion_state' in figA.get('soul_profile', {}).get('persona', {})}")
print(f"  system_voice_name from archetype: {figA.get('voice_profile', {}).get('system_voice_name')}")

# Create figureB: archetype=傲娇吐槽型, NO explicit touch_reactions
print("\n=== Create figureB (傲娇吐槽型) - no explicit touch_reactions ===")
figB = req("POST", "/figures", {
    "name": "傲傲",
    "figure_type": "二次元手办",
    "wake_names": ["傲傲"],
    "soul_profile": {
        "archetype": "傲娇吐槽型",
        "name": "傲傲",
        "address_user_as": "你"
    }
})
print(f"  figureB id: {figB.get('figure_id', '?')[:8]}")
print(f"  light_touch from archetype template: {figB.get('touch_reactions', {}).get('light_touch', [])}")

# Register + bind base
req("POST", "/bases", {"base_id": "BASE-001"})
req("POST", "/bases/BASE-001/bind", {"bound_user_id": "user_default"})

# Set figureA as active, light_touch
print("\n=== figureA light_touch ===")
req("POST", "/bases/BASE-001/active-figure", {"figure_id": figA["figure_id"]})
respA = req("POST", "/events", {"base_id": "BASE-001", "event_type": "light_touch"})
print(f"  reply: {respA.get('reply', '?')}")

# Verify reply is from 御姐 archetype's light_touch list
archetypes_raw = req("GET", "/souls/archetypes")
yejia_tmpl = next((a for a in archetypes_raw if a["archetype"] == "御姐照顾型"), None)
print(f"  Expected from archetypes.json: {yejia_tmpl.get('response_templates', {}).get('light_touch', []) if yejia_tmpl else '?'}")
in_template_A = respA.get('reply', '') in yejia_tmpl.get('response_templates', {}).get('light_touch', []) if yejia_tmpl else False
print(f"  Reply from archetype template: {'✓' if in_template_A else '✗ (NOT from template!)'}")

# Switch to figureB, light_touch
print("\n=== figureB light_touch ===")
req("POST", "/bases/BASE-001/active-figure", {"figure_id": figB["figure_id"]})
respB = req("POST", "/events", {"base_id": "BASE-001", "event_type": "light_touch"})
print(f"  reply: {respB.get('reply', '?')}")

aoxiao_tmpl = next((a for a in archetypes_raw if a["archetype"] == "傲娇吐槽型"), None)
print(f"  Expected from archetypes.json: {aoxiao_tmpl.get('response_templates', {}).get('light_touch', []) if aoxiao_tmpl else '?'}")
in_template_B = respB.get('reply', '') in aoxiao_tmpl.get('response_templates', {}).get('light_touch', []) if aoxiao_tmpl else False
print(f"  Reply from archetype template: {'✓' if in_template_B else '✗ (NOT from template!)'}")

print(f"\n=== Core verification: figureA vs figureB replies DIFFERENT ===")
different = respA.get('reply', '') != respB.get('reply', '')
print(f"  reply different: {'✓' if different else '✗ SAME REPLY!'}")

# Emotion delta test (Bug 2: emotion_state at soul_profile.emotion_state)
print("\n=== Emotion delta (light_touch: happy+5, attached+2) ===")
req("POST", "/bases/BASE-001/active-figure", {"figure_id": figA["figure_id"]})
figA_before = req("GET", f"/figures/{figA['figure_id']}")
mood_before = figA_before.get("soul_profile", {}).get("emotion_state", {})
print(f"  Before: {mood_before}")
resp_c = req("POST", "/events", {"base_id": "BASE-001", "event_type": "light_touch"})
mood_after = resp_c.get("mood", {})
print(f"  After:  {mood_after}")
h_ok = mood_after.get("happy", 0) == mood_before.get("happy", 0) + 5
a_ok = mood_after.get("attached", 0) == mood_before.get("attached", 0) + 2
print(f"  happy +5: {'✓' if h_ok else '✗'}")
print(f"  attached +2: {'✓' if a_ok else '✗'}")

# heavy_press annoyed +8
print("\n=== Emotion delta (heavy_press: annoyed+8) ===")
figA_fresh = req("GET", f"/figures/{figA['figure_id']}")
mood_fresh = figA_fresh.get("soul_profile", {}).get("emotion_state", {})
resp_d = req("POST", "/events", {"base_id": "BASE-001", "event_type": "heavy_press"})
mood_d = resp_d.get("mood", {})
ann_ok = mood_d.get("annoyed", 0) == mood_fresh.get("annoyed", 0) + 8
print(f"  annoyed +8: {'✓' if ann_ok else '✗'}")

print("\n" + "="*50)
if different and in_template_A and in_template_B and h_ok and a_ok and ann_ok:
    print("✅ ALL TESTS PASSED - Bug fixes verified!")
else:
    print("❌ SOME TESTS FAILED")
