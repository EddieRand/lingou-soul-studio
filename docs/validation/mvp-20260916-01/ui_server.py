"""Temporary real FastAPI service for browser QA; fictional users, fake providers."""
import json
import os
from pathlib import Path
import uuid

VALIDATION_OUT = os.getenv(
    "LINGOU_VALIDATION_OUT",
    str(Path(__file__).resolve().parent),
)
import probe_api as q
from app.core import dialogue_engine
import uvicorn

OUT = Path(VALIDATION_OUT)
OUT.mkdir(parents=True, exist_ok=True)
username="qa_browser_mvp"
password="qa-fiction-only"
with q.http:
    response=q.http.post("/api/auth/register",json={"username":username,"email":"qa_browser_mvp@example.com","password":password})
    owner=response.json()["user_id"]
base="BASE-QA-BROWSER"
qr=base+"."+"p"*43
q.store.provision_base(base,pairing_token=qr,device_credential=base+"."+"d"*43)
q.store.save_archetypes([{"archetype_id":"gentle","name":"温和伙伴","description":"测试默认模板","persona":{"speaking_style":"简洁"}}])
location={"data_dir":q.temp.name,"username":username,"owner":owner,"base":base,
          "providers":"fake: text-only T1; no live audio proof"}
(OUT/"ui-runtime.json").write_text(json.dumps(location,ensure_ascii=False,indent=2))


def reply(*args,**kwargs):
    yield "这是隔离测试回答，我是 AI 驱动的灵偶。"
    return "online"


def speech(*args,**kwargs):
    return {"engine":"qa-no-audio","success":False,"synthesized":False,"transferred":False,"error":"qa audio disabled"}


dialogue_engine.route_reply_streaming=reply
dialogue_engine.speak_sentence_streaming=speech
dialogue_engine.is_weather_query=lambda *a,**k:False
dialogue_engine.should_use_bot_search=lambda *a,**k:False
dialogue_engine.extract_city=lambda *a,**k:None


async def qa_app(scope, receive, send):
    async def logged_send(message):
        if message["type"] == "http.response.start":
            with (OUT/"ui-requests.jsonl").open("a") as f:
                f.write(json.dumps({"method":scope.get("method"),"path":scope.get("path"),"status":message["status"]})+"\n")
        await send(message)
    await q.app(scope, receive, logged_send)


if __name__=="__main__":
    try:
        uvicorn.run(qa_app,host="127.0.0.1",port=8000,log_level="warning")
    finally:
        summary={"users":len(q.auth._get_users()["users"]),"bases":[],"figures":[]}
        for base_data in q.store.list_bases():
            user=q.store.base_owner_id(base_data)
            summary["bases"].append({"base_id":base_data["base_id"],"owner":user,"active_figure_id":base_data.get("active_figure_id")})
            if user:
                summary["figures"]+=q.store.list_figures(user_id=user)
        (OUT/"ui-final-state.json").write_text(json.dumps(summary,ensure_ascii=False,indent=2))
        q.temp.cleanup()
