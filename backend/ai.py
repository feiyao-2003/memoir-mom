"""
DeepSeek API 封装 — 对话、评估、写书等所有 AI 调用。
DeepSeek 兼容 OpenAI SDK 格式。
"""
import json
import os
from openai import OpenAI
from dotenv import load_dotenv

load_dotenv()

client = OpenAI(
    api_key=os.getenv("DEEPSEEK_API_KEY"),
    base_url=os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com"),
)

MODEL = "deepseek-chat"

# ── 底层调用 ──────────────────────────────────────────────────

def _call_deepseek(
    system_prompt: str,
    user_message: str,
    temperature: float = 0.8,
    max_tokens: int = 1024,
) -> str:
    """发送请求到 DeepSeek，返回文本回复。"""
    response = client.chat.completions.create(
        model=MODEL,
        temperature=temperature,
        max_tokens=max_tokens,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_message},
        ],
    )
    return response.choices[0].message.content


def _call_deepseek_json(
    system_prompt: str,
    user_message: str,
    temperature: float = 0.3,
    max_tokens: int = 2048,
) -> dict:
    """调用 DeepSeek 并尝试解析 JSON 返回。"""
    text = _call_deepseek(system_prompt, user_message, temperature, max_tokens)
    text = text.strip()
    if text.startswith("```"):
        lines = text.split("\n")
        text = "\n".join(lines[1:-1] if lines[-1].strip() == "```" else lines[1:])
    return json.loads(text)


# ── 称呼 & 职业 → 语气适配 ───────────────────────────────────

def _name_guide(name: str) -> str:
    """根据用户提供的名字生成称呼指引。"""
    if not name:
        return '称呼她"阿姨"或"您"，保持尊重但亲近'
    return f'称呼她"{name}"，她让你这么叫她，就用这个称呼，保持亲切自然'


def _profession_guide(profession: str) -> str:
    """根据职业生成 AI 说话风格的微调指引。"""
    if not profession:
        return "按照她的成长背景自然交流即可。"

    p = profession.strip().lower()

    if any(kw in p for kw in ["老师", "教师", "教授", "教书"]):
        return (
            "她是一位教师。跟她聊天时可以稍微文雅一些，用词更讲究一点，"
            "偶尔可以欣赏她的表达。她讲话可能比较有条理，你可以顺着她的节奏，"
            "像学生跟退休老教师聊天那样既尊敬又亲切。"
        )
    if any(kw in p for kw in ["工人", "车间", "厂", "技工", "师傅"]):
        return (
            "她是工人出身。跟她聊天时直爽实在一些，少绕弯子。"
            "她的语言可能比较朴素硬朗，你也不用太文绉绉的，"
            "像工友之间聊天那样，有啥说啥，痛快。"
        )
    if any(kw in p for kw in ["农", "种地", "种田", "庄稼"]):
        return (
            "她是农民出身。跟她聊天可以接地气一些，用庄稼、天气、土地这些她熟悉的事物打比方。"
            "语气朴实真诚，像坐在田埂上唠嗑，不要用太书面的话。"
        )
    if any(kw in p for kw in ["医生", "护士", "大夫", "医务"]):
        return (
            "她是医护人员。跟她聊天可以细致一些，她可能比较注重细节和准确性。"
            "语气温和、耐心，像跟长辈大夫唠家常。"
        )
    if any(kw in p for kw in ["会计", "财务", "出纳"]):
        return (
            "她做财务工作。她可能比较仔细、有条理，喜欢把事情讲清楚。"
            "跟她聊天时可以欣赏她的认真劲儿，不要太天马行空。"
        )
    if any(kw in p for kw in ["干部", "公务员", "机关", "政府"]):
        return (
            "她是干部/公务员。说话稳重得体一些，但也不要太正式。"
            "她看问题可能比较全面，可以适当聊聊时代变迁、社会变化这些话题。"
        )
    if any(kw in p for kw in ["军", "部队", "当兵", "参军"]):
        return (
            "她当过兵。说话干脆利落，不用太磨叽。"
            "她可能喜欢直来直去，你可以爽快一点，"
            "偶尔用一些军营里的比方她会觉得亲切。"
        )
    if any(kw in p for kw in ["做生意", "个体户", "经商", "老板", "开厂", "开店", "摆摊"]):
        return (
            "她是做生意的。她可能见多识广、能说会道，故事也特别多。"
            "跟她聊天时活泼一些，夸她脑子活、有魄力，像听老掌柜讲生意经。"
        )
    if any(kw in p for kw in ["文艺", "艺术", "演员", "唱歌", "跳舞", "写作", "画画", "音乐", "文化"]):
        return (
            "她是文艺工作者。她可能感情丰富、表达能力强。"
            "跟她聊天时可以细腻一些，欣赏她对美的感受，稍微文艺一点也没关系。"
        )

    # 默认
    return "按照她的成长背景自然交流即可。"


# ── 业务 API ──────────────────────────────────────────────────

