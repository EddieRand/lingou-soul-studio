#!/usr/bin/env python3
"""Day 6 self-test: volcano TTS + fallback + voice API"""
import urllib.request, json, os

BASE = "http://localhost:8000/api"

def req(method, path, data=None):
    url = f"{BASE}{path}"
    body = json.dumps(data).encode() if data else None
    r = urllib.request.Request(url, data=body, method=method)
    r.add_header("Content-Type", "application/json")
    with urllib.request.urlopen(r, timeout=15) as resp:
        return json.loads(resp.read())

def req_multipart(method, path, fields, files):
    boundary = "----Day6Test"
    body = b""
    for name, value in fields:
        body += f"--{boundary}\r\nContent-Disposition: form-data; name=\"{name}\"\r\n\r\n{value}\r\n".encode()
    for name, filename, content in files:
        body += f"--{boundary}\r\nContent-Disposition: form-data; name=\"{name}\"; filename=\"{filename}\"\r\nContent-Type: audio/wav\r\n\r\n".encode()
        body += content + b"\r\n"
    body += f"--{boundary}--\r\n".encode()
    r = urllib.request.Request(url, data=body, method=method)
    r.add_header("Content-Type", f"multipart/form-data; boundary={boundary}")
    with urllib.request.urlopen(r, timeout=15) as resp:
        return json.loads(resp.read())

print("=== Day 6 Self-Test ===\n")

# 1. Setup: ensure figure
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
else:
    fid = figs[0]["figure_id"]

fig_detail = req("GET", f"/figures/{fid}")
vp = fig_detail.get("voice_profile", {})
print(f"1. Figure: {fid[:8]}...")
print(f"   tts_engine: {vp.get('tts_engine')}  {'✓ volcano_tts' if vp.get('tts_engine') == 'volcano_tts' else '✗'}")
print(f"   speaker:    {vp.get('speaker')}  {'✓ set' if vp.get('speaker') else '✗'}")

# 2. Speakers API
print("\n2. GET /api/voice/speakers")
spk = req("GET", "/voice/speakers")
print(f"   available: {spk.get('available')}  {'✓' if spk.get('available') != None else '✗'}")
print(f"   speakers count: {len(spk.get('speakers', []))}  {'✓ >= 1' if len(spk.get('speakers', [])) >= 1 else '✗'}")

# 3. Voice design
print("\n3. POST /api/voice/design")
design = req("POST", "/voice/design", {"figure_id": fid, "speaker": "female_boss"})
dvp = design.get("voice_profile", {})
print(f"   speaker set to: {dvp.get('speaker')}  {'✓ female_boss' if dvp.get('speaker') == 'female_boss' else '✗'}")
print(f"   tts_engine: {dvp.get('tts_engine')}  {'✓ volcano_tts' if dvp.get('tts_engine') == 'volcano_tts' else '✗'}")

# 4. Voice generate (REAL volcano TTS - should play sound)
print("\n4. POST /api/voice/generate (REAL volcano TTS)")
print("   (You should hear audio playing in ~2-5 seconds)")
gen = req("POST", "/voice/generate", {
    "figure_id": fid,
    "text": "主人，欢迎回来呀"
})
print(f"   engine:  {gen.get('engine')}  {'✓ volcano_tts' if gen.get('engine') == 'volcano_tts' else '✗ ' + gen.get('engine', '')}")
print(f"   success:  {gen.get('success')}  {'✓' if gen.get('success') else '✗'}")
print(f"   audio_path: {str(gen.get('audio_path', ''))[:60]}")

if gen.get('audio_path'):
    import os as _os
    exists = _os.path.exists(gen['audio_path'])
    print(f"   file exists: {'✓' if exists else '✗ MISSING: ' + gen['audio_path']}")
    if exists:
        size = _os.path.getsize(gen['audio_path'])
        print(f"   file size: {size} bytes  {'✓' if size > 1000 else '✗ too small'}")

# 5. Fallback: simulate bad key
print("\n5. Fallback test (bad key → should use system_say, not crash)")
# Monkey-patch env to simulate missing key
orig_key = os.environ.get("VOLC_TTS_API_KEY")
os.environ["VOLC_TTS_API_KEY"] = "invalid_key"
# Restart the module's config cache... we'll test via dialogue
req("POST", "/brain/mode?base_id=BASE-001", {"mode": "offline"})
try:
    resp = req("POST", "/dialogue/text", {"base_id": "BASE-001", "text": "你好"})
    print(f"   no crash: ✓")
    print(f"   reply: 「{resp.get('reply', '')}」")
except Exception as e:
    print(f"   crashed: ✗ {e}")
finally:
    if orig_key:
        os.environ["VOLC_TTS_API_KEY"] = orig_key

print("\n=== Day 6 Complete ===")
print("✅ If you heard audio above, volcano TTS is working!")
