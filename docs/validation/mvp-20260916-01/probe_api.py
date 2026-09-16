"""API/WS acceptance variants against a temporary in-process FastAPI instance."""
import asyncio
from concurrent.futures import ThreadPoolExecutor
from contextlib import ExitStack
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import secrets
import subprocess
import sys
import tempfile
import threading
import traceback
from unittest.mock import AsyncMock, patch
import uuid

ROOT = Path(__file__).resolve().parents[3]
SERVER = ROOT / "services/companion-server"
OUT = Path(os.getenv(
    "LINGOU_VALIDATION_OUT",
    str(Path(__file__).resolve().parent),
))
OUT.mkdir(parents=True, exist_ok=True)
sys.path.insert(0, str(SERVER))
sys.path.insert(0, str(ROOT))
temp = tempfile.TemporaryDirectory(prefix="lingou-qa-api-")
environment = {k: v for k, v in os.environ.items() if k in ("PATH", "HOME", "TMPDIR")}
environment.update(LINGOU_DATA_DIR=temp.name, LINGOU_LOAD_DOTENV="0",
                   LINGOU_WARMUP_ON_STARTUP="0", LINGOU_JWT_SECRET="qa-only-secret-with-at-least-32-bytes",
                   LINGOU_ENABLE_DEV_TOOLS="0", LINGOU_ENABLE_TEST_DEVICE_AUTH="0")
os.environ.clear()
os.environ.update(environment)
from fastapi.testclient import TestClient
from app.main import app
from app.api import auth, asr, device_auth
from app.core import memory_engine as memory, persona_builder
from data import store
import jwt

results = json.loads((OUT / "api-results.json").read_text()) if "--memory-retry" in sys.argv else []
http = TestClient(app, raise_server_exceptions=False)


def save(case, observation, passed=True, coverage="API scope"):
    results.append({"case": case, "passed": passed, "coverage": coverage,
                    "observation": observation, "time": datetime.now(timezone.utc).isoformat()})
    (OUT / "api-results.json").write_text(json.dumps(results, ensure_ascii=False, indent=2))
    print(case, "PASS" if passed else "FAIL", flush=True)


def case(name):
    def outer(fn):
        def wrapped():
            try:
                observations = fn()
                save(name, observations)
            except Exception as exc:
                save(name, {"error": str(exc), "trace": traceback.format_exc()}, False)
        return wrapped
    return outer


def expect(value, expected):
    assert value == expected, f"actual={value!r}; expected={expected!r}"


def account():
    name = "qa-" + uuid.uuid4().hex
    payload = {"username": name, "email": name + "@example.com", "password": "qa-fiction-only"}
    response = http.post("/api/auth/register", json=payload)
    expect(response.status_code, 200)
    token = http.post("/api/auth/login", data={"username": name, "password": payload["password"]}).json()
    return dict(owner=response.json()["user_id"], headers={"Authorization": "Bearer " + token["access_token"]},
                token=token["access_token"], payload=payload)


def provision():
    base = "BASE-QA-" + uuid.uuid4().hex
    qr = base + "." + secrets.token_urlsafe(32)
    device = base + "." + secrets.token_urlsafe(32)
    store.provision_base(base, pairing_token=qr, device_credential=device)
    return base, qr, device


def pair(a, qr):
    return http.post("/api/bases/pair", json={"qr_token": "lingou://pair?token=" + qr}, headers=a["headers"])


def fixture(active=True):
    a = account()
    a["base"], a["qr"], a["device"] = provision()
    expect(pair(a, a["qr"]).status_code, 200)
    if active:
        response = http.post("/api/figures", headers=a["headers"], json={
            "name": "阿澈", "figure_type": "soul",
            "creation_request_id": "qa-" + uuid.uuid4().hex, "activate_base_id": a["base"],
            "soul_profile": {"name": "阿澈", "archetype": "温和伙伴", "one_line": "温和简洁，中文回答"},
        })
        expect(response.status_code, 200)
        a["figure"] = response.json()["figure_id"]
    return a


def memory_url(a):
    return f"/api/figures/{a['figure']}/memories"


def add(a, content):
    return http.post(memory_url(a), headers=a["headers"], json={"content": content})