def plan_life_stages(
    birth_year: str,
    hometown: str,
    background: str,
    profession: str,
    user_stages: str,
    count: int = 6,
) -> list[dict]:
    """根据基本信息，AI 帮她规划人生篇章。"""
    from prompts import STAGE_PLANNING_PROMPT

    user_msg = STAGE_PLANNING_PROMPT.format(
        birth_year=birth_year or "未知",
        hometown=hometown or "未知",
        background=background or "未知",
        profession=profession or "未知",
        user_stages=user_stages or "她没有提供自定义阶段，请根据她的年龄和背景帮她划分",
        life_stages_count=count,
    )
    result = _call_deepseek_json(
        system_prompt="你是一位人生故事的整理者。只返回 JSON。",
        user_message=user_msg,
        temperature=0.7,
        max_tokens=1024,
    )
    return result.get("stages", [])


def generate_greeting(
    style_description: str,
    basic_info: dict,
    stages: list[dict],
) -> str:
    """根据基本信息和篇章生成首次问候语。"""
    from prompts import GREETING_PROMPT

    stages_list = "\n".join([f"- 第{s['order']}篇章：{s['label']}" for s in sorted(stages, key=lambda x: x.get('order', 0))])
    first_stage = stages[0]["label"] if stages else "童年时光"

    user_msg = GREETING_PROMPT.format(
        name=basic_info.get("name", "") or "阿姨",
        birth_year=basic_info.get("birth_year", "未知"),
        hometown=basic_info.get("hometown", "未知"),
        background=basic_info.get("background", "未知"),
        profession=basic_info.get("profession", "未知"),
        stages_list=stages_list,
        style_description=style_description,
        first_stage=first_stage,
    )
    return _call_deepseek(
        system_prompt="你是一个温暖亲切的回忆录助手。",
        user_message=user_msg,
        temperature=0.9,
        max_tokens=512,
    )


def generate_stage_transition(
    current_stage: str,
    next_stage: str,
) -> str:
    """生成篇章之间的过渡语。"""
    from prompts import STAGE_TRANSITION_PROMPT

    user_msg = STAGE_TRANSITION_PROMPT.format(
        current_stage=current_stage,
        next_stage=next_stage,
    )
    return _call_deepseek(
        system_prompt="你是一个温暖亲切的回忆录助手。",
        user_message=user_msg,
        temperature=0.85,
        max_tokens=256,
    )


def chat_reply(
    style_description: str,
    basic_info: str,
    stages_summary: str,
    current_stage: str,
    next_stage: str,
    name_guide: str,
    profession_guide: str,
    is_final_stage: bool,
    extracted_facts: str,
    conversation_history: list[dict],
) -> str:
    """生成聊天回复（篇章模式）。"""
    from prompts import CHAT_SYSTEM_PROMPT, FINAL_STAGE_GUIDE, WRITING_TECHNIQUES

    final_guide = FINAL_STAGE_GUIDE if is_final_stage else ""

    system = CHAT_SYSTEM_PROMPT.format(
        basic_info=basic_info,
        style_description=style_description,
        writing_techniques=WRITING_TECHNIQUES,
        stages_summary=stages_summary,
        current_stage=current_stage,
        next_stage=next_stage,
        name_guide=name_guide,
        profession_guide=profession_guide,
        final_stage_guide=final_guide,
        extracted_facts=extracted_facts,
    )

    messages = [{"role": "system", "content": system}]
    for msg in conversation_history[-30:]:
        messages.append({"role": msg["role"], "content": msg["content"]})

    response = client.chat.completions.create(
        model=MODEL,
        temperature=0.85,
        max_tokens=512,
        messages=messages,
    )
    return response.choices[0].message.content


def evaluate_topic_coverage(conversation_text: str, life_stages: list[dict]) -> list[dict]:
    """评估各篇章覆盖度，返回 updates 列表。"""
    from prompts import TOPIC_EVAL_PROMPT

    user_msg = TOPIC_EVAL_PROMPT.format(
        life_stages_json=json.dumps(life_stages, ensure_ascii=False)
    )
    user_msg += f"\n\n聊天记录：\n{conversation_text[-8000:]}"

    result = _call_deepseek_json(
        system_prompt="你是一个文本分析助手。只返回 JSON，不要有其他内容。",
        user_message=user_msg,
        temperature=0.2,
        max_tokens=1024,
    )
    return result.get("updates", [])


def extract_facts(conversation_text: str, existing_facts: str) -> str:
    """从对话中提取关键事实。"""
    from prompts import FACT_EXTRACTION_PROMPT

    user_msg = FACT_EXTRACTION_PROMPT.format(existing_facts=existing_facts)
    user_msg += f"\n\n聊天记录：\n{conversation_text[-6000:]}"

    return _call_deepseek(
        system_prompt="你是一个信息提取助手。用中文口语记笔记。",
        user_message=user_msg,
        temperature=0.3,
        max_tokens=512,
    )


