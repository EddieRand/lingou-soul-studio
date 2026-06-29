# services/companion-server/app/api/character.py
"""
Character Profile API - Phase A 角色还魂深化
POST /api/character/generate  - AI 辅助生成完整角色档案
PUT  /api/figures/{figure_id}/character - 保存角色档案到灵偶
"""
from __future__ import annotations

import re
import json
import httpx
import os
from typing import Optional
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

router = APIRouter(tags=["character"])

# ============== Request/Response Models ==============

class CharacterGenerateRequest(BaseModel):
    name: str  # 角色名
    figure_type: str  # 角色类型
    archetype: Optional[str] = None  # 气质（可选）
    one_line: Optional[str] = None  # 一句话设定种子（可选）


class Recommendation(BaseModel):
    recommended_archetype: str  # 推荐气质（必须是现有11气质之一）
    personality_traits: list[str]  # 人格特质
    speech_style: str  # 说话风格
    recommended_voice: str  # 推荐音色
    wake_reply: str  # 被唤醒时的开场台词
    recommended_touch_reactions: dict  # 5动作推荐台词
    recommended_touch_escalation: Optional[dict] = None  # 触摸递进台词（light_touch/heavy_press/double_tap 各含 tier2/tier3）


class CharacterGenerateResponse(BaseModel):
    recommendation: Recommendation  # AI推荐（用于驱动向导）
    character_profile: dict  # CharacterProfile JSON（深度档案）


# ============== Character Designer System Prompt ==============

# 系统真实的11气质（与 archetypes.json 一致）
VALID_ARCHETYPES = [
    "御姐照顾型", "傲娇吐槽型", "软萌治愈型", "元气伙伴型", "冷淡守护型",
    "桀骜战神型", "搞怪捣蛋型", "憨憨吃货型", "机械副官型", "萌宠陪伴型", "潮玩幸运型"
]

# 验证可用的火山音色ID（与 archetypes.json 的 volcano_speaker 一致）
VALID_VOICES = [
    "zh_female_meilinvyou_emo_v2_mars_bigtts",
    "zh_female_tianmeitaozi_mars_bigtts",
    "zh_female_roumeinvyou_emo_v2_mars_bigtts",
    "zh_female_shuangkuaisisi_moon_bigtts",
    "zh_female_gaolengyujie_emo_v2_mars_bigtts",
    "zh_male_sunwukong_mars_bigtts",
    "zh_male_jingqiangkanye_moon_bigtts",
    "zh_male_beijingxiaoye_emo_v2_mars_bigtts",
    "zh_male_yangguangqingnian_emo_v2_mars_bigtts",
    "zh_female_kailangjiejie_moon_bigtts",
]

