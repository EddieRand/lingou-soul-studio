#!/usr/bin/env python3
"""Day 5 self-test: EventLog/DialogueLog persistence + memory-summary + sync queue + voice upload"""
import urllib.request, json, os, tempfile

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

def req_file(method, path, files=None):
    import urllib.request, io
    boundary = "----WebKitFormBoundary"
    body = b""
    for name, filename, content in (files or []):
        body += f"--{boundary}\r\n".encode()
        body += f'Content-Disposition: form-data; name="{name}"; filename="{filename}"\r\n'.encode()
        body += b"Content-Type: audio/wav\r\n\r\n"
        body += content + b"\r\n"
    body += f"--{boundary}--\r\n".encode()
    url = f"{BASE}{path}"
    r = urllib.request.Request(url, data=body, method=method)
    r.add_header("Content-Type", f"multipart/form-data; boundary={boundary}")
    with urllib.request.urlopen(r, timeout=10) as resp:
        return json.loads(resp.read())

print("=== Day 5 Self-Test ===\n")

# 1. Setup - ensure figure exists
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
    print(f"1. Created figure: {fid[:8]}")
else:
    fid = figs[0]["figure_id"]
    print(f"1. Using figure: {fid[:8]}")

# 2. Trigger events + dialogue to generate logs
print("\n2. Trigger touch events...")
for evt in ["light_touch", "heavy_press"]:
    req("POST", "/events", {"base_id": "BASE-001", "event_type": evt})

print("\n3. Trigger dialogue...")
req("POST", "/brain/mode?base_id=BASE-001", {"mode": "offline"})
req("POST", "/dialogue/text", {"base_id": "BASE-001", "text": "你好呀傲傲"})

# 4. Verify event logs
print("\n4. GET /api/events/logs")
logs = req("GET", f"/events/logs?base_id=BASE-001&limit=10")
print(f"   count: {len(logs)}  {'✓' if len(logs) >= 2 else '✗ need >= 2'}")
if logs:
    e0 = logs[0]
    has_fields = all(k in e0 for k in ["event_id","base_id","figure_id","event_type","reply","mood_before","mood_after","triggered_at"])
    print(f"   all fields: {'✓' if has_fields else '✗'}")
    print(f"   mood_before != mood_after: {'✓' if e0.get('mood_before') != e0.get('mood_after') else '✗ same'}")
    print(f"   sample: {e0.get('event_type')} → 「{e0.get('reply')[:20]}」")

# 5. Verify dialogue logs
print("\n5. GET /api/dialogue/logs")
dlogs = req("GET", f"/dialogue/logs?figure_id={fid}&limit=10")
print(f"   count: {len(dlogs)}  {'✓' if len(dlogs) >= 1 else '✗ need >= 1'}")
if dlogs:
    dl = dlogs[0]
    has_fields = all(k in dl for k in ["dialogue_id","figure_id","base_id","wake_source","user_input_text","reply_text","brain_mode"])
    print(f"   all fields: {'✓' if has_fields else '✗'}")
    print(f"   sample: 「{dl.get('user_input_text')}」→ 「{dl.get('reply_text')[:20]}」")

# 6. Memory summary
print("\n6. POST /api/dialogue/memory-summary")
summary = req("POST", "/dialogue/memory-summary", {"figure_id": fid})
print(f"   summary: {summary.get('summary', '?')}")
print(f"   has summary field: {'✓' if 'summary' in summary else '✗'}")

# Verify memory written back to figure
fig_updated = req("GET", f"/figures/{fid}")
memory = fig_updated.get("memory", {})
print(f"   memory.memory_summary: {memory.get('memory_summary', '?')[:40]}")

# 7. Sync queue
print("\n7. Sync queue - queue + flush")
queue1 = req("POST", "/sync", {"figure_id": fid, "type": "emotion_update", "data": {"happy": 60}})
print(f"   queue items after add: {len(queue1.get('items', []))}  {'✓' if len(queue1.get('items', [])) >= 1 else '✗'}")
pending = [i for i in queue1.get("items", []) if i.get("sync_status") == "pending"]
print(f"   pending count: {len(pending)}  {'✓' if len(pending) >= 1 else '✗'}")

queue2 = req("POST", "/sync/flush")
synced = [i for i in queue2.get("items", []) if i.get("sync_status") == "synced"]
print(f"   synced after flush: {len(synced)}  {'✓' if len(synced) >= 1 else '✗'}")

# 8. Voice upload
print("\n8. POST /api/voice/upload (test audio file)")
# Create a small fake wav file
fake_audio = b"RIFF$\x00\x00\x00WAVEfmt \x10\x00\x00\x00\x01\x00\x01\x00@\x1f\x00\x00D\x00\x00\x00\x02\x00\x10\x00data\x00\x00\x00\x00"
try:
    up = req_file("POST", "/voice/upload", [
        ("figure_id", fid),
        ("audio", "test.wav", fake_audio)
    ])
    vp = up.get("voice_profile", {})
    print(f"   voice_status: {vp.get('voice_status')}  {'✓ pending_clone' if vp.get('voice_status') == 'pending_clone' else '✗'}")
    print(f"   clone_status: {vp.get('clone_status')}  {'✓ pending' if vp.get('clone_status') == 'pending' else '✗'}")
    print(f"   recording_url: {vp.get('recording_url', '')[:50]}")
    saved_path = up.get("saved_path", "")
    import os as _os
    exists = _os.path.exists(saved_path) if saved_path else False
    print(f"   file exists: {'✓' if exists else '✗ ' + saved_path}")
except Exception as e:
    print(f"   error: {e}")

print("\n=== Day 5 Complete ===")