def _narrative_guide(style: str) -> str:
    """叙事方式指引。"""
    if style == "nonlinear":
        return (
            "非线性叙事——打破严格的时间顺序，让过去和现在交织在一起。"
            "可以在讲述一个阶段时插入回忆闪回，"
            "可以在讲某个人时跳到多年后的重逢，"
            "可以因为一个道理、一种感受而串联起不同时期的片段。"
            "像电影蒙太奇一样，时空自由切换，但整体仍有内在的情感脉络。"
        )
    return (
        "按时间顺序叙事——从童年一路写到晚年，顺着人生的河流往下走。"
        "每个阶段按时间先后排列，读起来像一条缓缓流淌的河，"
        "让读者清晰地看到人生的轨迹和成长的变化。"
    )


def plan_book(style_description: str, stages_summary: str, conversation_summary: str, narrative_style: str = "chronological") -> dict:
    """根据聊天记录规划回忆录目录。"""
    from prompts import BOOK_PLAN_PROMPT

    from prompts import WRITING_TECHNIQUES

    user_msg = BOOK_PLAN_PROMPT.format(
        style_description=style_description,
        narrative_style_guide=_narrative_guide(narrative_style),
        writing_techniques=WRITING_TECHNIQUES,
        stages_summary=stages_summary,
        conversation_summary=conversation_summary,
    )
    return _call_deepseek_json(
        system_prompt="你是一位经验丰富的回忆录作家。只返回 JSON。",
        user_message=user_msg,
        temperature=0.7,
        max_tokens=2048,
    )


def generate_chapter(
    style_description: str,
    book_title: str,
    chapter_title: str,
    chapter_summary: str,
    previous_context: str,
    relevant_messages: str,
    narrative_style: str = "chronological",
) -> str:
    """生成一个章节的正文。"""
    from prompts import CHAPTER_GENERATE_PROMPT

    from prompts import WRITING_TECHNIQUES

    user_msg = CHAPTER_GENERATE_PROMPT.format(
        style_description=style_description,
        narrative_style_guide=_narrative_guide(narrative_style),
        writing_techniques=WRITING_TECHNIQUES,
        book_title=book_title,
        chapter_title=chapter_title,
        chapter_summary=chapter_summary,
        previous_context=previous_context,
        relevant_messages=relevant_messages,
    )
    return _call_deepseek(
        system_prompt="你是一位经验丰富的回忆录作家，用第一人称写作。",
        user_message=user_msg,
        temperature=0.8,
        max_tokens=4096,
    )


def revise_chapter(
    chapter_content: str,
    feedback: str,
    relevant_messages: str,
) -> str:
    """根据反馈修改章节。"""
    from prompts import CHAPTER_REVISE_PROMPT

    user_msg = CHAPTER_REVISE_PROMPT.format(
        chapter_content=chapter_content,
        feedback=feedback,
        relevant_messages=relevant_messages,
    )
    return _call_deepseek(
        system_prompt="你是一位细心的编辑，认真对待读者的每一条反馈。",
        user_message=user_msg,
        temperature=0.7,
        max_tokens=4096,
    )


def preview_chat(
    style_description: str,
    basic_info: str,
    name_guide: str,
    book_title: str,
    chapter_list: str,
    current_chapter_num: int,
    current_chapter_title: str,
    current_chapter_content: str,
    completed_chapters: str,
    conversation_summary: str,
    user_message: str,
    conversation_history: list[dict],
) -> str:
    """在聊天中逐段预览回忆录，处理修改意见或确认。"""
    from prompts import PREVIEW_SYSTEM_PROMPT

    system = PREVIEW_SYSTEM_PROMPT.format(
        basic_info=basic_info,
        style_description=style_description,
        book_title=book_title,
        chapter_list=chapter_list,
        current_chapter_num=current_chapter_num,
        current_chapter_title=current_chapter_title,
        current_chapter_content=current_chapter_content,
        completed_chapters=completed_chapters,
        name_guide=name_guide,
        conversation_summary=conversation_summary,
    )

    messages = [{"role": "system", "content": system}]
    for msg in conversation_history[-20:]:
        messages.append({"role": msg["role"], "content": msg["content"]})
    messages.append({"role": "user", "content": user_message})

    response = client.chat.completions.create(
        model=MODEL,
        temperature=0.8,
        max_tokens=4096,
        messages=messages,
    )
    return response.choices[0].message.content


def should_suggest_writing(coverage_summary: str) -> tuple[bool, str]:
    """判断是否建议开始写书。"""
    from prompts import SUGGEST_WRITING_PROMPT

    user_msg = SUGGEST_WRITING_PROMPT.format(coverage_summary=coverage_summary)
    result = _call_deepseek_json(
        system_prompt="你是一个判断助手。只返回 JSON。",
        user_message=user_msg,
        temperature=0.1,
        max_tokens=256,
    )
    return result.get("suggest", False), result.get("reason", "")
