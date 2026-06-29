#!/usr/bin/env python3
import urllib.request, json

BASE = "http://localhost:8000/api"

def req(method, path, data=None):
    url = f"{BASE}{path}"
    body = json.dumps(data).encode() if data else None
    r = urllib.request.Request(url, data=body, method=method)
    r.add_header("Content-Type", "application/json")
    with urllib.request.urlopen(r, timeout=20) as resp:
        return json.loads(resp.read())

figs = req("GET", "/figures")
fid = figs[0]["figure_id"]
print(f"Figure: {fid[:8]}")

# Design first
d = req("POST", "/voice/design", {"figure_id": fid, "speaker": "zh_male_beijingxiaoye_emo_v2_mars_bigtts"})
print(f"Design OK: speaker={d['voice_profile']['speaker']} tts_engine={d['voice_profile']['tts_engine']}")

# Generate (this will print debug to uvicorn console)
print("Calling generate... (check uvicorn terminal for DEBUG output)")
result = req("POST", "/voice/generate", {"figure_id": fid, "text": "你好"})
print(f"engine={result['engine']} success={result['success']} audio_path={str(result.get('audio_path',''))[:50]}")
import os
if result.get("audio_path"):
    print("file exists:", os.path.exists(result["audio_path"]))
    print("file size:", os.path.getsize(result["audio_path"]) if os.path.exists(result["audio_path"]) else "N/A")