def memories(a):
    return http.get(memory_url(a), headers=a["headers"]).json()


def ws_result(credential, protocols=None, query=""):
    with http.websocket_connect("/api/asr/device-stream" + query,
            headers={"Authorization": credential},
            subprotocols=protocols if protocols is not None else [asr.DEVICE_WS_PROTOCOL]) as ws:
        return ws.receive()


@case("AUTH-01")
def auth_one():
    a = account()
    email_login = http.post("/api/auth/login", data={
        "username": a["payload"]["email"], "password": a["payload"]["password"]})
    expect(email_login.status_code, 200)
    expect(email_login.json()["user_id"], a["owner"])
    for _ in range(2):
        response = http.get("/api/auth/verify", headers=a["headers"])
        expect(response.status_code, 200)
        assert "password" not in response.text
    return {"username_email_same_owner": True, "verify_twice": 200, "browser_refresh": "not included"}


@case("AUTH-02")
def auth_boundaries():
    observations = []
    variations = [
        ("blank username", " ", "12345678", 422),
        ("1 char username", "q", "12345678", 200),
        ("50 chars username", "q"*50, "12345678", 200),
        ("51 chars username", "q"*51, "12345678", 422),
        ("7 char password", None, "1"*7, 422),
        ("8 char password", None, "1"*8, 200),
        ("72 bytes password", None, "中"*24, 200),
        ("73 bytes password", None, "中"*24+"a", 422),
    ]
    for label, name, password, status in variations:
        unique = "qa-" + uuid.uuid4().hex
        response = http.post("/api/auth/register", json={"username": name or unique,
                   "email": unique+"@example.com", "password": password})
        observations.append({"variant": label, "status": response.status_code})
        expect(response.status_code, status)
    response = http.post("/api/auth/register", json={"username": uuid.uuid4().hex, "email": "invalid", "password": "12345678"})
    expect(response.status_code, 422)
    payload = {"username": "race-"+uuid.uuid4().hex, "email": uuid.uuid4().hex+"@example.com", "password": "12345678"}
    with ThreadPoolExecutor(2) as pool:
        codes = list(pool.map(lambda _: http.post("/api/auth/register", json=payload).status_code, range(2)))
    expect(codes.count(200), 1)
    return {"boundaries": observations, "invalid_email": 422, "concurrent_codes": codes}


@case("AUTH-03")
def invalid_tokens():
    a = fixture()
    expired = jwt.encode({"sub": a["owner"], "typ": auth.ACCESS_TOKEN_TYPE,
                          "iat": datetime.now(timezone.utc)-timedelta(hours=2),
                          "exp": datetime.now(timezone.utc)-timedelta(hours=1)}, os.environ["LINGOU_JWT_SECRET"], algorithm="HS256")
    codes = []
    for header in [{}, {"Authorization": "Bearer "+expired},
                   {"Authorization": "Bearer "+a["token"]+"broken"},
                   {"Authorization": "Device "+a["device"]}]:
        codes.append(http.get("/api/figures", headers=header).status_code)
    expect(codes, [401]*4)
    bad = http.post("/api/auth/login", data={"username": a["payload"]["username"], "password": "wrong"})
    absent = http.post("/api/auth/login", data={"username": "absent-user", "password": "wrong"})
    expect(bad.json(), absent.json())
    return {"codes": codes, "error_does_not_enumerate": True, "environment": "all provider credentials absent"}


@case("PAIR-02")
def bad_qr():
    a = account()
    base, qr, _ = provision()
    values = ["", "https://example.com", qr[:10], base+"."+"x"*43, "../base."+"x"*43]
    codes = [http.post("/api/bases/pair", headers=a["headers"], json={"qr_token": v}).status_code for v in values]
    assert all(c in (400,422) for c in codes), codes
    expect(store.base_owner_id(store.get_base(base)), None)
    expect(pair(a, qr).status_code, 200)
    return {"invalid_codes": codes, "original_valid_code_still_works": True}


