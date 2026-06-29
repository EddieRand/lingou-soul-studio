#!/usr/bin/env python3
"""Day 5 quick fix test: voice upload + verify persistence"""
import urllib.request, urllib.error, json, os, tempfile

BASE = "http://localhost:8000/api"

def req(method, path, data=None):
    url = f"{BASE}{path}"
    body = json.dumps(data).encode() if data else None
    r = urllib.request.Request(url, data=body, method=method)
    r.add_header("Content-Type", "application/json")
    with urllib.request.urlopen(r, timeout=10) as resp:
        return json.loads(resp.read())

def req_multipart(method, path, fields, files):
    """fields: list of (name, value) tuples
       files: list of (name, filename, content) tuples"""
    boundary = "----WebKitFormBoundary7MA4YWfDk3J6Q6Z5"
    body = b""
    for name, value in fields:
        body += f"--{boundary}\r\n".encode()
        body += f'Content-Disposition: form-data; name="{name}"\r\n\r\n'.encode()
        body += f"{value}\r\n".encode()
    for name, filename, content in files:
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

print("=== Day 5 Voice Upload Test ===\n")

# Get figure id
figs = req("GET", "/figures")
fid = figs[0]["figure_id"] if figs else None
print(f"Using figure: {fid[:8]}...")

# Voice upload
fake_audio = b"RIFF$\x00\x00\x00WAVEfmt \x10\x00\x00\x00\x01\x00\x01\x00@\x1f\x00\x00D\x00\x00\x00\x02\x00\x10\x00data\x00\x00\x00\x00"
try:
    result = req_multipart("POST", "/voice/upload",
        fields=[("figure_id", fid)],
        files=[("audio", "test_recording.wav", fake_audio)]
    )
    vp = result.get("voice_profile", {})
    print(f"voice_status:  {vp.get('voice_status')}  {'✓ pending_clone' if vp.get('voice_status') == 'pending_clone' else '✗'}")
    print(f"clone_status:  {vp.get('clone_status')}  {'✓ pending' if vp.get('clone_status') == 'pending' else '✗'}")
    print(f"voice_mode:    {vp.get('voice_mode')}  {'✓ voice_clone' if vp.get('voice_mode') == 'voice_clone' else '✗'}")
    saved_path = result.get("saved_path", "")
    print(f"saved_path:    {saved_path}")
    exists = os.path.exists(saved_path) if saved_path else False
    print(f"file on disk: {'✓ exists' if exists else '✗ MISSING: ' + saved_path}")
except Exception as e:
    print(f"Error: {e}")

print("\n=== Done ===")
