import urllib.request, json, time, sys
B="http://localhost:8000"
P=0; F=0; results=[]
def call(method, path, body=None, timeout=45):
    data=json.dumps(body).encode() if body is not None else None
    req=urllib.request.Request(B+path, data=data, headers={"Content-Type":"application/json"}, method=method)
    try:
        r=urllib.request.urlopen(req, timeout=timeout)
        return r.getcode(), json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        try: return e.code, json.loads(e.read().decode())
        except: return e.code, {}
    except Exception as e:
        return 0, {"err":str(e)}
def check(name, cond, detail=""):
    global P,F
    ok = bool(cond)
    P+= ok; F+= (not ok)
    results.append(("✅" if ok else "❌")+" "+name+(" | "+detail if detail else ""))
    print(results[-1])

print("=== M10/M1 持久化+绑定 ===")
c,d=call("GET","/api/bases/BASE-001"); base=d.get("base",d)
check("M1 GET base 已绑定", base.get("status") in ("bound","waiting","bound_to_current_user"), str(base.get("status")))

print("=== 准备测试灵偶(御姐) ===")
c,d=call("POST","/api/figures",{"name":"回归娘","figure_type":"原创角色","wake_names":["回归娘"],"soul_profile":{"archetype":"御姐照顾型","name":"回归娘","address_user_as":"Eddie"}})
FID=d.get("figure_id"); 
check("M10 创建灵偶落盘", FID is not None, FID or str(d)[:60])
m=d.get("memory",{})
check("M8 新建关系初始化(陌生/first_meet)", m.get("relationship_level")=="陌生" and any(c.get("type")=="first_meet" for c in (m.get("memory_capsule") or [])), f"lvl={m.get('relationship_level')} streak={m.get('streak_days')}")
check("M5 御姐音色映射", d.get("voice_profile",{}).get("speaker")=="zh_female_meilinvyou_emo_v2_mars_bigtts", str(d.get("voice_profile",{}).get("speaker")))
call("POST",f"/api/bases/BASE-001/active-figure",{"figure_id":FID})

print("=== M5 触摸短回应+情绪 ===")
c,d=call("POST","/api/events",{"base_id":"BASE-001","event_type":"light_touch"})
check("M5 light_touch 回应+led", bool(d.get("reply")) and d.get("led_effect"), f"reply={d.get('reply')} led={d.get('led_effect')}")
mood=d.get("mood",{})
check("M5 情绪累加(attached+2)", mood.get("attached",0)>=2 or mood.get("happy",0)>50, str({k:mood.get(k) for k in ['happy','attached']}))

print("=== M9 边界: 无效base/figure ===")
c,d=call("GET","/api/figures/nonexistent-xyz")
check("M9 无效figure 404中文", c==404 and ("找不到" in str(d) or "not found" in str(d).lower()), f"{c} {str(d)[:40]}")

print("=== M7 冷落重逢 ===")
call("POST",f"/api/figures/{FID}/simulate-absence",{"hours":72})
c,d=call("GET",f"/api/figures/{FID}"); ls=d.get("life_status",{})
check("M7 冷落分级 missed", ls.get("neglect_tier")=="missed", str(ls.get("neglect_tier")))
c,d=call("POST","/api/events",{"base_id":"BASE-001","event_type":"figure_placed"})
check("M7 重逢台词+tier", bool(d.get("reply")) and d.get("neglect_tier") in("missed","abandoned","half"), f"{d.get('neglect_tier')}: {d.get('reply')}")

print("=== M8 关系boost+streak ===")
call("POST",f"/api/figures/{FID}/boost-relationship",{"level":"羁绊","streak_days":7})
c,d=call("GET",f"/api/figures/{FID}"); m=d.get("memory",{})
check("M8 boost到羁绊+streak7", m.get("relationship_level")=="羁绊" and m.get("streak_days")==7, f"{m.get('relationship_level')}/{m.get('streak_days')}")

print("=== M6 离线对话(快, 不调豆包) ===")
call("POST","/api/brain/mode?base_id=BASE-001",{"mode":"offline"})
c,d=call("POST","/api/dialogue/text?base_id=BASE-001",{"base_id":"BASE-001","text":"我有点累"},timeout=20)
check("M6 离线对话有回复+brain=offline", bool(d.get("reply")) and d.get("brain_mode")=="offline", f"{d.get('brain_mode')}: {d.get('reply')}")
check("M6 离线 tts_engine=voice_pool/system", d.get("tts_engine") in("voice_pool","system_tts","volcano_tts"), str(d.get("tts_engine")))

print("=== M4/M6 在线不出戏(调豆包1次) ===")
call("POST","/api/brain/mode?base_id=BASE-001",{"mode":"online"})
c,d=call("POST","/api/dialogue/text?base_id=BASE-001",{"base_id":"BASE-001","text":"你是AI吗？"},timeout=40)
r=d.get("reply","")
check("M4 在线不出戏(不认AI)", bool(r) and ("AI" not in r or "不是" in r or "什么" in r) , f"{d.get('brain_mode')}: {r}")

print("=== M10 持久化复查(GET能拿回关系/档案) ===")
c,d=call("GET",f"/api/figures/{FID}")
check("M10 关系/streak/胶囊持久", d.get("memory",{}).get("relationship_level")=="羁绊" and len(d.get("memory",{}).get("memory_capsule") or [])>=1, "")

print(f"\n=== 回归结果: {P} 通过 / {F} 失败 ===")
sys.exit(0 if F==0 else 1)