CHARACTER_DESIGNER_PROMPT_TEMPLATE = """你是一位专业的角色设定师（Character Designer）。
你的任务是根据用户提供的种子信息，同时生成【推荐配置】和【深度角色档案】。

【输入信息】
- 角色名: __NAME__
- 角色类型: __FIGURE_TYPE__
- 气质原型: __ARCHETYPE__
- 一句话设定: __ONE_LINE__

【可用气质原型（必须从中选择一个推荐）】
御姐照顾型、傲娇吐槽型、软萌治愈型、元气伙伴型、冷淡守护型、桀骜战神型、搞怪捣蛋型、憨憨吃货型、机械副官型、萌宠陪伴型、潮玩幸运型

【可用音色（必须从中选择一个推荐）】
zh_female_meilinvyou_emo_v2_mars_bigtts、zh_female_tianmeitaozi_mars_bigtts、zh_female_roumeinvyou_emo_v2_mars_bigtts、zh_female_shuangkuaisisi_moon_bigtts、zh_female_gaolengyujie_emo_v2_mars_bigtts、zh_male_sunwukong_mars_bigtts、zh_male_jingqiangkanye_moon_bigtts、zh_male_beijingxiaoye_emo_v2_mars_bigtts、zh_male_yangguangqingnian_emo_v2_mars_bigtts、zh_female_kailangjiejie_moon_bigtts

【已知角色识别】如果用户给的 名字 或 一句话设定 指向一个可识别的已知角色(动漫/影视/游戏/漫画等 IP),请用该角色广为人知的设定来填充档案,力求还原本设——
- relationships:填该角色生活中重要的人及其称呼(例:蜡笔小新→{'妈妈':'美伢','爸爸':'广志','妹妹':'小葵','宠物狗':'小白'});
- background:该角色的出身/世界观(例:蜡笔小新→5岁,住春日部,上双叶幼稚园,妈妈美伢爸爸广志);
- catchphrases/signature_lines:该角色标志性的口头禅/台词(例:小新→'我回来了~''动感超人在哪里~');
- knowledge_bounds/values/address_user_as:贴合该角色年龄/身份;
尽量贴近原作但用你自己的话表达,不逐字照抄。
如果是原创或无法识别的角色,照现有方式自圆其说地创作。

【输出格式】
严格只输出 JSON，不要任何前缀后缀文字：
{
  "recommendation": {
    "recommended_archetype": "从11气质中选一个最匹配的",
    "personality_traits": ["特质1", "特质2", "特质3"],
    "speech_style": "说话风格一句话（≤20字）",
    "recommended_voice": "从可用音色中选一个",
    "wake_reply": "被唤醒时的开场台词（≤30字，角色化）",
    "recommended_touch_reactions": {
      "figure_placed": "放上底座时的台词（≤20字）",
      "light_touch": "轻触时的台词（≤20字）",
      "heavy_press": "重按时的台词（≤20字）",
      "double_tap": "双击时的台词（≤20字）",
      "long_press": "长按时的台词（≤20字）"
    },
    "recommended_touch_escalation": {
      "light_touch": {
        "tier2": ["被连续轻触2-3次时的递进反应（贴合人设，≤20字）", "同tier的另一条"],
        "tier3": ["被连续轻触4次以上的升级反应（明显升级，≤20字）", "同tier的另一条"]
      },
      "heavy_press": {
        "tier2": ["被连续重按2-3次时的递进反应（贴合人设，≤20字）", "同tier的另一条"],
        "tier3": ["被连续重按4次以上的升级反应（明显升级，≤20字）", "同tier的另一条"]
      },
      "double_tap": {
        "tier2": ["被连续双击2-3次时的递进反应（贴合人设，≤20字）", "同tier的另一条"],
        "tier3": ["被连续双击4次以上的升级反应（明显升级，≤20字）", "同tier的另一条"]
      }
    }
  },
  "character_profile": {
    "character_name": "__NAME__",
    "one_line": "一句话核心人设（≤20字）",
    "background": "背景故事（≤120字，精炼不啰嗦）",
    "traits": ["特质1", "特质2", "特质3", "特质4"],
    "speech_style": "说话风格（一句话，≤30字）",
    "catchphrases": ["口头禅1", "口头禅2", "口头禅3"],
    "signature_lines": ["台词1", "台词2", "台词3"],
    "relationships": {"关系名": "称呼"},
    "taboos": ["禁忌1", "禁忌2", "禁忌3"],
    "knowledge_bounds": {"knows": ["懂的事"], "不懂": ["不懂的事"]},
    "values": ["价值1", "价值2"],
    "address_user_as": "角色对用户的称呼，只填一个简短词（如「哥哥」「主人」「大雄」「小朋友」）",
    "touch_escalation": {
      "light_touch": {
        "tier2": ["被连续轻触2-3次时的反应（贴合人设，≤20字）", "同tier的另一条"],
        "tier3": ["被连续轻触4次以上的反应（明显升级，≤20字）", "同tier的另一条"]
      },
      "heavy_press": {
        "tier2": ["被连续重按2-3次时的反应（贴合人设，≤20字）", "同tier的另一条"],
        "tier3": ["被连续重按4次以上的反应（明显升级，≤20字）", "同tier的另一条"]
      },
      "double_tap": {
        "tier2": ["被连续双击2-3次时的反应（贴合人设，≤20字）", "同tier的另一条"],
        "tier3": ["被连续双击4次以上的反应（明显升级，≤20字）", "同tier的另一条"]
      }
    }
  }
}

【严格要求】
- recommendation.recommended_archetype 必须是11气质之一；
- 【重要】推荐气质必须符合角色性别与年龄：先判断角色性别。
  * 男性/雄性角色禁止推女性向气质（御姐照顾型、软萌治愈型、潮玩幸运型、元气伙伴型）；
  * 女性角色禁止推明显男性向气质（桀骜战神型、机械副官型）；
  * 中性气质（傲娇吐槽型、冷淡守护型、搞怪捣蛋型、憨憨吃货型、萌宠陪伴型）可根据角色性格选用；
  * 在符合性别的气质里挑最贴性格的。例如：雄性、成熟、护着弟弟熊二的"熊大"，应选冷淡守护型 / 憨憨吃货型 / 搞怪捣蛋型，不能选软萌治愈型或御姐照顾型。
- recommendation.recommended_voice 必须是可用音色之一；若为已知角色，recommended_voice 选最符合该角色性别年龄音色特征的（如男童角色选男童音、御姐角色选成熟女声）；
- recommendation.recommended_touch_reactions 5个动作都要有台词，每条≤20字；
- character_profile.background 严格≤120字；
- catchphrases/signature_lines/taboos 各恰好3条，每条≤15字；
- traits 4-6个词；
- touch_escalation: 每个动作(light_touch/heavy_press/double_tap)要有tier2和tier3，每档2条，体现递进情绪；
- address_user_as：直接给一个简短的最终称呼，不要写多个备选、不要用斜杠/顿号、不要加任何解释或括号说明；
- 输出必须是纯 JSON，不含任何其他文字。"""