@case("PAIR-03")
def pairing_race():
    a,b = account(),account()
    base,qr,_ = provision()
    with ThreadPoolExecutor(2) as pool:
        codes = list(pool.map(lambda u: pair(u, qr).status_code, [a,b]))
    expect(sorted(codes), [200,409])
    winner = [a,b][codes.index(200)]
    loser = [a,b][codes.index(409)]
    replays = [pair(winner, qr).status_code for _ in range(3)]
    expect(replays,[200]*3)
    expect(pair(loser,qr).status_code,409)
    expect(store.base_owner_id(store.get_base(base)),winner["owner"])
    return {"race":codes,"replays":replays,"owner_unique":True}


@case("PAIR-04")
def second_base():
    a = fixture()
    base,qr,_ = provision()
    expect(pair(a,qr).status_code,409)
    expect(http.post(f"/api/bases/{a['base']}/unbind",headers=a["headers"]).status_code,200)
    expect(pair(a,qr).status_code,200)
    return {"before_unbind":409,"after_unbind":200}


@case("PAIR-06")
def foreign_activation():
    a,b=fixture(),fixture()
    codes=[]
    for base,figure in [(a["base"],b["figure"]),(b["base"],a["figure"])]:
        codes.append(http.post(f"/api/bases/{base}/active-figure", headers=a["headers"], json={"figure_id":figure}).status_code)
    expect(codes,[404,404])
    extra = http.post(f"/api/bases/{a['base']}/active-figure",headers=a["headers"],json={"figure_id":a["figure"],"owner_user_id":b["owner"]})
    expect(extra.status_code,422)
    for u in (a,b): expect(store.get_base(u["base"])["active_figure_id"],u["figure"])
    return {"foreign_codes":codes,"forged_owner":422,"unchanged":True}


@case("CREATE-06")
def lost_create_response():
    a=fixture(active=False)
    payload={"name":"阿澈","figure_type":"soul","creation_request_id":uuid.uuid4().hex,"activate_base_id":a["base"]}
    # The test client deliberately discards the first successful response.
    http.post("/api/figures",headers=a["headers"],json=payload)
    response=http.post("/api/figures",headers=a["headers"],json=payload)
    expect(response.status_code,200)
    saved=store.list_figures(user_id=a["owner"])
    expect(len(saved),1)
    expect(store.get_base(a["base"])["active_figure_id"],saved[0]["figure_id"])
    return {"discarded_first_response":True,"retry_code":200,"figure_count":1,"scope":"HTTP retry, UI pending"}


@case("MEMORY-02")
def candidate():
    a=fixture()
    memory.add_memory_candidate(a["figure"],"用户周末喜欢骑车",source_turn_id="qa-turn",user_id=a["owner"])
    rows=memories(a)
    expect(len(rows["candidates"]),1)
    prompt=persona_builder.build_persona_prompt(store.get_figure(a["figure"],user_id=a["owner"]))
    assert "骑车" not in prompt
    mid=rows["candidates"][0]["memory_id"]
    response=http.post(memory_url(a)+"/"+mid+"/confirm",headers=a["headers"])
    expect(response.status_code,200)
    prompt=persona_builder.build_persona_prompt(store.get_figure(a["figure"],user_id=a["owner"]))
    assert "骑车" in prompt
    return {"candidate_excluded_before_confirmation":True,"confirmed_prompt_contains_fact":True}


@case("MEMORY-05")
def memory_limit():
    a=fixture()
    for i in range(10): expect(add(a,f"用户测试偏好编号{i}").status_code,201)
    expect(add(a,"用户第十一条偏好").status_code,409)
    memory.add_memory_candidate(a["figure"],"用户另一个候选偏好",source_turn_id="turn-c",user_id=a["owner"])
    rows=memories(a)
    mid=rows["candidates"][0]["memory_id"]
    expect(http.post(memory_url(a)+"/"+mid+"/confirm",headers=a["headers"]).status_code,409)
    delete_id=rows["confirmed_facts"][0]["memory_id"]
    expect(http.delete(memory_url(a)+"/"+delete_id,headers=a["headers"]).status_code,204)
    expect(http.post(memory_url(a)+"/"+mid+"/confirm",headers=a["headers"]).status_code,200)
    expect(len(memories(a)["confirmed_facts"]),10)
    return {"max":10,"11th":409,"confirm_when_full":409,"confirm_after_delete":200}