def _build_prompt(name: str, figure_type: str, archetype: str, one_line: str) -> str:
    """使用 replace 替换占位符，避免 .format() 与 JSON 花括号冲突"""
    return CHARACTER_DESIGNER_PROMPT_TEMPLATE.replace("__NAME__", name).replace("__FIGURE_TYPE__", figure_type).replace("__ARCHETYPE__", archetype).replace("__ONE_LINE__", one_line)


def _get_ark_config() -> dict:
    return {
        "api_key": os.getenv("ARK_API_KEY", "").strip(),
        "endpoint_id": os.getenv("ARK_ENDPOINT_ID", "").strip(),
        "base_url": os.getenv("ARK_BASE_URL", "https://ark.cn-beijing.volces.com/api/v3").strip(),
    }


def _call_doubao_json(messages: list[dict], timeout: float = 75.0) -> str:
    """Call Doubao Ark API, return assistant reply text."""
    cfg = _get_ark_config()
    headers = {
        "Authorization": f"Bearer {cfg['api_key']}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": cfg["endpoint_id"],
        "messages": messages,
        "max_tokens": 2600,
        "temperature": 0.7,
        "thinking": {"type": "disabled"},
    }
    url = f"{cfg['base_url']}/chat/completions"
    with httpx.Client(timeout=httpx.Timeout(timeout, connect=5.0)) as client:
        resp = client.post(url, headers=headers, json=payload)
        if resp.status_code != 200:
            raise Exception(f"Ark API error: {resp.status_code} {resp.text[:200]}")
        data = resp.json()
        choices = data.get("choices", [])
        if not choices:
            raise Exception("No choices in Ark response")
        return choices[0].get("message", {}).get("content", "").strip()


def _parse_character_json(raw_text: str) -> dict | None:
    """解析豆包返回的 JSON，处理可能的 markdown 包裹。"""
    # 去掉可能的 markdown 代码块包裹
    text = raw_text.strip()
    if text.startswith("```"):
        # 去掉 ```json 或 ``` 和最后的 ```
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    text = text.strip()

    # 尝试直接解析
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        # 尝试在文本中找 JSON 对象（花括号配对）
        start = text.find("{")
        end = text.rfind("}")
        if start != -1 and end != -1 and end > start:
            try:
                return json.loads(text[start:end+1])
            except json.JSONDecodeError:
                return None
    return None


def _clean_address_user_as(character_profile: dict) -> None:
    """清洗 address_user_as，去掉斜杠/顿号/括号及之后内容，只保留第一个称呼。"""
    a = character_profile.get("address_user_as", "")
    if a:
        # 按斜杠、顿号、逗号、左括号分割，取第一段
        a = re.split(r"[/、，,（(]", a)[0].strip()
        character_profile["address_user_as"] = a


# ============== API Endpoints ==============

@router.post("/generate", response_model=CharacterGenerateResponse)
async def generate_character(req: CharacterGenerateRequest):
    """
    AI 辅助生成完整角色档案 + 推荐配置。
    复用豆包 Ark 调用，用"角色设定师"system prompt 生成。
    """
    cfg = _get_ark_config()
    if not cfg["api_key"] or not cfg["endpoint_id"]:
        raise HTTPException(status_code=503, detail="ARK API 未配置，请设置 ARK_API_KEY 和 ARK_ENDPOINT_ID")

    # 填充默认值
    archetype = req.archetype or "软萌治愈型"
    one_line = req.one_line or f"一个{archetype}的{req.figure_type}"

    # 使用 _build_prompt 替代 .format()，避免 JSON 花括号冲突
    system_prompt = _build_prompt(
        name=req.name,
        figure_type=req.figure_type,
        archetype=archetype,
        one_line=one_line,
    )

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": f"请为「{req.name}」生成推荐配置和深度角色档案。"},
    ]

    # 第一次尝试
    first_error = ""
    try:
        raw = _call_doubao_json(messages)
        result = _parse_character_json(raw)
        if result and "recommendation" in result and "character_profile" in result:
            # 验证推荐气质和音色是否有效
            rec = result["recommendation"]
            if rec.get("recommended_archetype") not in VALID_ARCHETYPES:
                # 如果不在有效列表，尝试找最接近的
                for valid_arch in VALID_ARCHETYPES:
                    if valid_arch in rec.get("recommended_archetype", "") or rec.get("recommended_archetype", "") in valid_arch:
                        rec["recommended_archetype"] = valid_arch
                        break
                else:
                    rec["recommended_archetype"] = VALID_ARCHETYPES[0]  # 默认第一个
            
            if rec.get("recommended_voice") not in VALID_VOICES:
                # 如果不在有效列表，根据气质选择对应的默认音色
                arch_to_voice = {
                    "御姐照顾型": "zh_female_meilinvyou_emo_v2_mars_bigtts",
                    "傲娇吐槽型": "zh_female_tianmeitaozi_mars_bigtts",
                    "软萌治愈型": "zh_female_roumeinvyou_emo_v2_mars_bigtts",
                    "元气伙伴型": "zh_female_shuangkuaisisi_moon_bigtts",
                    "冷淡守护型": "zh_female_gaolengyujie_emo_v2_mars_bigtts",
                    "桀骜战神型": "zh_male_sunwukong_mars_bigtts",
                    "搞怪捣蛋型": "zh_male_jingqiangkanye_moon_bigtts",
                    "憨憨吃货型": "zh_male_beijingxiaoye_emo_v2_mars_bigtts",
                    "机械副官型": "zh_male_yangguangqingnian_emo_v2_mars_bigtts",
                    "萌宠陪伴型": "zh_female_kailangjiejie_moon_bigtts",
                    "潮玩幸运型": "zh_female_tianmeitaozi_mars_bigtts",
                }
                rec["recommended_voice"] = arch_to_voice.get(rec.get("recommended_archetype"), VALID_VOICES[0])
            
            # 清洗 address_user_as，确保是单一干净的称呼
            _clean_address_user_as(result["character_profile"])
            
            return CharacterGenerateResponse(
                recommendation=Recommendation(**rec),
                character_profile=result["character_profile"]
            )
    except Exception as e:
        first_error = str(e)
        if "timeout" in first_error.lower():
            raise HTTPException(
                status_code=504,
                detail="角色档案生成超时，请稍后重试。"
            )

    # 第一次失败（非超时），重试一次
    try:
        raw = _call_doubao_json(messages, timeout=30.0)
        result = _parse_character_json(raw)
        if result and "recommendation" in result and "character_profile" in result:
            # 验证推荐气质和音色是否有效
            rec = result["recommendation"]
            if rec.get("recommended_archetype") not in VALID_ARCHETYPES:
                for valid_arch in VALID_ARCHETYPES:
                    if valid_arch in rec.get("recommended_archetype", "") or rec.get("recommended_archetype", "") in valid_arch:
                        rec["recommended_archetype"] = valid_arch
                        break
                else:
                    rec["recommended_archetype"] = VALID_ARCHETYPES[0]
            
            if rec.get("recommended_voice") not in VALID_VOICES:
                arch_to_voice = {
                    "御姐照顾型": "zh_female_meilinvyou_emo_v2_mars_bigtts",
                    "傲娇吐槽型": "zh_female_tianmeitaozi_mars_bigtts",
                    "软萌治愈型": "zh_female_roumeinvyou_emo_v2_mars_bigtts",
                    "元气伙伴型": "zh_female_shuangkuaisisi_moon_bigtts",
                    "冷淡守护型": "zh_female_gaolengyujie_emo_v2_mars_bigtts",
                    "桀骜战神型": "zh_male_sunwukong_mars_bigtts",
                    "搞怪捣蛋型": "zh_male_jingqiangkanye_moon_bigtts",
                    "憨憨吃货型": "zh_male_beijingxiaoye_emo_v2_mars_bigtts",
                    "机械副官型": "zh_male_yangguangqingnian_emo_v2_mars_bigtts",
                    "萌宠陪伴型": "zh_female_kailangjiejie_moon_bigtts",
                    "潮玩幸运型": "zh_female_tianmeitaozi_mars_bigtts",
                }
                rec["recommended_voice"] = arch_to_voice.get(rec.get("recommended_archetype"), VALID_VOICES[0])
            
            # 清洗 address_user_as，确保是单一干净的称呼
            _clean_address_user_as(result["character_profile"])
            
            return CharacterGenerateResponse(
                recommendation=Recommendation(**rec),
                character_profile=result["character_profile"]
            )
    except Exception as retry_error:
        pass

    # 两次都失败
    error_type = "网络超时" if "timeout" in first_error.lower() else "服务异常"
    raise HTTPException(
        status_code=502,
        detail=f"角色档案生成失败（{error_type}）。请稍后重试。"
    )