@case("MEMORY-06")
def memory_boundaries():
    a=fixture()
    variants=[("",422),("   ",400),("a",201),("长"*120,201),("长"*121,422),
              ("用户\n喜欢🐱",201),("<script>alert(1)</script>",201)]
    codes=[]
    for content,status in variants:
        response=add(a,content)
        codes.append(response.status_code)
        expect(response.status_code,status)
    first=add(a,"用户喜欢蓝色").json()["memory"]["memory_id"]
    repeat=add(a,"用户喜欢蓝色")
    expect(repeat.json()["created"],False)
    second=add(a,"用户喜欢绿色").json()["memory"]["memory_id"]
    expect(http.put(memory_url(a)+"/"+second,headers=a["headers"],json={"content":"用户喜欢蓝色"}).status_code,409)
    return {"codes":codes,"duplicate_created":False,"update_conflict":409,"DOM_rendering":"pending browser"}


@case("MEMORY-07")
def memory_concurrency():
    a=fixture()
    with ThreadPoolExecutor(10) as pool:
        codes=list(pool.map(lambda i:add(a,f"用户并发测试偏好{i}").status_code,range(10)))
    expect(codes,[201]*10)
    rows=memories(a)["confirmed_facts"]
    expect(len(rows),10)
    def update(pair):
        mid,content=pair
        return http.put(memory_url(a)+"/"+mid,headers=a["headers"],json={"content":content}).status_code
    with ThreadPoolExecutor(2) as pool:
        diff=list(pool.map(update,[(rows[0]["memory_id"],"用户新偏好一"),(rows[1]["memory_id"],"用户新偏好二")]))
        same=list(pool.map(update,[(rows[0]["memory_id"],"同条偏好甲"),(rows[0]["memory_id"],"同条偏好乙")]))
    expect(diff,[200,200]);expect(same,[200,200])
    final=memories(a)["confirmed_facts"]
    expect(len(final),10)
    return {"concurrent_create":codes,"different_updates":diff,"same_updates":same,"final_count":10}


@case("MEMORY-09")
def foreign_memory():
    a,b=fixture(),fixture()
    aid=add(a,"用户喜欢蓝色").json()["memory"]["memory_id"]
    bid=add(b,"用户喜欢橙色").json()["memory"]["memory_id"]
    memory.add_memory_candidate(a["figure"],"用户喜欢骑车",source_turn_id="turn",user_id=a["owner"])
    candidate_id=memories(a)["candidates"][0]["memory_id"]
    before=memories(a)
    calls=[("GET",memory_url(a),None),("POST",memory_url(a),{"content":"forged"}),
           ("PUT",memory_url(a)+"/"+aid,{"content":"forged"}),("DELETE",memory_url(a)+"/"+aid,None),
           ("POST",memory_url(a)+"/"+candidate_id+"/confirm",None)]
    codes=[http.request(m,u,headers=b["headers"],json=j).status_code for m,u,j in calls]
    expect(codes,[404]*5)
    expect(http.delete(memory_url(a)+"/"+bid,headers=a["headers"]).status_code,404)
    expect(http.post(memory_url(a),headers=a["headers"],json={"content":"x","owner_user_id":b["owner"]}).status_code,422)
    expect(memories(a),before)
    return {"foreign_methods":codes,"cross_figure_memory_id":404,"extra_owner":422,"unchanged":True}


@case("DEVAUTH-02")
def wrong_device_auth():
    a=fixture()
    creds=["", "Device "+a["device"]+"broken","Bearer "+a["token"]]
    with patch.object(asr,"is_asr_available",side_effect=AssertionError("provider check reached")):
        codes=[ws_result(c)["code"] for c in creds]
        base=store.get_base(a["base"]);base["device_credential_scope"]=["events:write"]
        store.save_base(a["base"],base,owner_user_id=a["owner"])
        codes.append(ws_result("Device "+a["device"])["code"])
    expect(codes,[4401]*4)
    return {"close_codes":codes,"provider_check_not_reached":True}


@case("DEVAUTH-03")
def inactive_device():
    base,qr,dev=provision()
    expect(ws_result("Device "+dev)["code"],4401)
    a=account()
    expect(pair(a,qr).status_code,200)
    expect(ws_result("Device "+dev)["code"],4404)
    response=http.post("/api/figures",headers=a["headers"],json={"name":"test","figure_type":"soul","activate_base_id":base,"creation_request_id":uuid.uuid4().hex})
    expect(response.status_code,200)
    with patch.object(asr,"is_asr_available",return_value=False):
        result=ws_result("Device "+dev)
    expect(result["type"],"websocket.send")
    return {"unclaimed":4401,"unactivated":4404,"activated_reaches_provider_status":True}


@case("DEVAUTH-04")
def rotate():
    a=fixture()
    new=a["base"]+"."+secrets.token_urlsafe(32)
    before=store.get_base(a["base"])["active_figure_id"]
    store.rotate_production_device_credential(a["base"],device_credential=new)
    expect(ws_result("Device "+a["device"])["code"],4401)
    expect(http.post("/api/device/events",headers={"Authorization":"Device "+a["device"]},json={"event_type":"light_touch"}).status_code,401)
    with patch.object(asr,"is_asr_available",return_value=False):
        expect(ws_result("Device "+new)["type"],"websocket.send")
    expect(store.get_base(a["base"])["active_figure_id"],before)
    return {"old_ws":4401,"old_http":401,"new_accepted":True,"figure_unchanged":True}


@case("DEVAUTH-06")
def device_user_api():
    a,b=fixture(),fixture()
    rows=[]
    for scheme in ["Device","Bearer"]:
        headers={"Authorization":scheme+" "+a["device"]}
        for method,url,body in [("GET","/api/figures",None),("GET","/api/sync",None),
                 ("GET",memory_url(a),None),("POST",memory_url(a),{"content":"x"}),
                 ("PUT",memory_url(a)+"/missing",{"content":"x"}),("DELETE",memory_url(a)+"/missing",None),
                 ("POST","/api/voice/preview",{"figure_id":b["figure"]})]:
            code=http.request(method,url,headers=headers,json=body).status_code
            expect(code,401)
            rows.append({"scheme":scheme,"method":method,"path":url,"code":code})
    return rows


@case("DEVAUTH-07")
def subprotocols():
    a=fixture()
    with patch.object(asr,"is_asr_available",side_effect=AssertionError("provider reached")):
        codes=[ws_result("Device "+a["device"],p)["code"] for p in [[],["lingou.asr.v1"],["lingou.device.voice.v99"]]]
    expect(codes,[4401]*3)
    return {"protocol_codes":codes,"unknown_message_variants":"separate protocol probe"}


@case("DEVAUTH-08")
def test_credentials():
    a=fixture()
    expect(http.post("/api/bases/test-bases",headers=a["headers"],json={"base_id":"BASE-QA-DEVELOP"}).status_code,404)
    expect(http.post(f"/api/bases/{a['base']}/test-device-credential",headers=a["headers"]).status_code,404)
    with patch.dict(os.environ,{"LINGOU_ENABLE_TEST_DEVICE_AUTH":"1"}):
        issued=http.post(f"/api/bases/{a['base']}/test-device-credential",headers=a["headers"])
        expect(issued.status_code,200)
        credential=issued.json()["device_credential"]
        assert device_auth.authenticate_device_credential(credential,required_scope="voice:stream")
    expect(device_auth.authenticate_device_credential(credential,required_scope="voice:stream"),None)
    return {"default_test_routes":404,"explicit_test_enabled":200,"disabled_rejects_issued_test_secret":True}


def run():
    funcs=[auth_one,auth_boundaries,invalid_tokens,bad_qr,pairing_race,second_base,foreign_activation,
           lost_create_response,candidate,memory_limit,memory_boundaries,memory_concurrency,foreign_memory,
           wrong_device_auth,inactive_device,rotate,device_user_api,subprotocols,test_credentials]
    if "--memory-retry" in sys.argv:
        funcs = [candidate, memory_limit, foreign_memory]
    with http:
        for fn in funcs: fn()
    temp.cleanup()


if __name__=="__main__":
    run()
