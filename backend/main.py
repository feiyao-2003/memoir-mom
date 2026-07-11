"""
人生回忆录 — FastAPI 主应用（篇章模式）
"""
import datetime
import json
from fastapi import FastAPI, Depends, HTTPException, Query, Body
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from sqlalchemy.orm import Session as DbSession

from database import get_db, init_db
from models import Session, Message, TopicCoverage, Chapter
from prompts import STYLE_TEMPLATES, DEFAULT_LIFE_STAGES, STAGE_SUGGESTIONS
import ai
import export as export_lib


class ChatRequest(BaseModel):
    message: str

class ReviseRequest(BaseModel):
    feedback: str

class SetupRequest(BaseModel):
    name: str = ""  # 怎么称呼她
    birth_year: str = ""
    hometown: str = ""
    background: str = ""
    profession: str = ""  # 职业
    custom_stages: str = ""  # 用户自己输入的阶段描述


app = FastAPI(title="人生回忆录", version="2.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.mount("/static", StaticFiles(directory="../frontend"), name="static")


@app.on_event("startup")
def on_startup():
    init_db()


# ── 辅助函数 ──────────────────────────────────────────────────

def _get_session(db: DbSession, session_id: str) -> Session:
    s = db.query(Session).filter(Session.id == session_id).first()
    if not s:
        raise HTTPException(status_code=404, detail="会话不存在")
    return s


def _get_stages(session: Session) -> list[dict]:
    """获取会话的篇章列表。"""
    if session.custom_stages:
        try:
            return json.loads(session.custom_stages)
        except json.JSONDecodeError:
            pass
    # 返回默认阶段
    return [dict(s) for s in DEFAULT_LIFE_STAGES]


def _get_current_stage(session: Session) -> dict:
    """获取当前篇章。"""
    stages = _get_stages(session)
    idx = session.current_stage_index
    if 0 <= idx < len(stages):
        return stages[idx]
    return stages[0] if stages else {"label": "童年时光", "key": "childhood"}


def _get_next_stage(session: Session) -> dict:
    """获取下一篇章。"""
    stages = _get_stages(session)
    idx = session.current_stage_index + 1
    if 0 <= idx < len(stages):
        return stages[idx]
    return {"label": "（这是最后一个篇章了）", "key": ""}


def _stages_summary(session: Session) -> str:
    """篇章的文本摘要。"""
    stages = _get_stages(session)
    lines = []
    for s in sorted(stages, key=lambda x: x.get("order", 0)):
        marker = " ← 当前" if s.get("order") == session.current_stage_index + 1 else ""
        lines.append(f"- 第{s.get('order', 0)}篇章：{s['label']}{marker}")
    return "\n".join(lines)


def _init_topic_coverage(db: DbSession, session_id: str, stages: list[dict]):
    """根据篇章初始化覆盖记录。"""
    for stage in stages:
        tc = TopicCoverage(
            session_id=session_id,
            topic_key=stage.get("key", f"stage_{stage.get('order', 1)}"),
            topic_label=stage["label"],
            coverage_score=0,
        )
        db.add(tc)
    db.commit()


def _get_extracted_facts(db: DbSession, session_id: str) -> str:
    fact_msg = (
        db.query(Message)
        .filter(
            Message.session_id == session_id,
            Message.role == "system",
            Message.content.like("[FACTS]%"),
        )
        .order_by(Message.id.desc())
        .first()
    )
    if fact_msg:
        return fact_msg.content.replace("[FACTS]\n", "")
    return "还没有提取事实"


def _save_facts(db: DbSession, session_id: str, facts: str):
    db.query(Message).filter(
        Message.session_id == session_id,
        Message.role == "system",
        Message.content.like("[FACTS]%"),
    ).delete()
    fact_msg = Message(
        session_id=session_id,
        role="system",
        content=f"[FACTS]\n{facts}",
    )
    db.add(fact_msg)
    db.commit()


# ── API 路由 ──────────────────────────────────────────────────

@app.get("/api/styles")
def get_styles():
    """返回风格、默认阶段、建议标签。"""
    return {
        "styles": STYLE_TEMPLATES,
        "default_stages": DEFAULT_LIFE_STAGES,
        "stage_suggestions": STAGE_SUGGESTIONS,
    }


@app.post("/api/sessions")
def create_session(
    style_key: str = Query(default=""),
    custom_style: str = Query(default=""),
    db: DbSession = Depends(get_db),
):
    """第1步：选风格，创建会话。"""
    if style_key and style_key in STYLE_TEMPLATES:
        style_desc = STYLE_TEMPLATES[style_key]["description"]
    elif custom_style:
        style_desc = custom_style
    else:
        style_desc = STYLE_TEMPLATES["style_a"]["description"]

    session = Session(
        phase="info_collect",
        style_preference=style_desc,
    )
    db.add(session)
    db.commit()

    return {
        "session_id": session.id,
        "style_description": style_desc,
    }


@app.post("/api/sessions/{session_id}/setup")
def setup_session(
    session_id: str,
    req: SetupRequest = Body(...),
    db: DbSession = Depends(get_db),
):
    """第2步：填基本信息 → AI 规划篇章 → 返回问候语。"""
    session = _get_session(db, session_id)

    # 保存基本信息
    basic_info = {
        "name": req.name,
        "birth_year": req.birth_year,
        "hometown": req.hometown,
        "background": req.background,
        "profession": req.profession,
    }
    session.basic_info = json.dumps(basic_info, ensure_ascii=False)

    # AI 规划篇章
    stages = ai.plan_life_stages(
        birth_year=req.birth_year,
        hometown=req.hometown,
        background=req.background,
        profession=req.profession,
        user_stages=req.custom_stages,
        count=6,
    )
    session.custom_stages = json.dumps(stages, ensure_ascii=False)
    session.current_stage_index = 0
    session.phase = "chatting"
    db.commit()

    # 初始化话题覆盖
    _init_topic_coverage(db, session.id, stages)

    # 生成问候语
    greeting = ai.generate_greeting(
        style_description=session.style_preference,
        basic_info=basic_info,
        stages=stages,
    )

    # 保存
    greeting_msg = Message(session_id=session.id, role="assistant", content=greeting)
    db.add(greeting_msg)
    db.commit()

    # 格式化基本信息给人看
    info_lines = []
    if req.name:
        info_lines.insert(0, f"称呼：{req.name}")
    if req.birth_year:
        info_lines.append(f"{req.birth_year}年生")
    if req.hometown:
        info_lines.append(f"籍贯{req.hometown}")
    if req.background:
        info_lines.append(f"{req.background}长大")
    if req.profession:
        info_lines.append(f"职业{req.profession}")
    basic_info_text = "，".join(info_lines) if info_lines else "未填写"

    return {
        "greeting": greeting,
        "stages": stages,
        "basic_info_text": basic_info_text,
        "current_stage": stages[0] if stages else None,
    }


@app.get("/api/sessions/{session_id}")
def get_session_state(session_id: str, db: DbSession = Depends(get_db)):
    """获取会话完整状态。"""
    session = _get_session(db, session_id)

    messages = [
        {"role": m.role, "content": m.content, "time": m.created_at.isoformat()}
        for m in session.messages
        if m.role in ("user", "assistant")
    ]

    coverages = {}
    for tc in session.topic_coverages:
        coverages[tc.topic_key] = {"label": tc.topic_label, "score": tc.coverage_score}

    chapters = [
        {"id": ch.id, "title": ch.title, "content": ch.content, "order": ch.order, "status": ch.status}
        for ch in session.chapters
    ]

    stages = _get_stages(session)
    current_stage = _get_current_stage(session)

    return {
        "session_id": session.id,
        "phase": session.phase,
        "style_preference": session.style_preference,
        "basic_info": json.loads(session.basic_info) if session.basic_info else {},
        "stages": stages,
        "current_stage_index": session.current_stage_index,
        "current_stage": current_stage,
        "messages": messages,
        "coverages": coverages,
        "chapters": chapters,
    }


@app.post("/api/sessions/{session_id}/chat")
def chat(
    session_id: str,
    req: ChatRequest = Body(...),
    db: DbSession = Depends(get_db),
):
    """发送用户消息，获取 AI 回复。支持聊天模式和预览模式。"""
    message = req.message
    if not message.strip():
        raise HTTPException(status_code=400, detail="消息不能为空")

    session = _get_session(db, session_id)

    # 保存用户消息
    user_msg = Message(session_id=session_id, role="user", content=message)
    db.add(user_msg)
    db.commit()

    # ── 选择叙事方式 → 触发写书 ──
    if session.phase == "choosing_narrative":
        msg_lower = message.strip().lower()
        if any(kw in msg_lower for kw in ["时间顺序", "按时间", "从童年", "顺着", "一路", "流水账", "顺序"]):
            session.narrative_style = "chronological"
        elif any(kw in msg_lower for kw in ["打破", "非线性", "交织", "穿插", "跳", "电影", "碎片", "混合", "结合"]):
            session.narrative_style = "nonlinear"
        else:
            # 模糊回答，默认按时间顺序
            session.narrative_style = "chronological"
        db.commit()
        # 触发实际生成
        return start_writing(session_id, db)

    # ── 预览模式 ──
    if session.phase == "previewing":
        return _handle_preview_chat(session, message, db)

    # ── 正常聊天模式 ──
    # 构建对话历史
    history = [
        {"role": m.role, "content": m.content}
        for m in db.query(Message)
        .filter(Message.session_id == session_id, Message.role.in_(["user", "assistant"]))
        .order_by(Message.created_at)
        .all()
    ]

    # 篇章信息
    stages = _get_stages(session)
    current_stage = _get_current_stage(session)
    next_stage = _get_next_stage(session)

    # 基本信息
    basic_info = ""
    profession = ""
    name = ""
    if session.basic_info:
        try:
            info = json.loads(session.basic_info)
            parts = []
            if info.get("name"):
                name = info["name"]
                parts.append(f"称呼：{name}")
            if info.get("birth_year"): parts.append(f"{info['birth_year']}年生")
            if info.get("hometown"): parts.append(f"籍贯{info['hometown']}")
            if info.get("background"): parts.append(f"{info['background']}长大")
            if info.get("profession"):
                parts.append(f"职业{info['profession']}")
                profession = info['profession']
            basic_info = "，".join(parts)
        except json.JSONDecodeError:
            basic_info = session.basic_info

    name_guide = ai._name_guide(name)
    profession_guide = ai._profession_guide(profession)
    facts = _get_extracted_facts(db, session_id)

    # 判断是否是最后一个篇章
    is_final = session.current_stage_index >= len(stages) - 1

    # 调用 AI
    reply = ai.chat_reply(
        style_description=session.style_preference,
        basic_info=basic_info,
        stages_summary=_stages_summary(session),
        current_stage=current_stage.get("label", ""),
        next_stage=next_stage.get("label", ""),
        name_guide=name_guide,
        profession_guide=profession_guide,
        is_final_stage=is_final,
        extracted_facts=facts,
        conversation_history=history,
    )

    # 检查是否有 [STAGE_COMPLETE] 标记
    stage_complete = "[STAGE_COMPLETE]" in reply
    reply = reply.replace("[STAGE_COMPLETE]", "").strip()

    # 如果篇章完成且用户似乎同意切换，自动推进
    if stage_complete:
        # 更新当前篇章的覆盖度
        tc = (
            db.query(TopicCoverage)
            .filter(
                TopicCoverage.session_id == session_id,
                TopicCoverage.topic_key == current_stage.get("key", ""),
            )
            .first()
        )
        if tc:
            tc.coverage_score = max(tc.coverage_score, 80)
            tc.last_discussed_at = datetime.datetime.utcnow()
        db.commit()

    # 保存 AI 回复
    assistant_msg = Message(session_id=session_id, role="assistant", content=reply)
    db.add(assistant_msg)
    session.updated_at = datetime.datetime.utcnow()
    db.commit()

    # 定期评估（每 5 轮）
    suggest_writing = False
    user_msg_count = (
        db.query(Message)
        .filter(Message.session_id == session_id, Message.role == "user")
        .count()
    )
    if user_msg_count % 5 == 0:
        all_messages = [
            m.content for m in db.query(Message)
            .filter(Message.session_id == session_id, Message.role.in_(["user", "assistant"]))
            .all()
        ]
        conversation_text = "\n".join(all_messages)

        updates = ai.evaluate_topic_coverage(conversation_text, stages)
        for update in updates:
            tc = (
                db.query(TopicCoverage)
                .filter(
                    TopicCoverage.session_id == session_id,
                    TopicCoverage.topic_key == update["topic_key"],
                )
                .first()
            )
            if tc:
                tc.coverage_score = max(tc.coverage_score, update.get("score", 0))
                tc.last_discussed_at = datetime.datetime.utcnow()
        db.commit()

        # 提取事实
        new_facts = ai.extract_facts(conversation_text, facts)
        if new_facts and "无新事实" not in new_facts:
            updated = facts + "\n" + new_facts if facts else new_facts
            _save_facts(db, session_id, updated)

        # 判断是否建议写书
        coverage_dict = {}
        for tc in session.topic_coverages:
            coverage_dict[tc.topic_key] = {"label": tc.topic_label, "score": tc.coverage_score}
        cov_str = "\n".join([f"- {v['label']}: {v['score']}%" for v in coverage_dict.values()])
        suggest_writing, _ = ai.should_suggest_writing(cov_str)

    # 最新覆盖度
    latest_coverages = {}
    for tc in session.topic_coverages:
        latest_coverages[tc.topic_key] = {"label": tc.topic_label, "score": tc.coverage_score}

    return {
        "reply": reply,
        "coverages": latest_coverages,
        "suggest_writing": suggest_writing,
        "current_stage": current_stage,
        "current_stage_index": session.current_stage_index,
        "stage_complete": stage_complete,
    }


@app.post("/api/sessions/{session_id}/next-stage")
def advance_stage(session_id: str, db: DbSession = Depends(get_db)):
    """手动推进到下一篇章。"""
    session = _get_session(db, session_id)
    stages = _get_stages(session)

    if session.current_stage_index >= len(stages) - 1:
        raise HTTPException(status_code=400, detail="已经是最后一个篇章了")

    session.current_stage_index += 1
    db.commit()

    current = _get_current_stage(session)

    # 生成过渡语
    transition = ai.generate_stage_transition(
        current_stage=stages[session.current_stage_index - 1]["label"],
        next_stage=current["label"],
    )

    # 保存过渡语
    trans_msg = Message(session_id=session.id, role="assistant", content=transition)
    db.add(trans_msg)
    db.commit()

    return {
        "transition": transition,
        "current_stage_index": session.current_stage_index,
        "current_stage": current,
    }


def _handle_preview_chat(session: Session, user_message: str, db: DbSession):
    """处理预览模式下的聊天：判断修改/确认/推进。"""
    # 获取当前正在预览的章节（最新的 draft）
    current_chapter = (
        db.query(Chapter)
        .filter(Chapter.session_id == session.id, Chapter.status == "draft")
        .order_by(Chapter.order)
        .first()
    )
    if not current_chapter:
        # 全部完成
        session.phase = "done"
        db.commit()
        return {
            "reply": "全部章节都看完啦！您可以点击下面的按钮导出下载~ 📥",
            "phase": "done",
            "preview_done": True,
        }

    # 判断用户意图：修改还是确认
    msg_lower = user_message.strip().lower()
    is_correction = any(kw in msg_lower for kw in [
        "不对", "错了", "其实是", "应该是", "改成", "修改", "加上", "加了",
        "不是", "写错", "有误", "更正", "补充", "再加", "还想加",
    ])
    is_approval = any(kw in msg_lower for kw in [
        "没问题", "挺好", "可以", "行", "好", "对", "是的", "继续",
        "下一章", "下一篇", "不错", "很好", "就这样", "ok", "嗯",
    ])

    # 构建基本信息
    basic_info = ""
    name = ""
    if session.basic_info:
        try:
            info = json.loads(session.basic_info)
            parts = []
            if info.get("name"):
                name = info["name"]
                parts.append(f"称呼：{name}")
            if info.get("birth_year"): parts.append(f"{info['birth_year']}年生")
            if info.get("hometown"): parts.append(f"籍贯{info['hometown']}")
            if info.get("background"): parts.append(f"{info['background']}长大")
            basic_info = "，".join(parts)
        except json.JSONDecodeError:
            pass

    name_guide = ai._name_guide(name)

    # 已完成章节
    completed = (
        db.query(Chapter)
        .filter(Chapter.session_id == session.id, Chapter.status == "final")
        .order_by(Chapter.order)
        .all()
    )
    completed_str = "、".join([ch.title for ch in completed]) if completed else "暂无"

    # 全部章节列表
    all_chapters = (
        db.query(Chapter)
        .filter(Chapter.session_id == session.id)
        .order_by(Chapter.order)
        .all()
    )
    chapter_list = "\n".join([
        f"第{i+1}章《{ch.title}》{' ✅已确认' if ch.status == 'final' else ' ⏳预览中' if ch.status == 'draft' else ' 📝待生成'}"
        for i, ch in enumerate(all_chapters)
    ])

    # 对话历史
    history = [
        {"role": m.role, "content": m.content}
        for m in db.query(Message)
        .filter(Message.session_id == session.id, Message.role.in_(["user", "assistant"]))
        .order_by(Message.created_at)
        .all()
    ]

    # 聊天记录摘要
    conv_text = "\n".join([m["content"] for m in history[-100:]])

    # 调用 AI 处理
    if is_correction and not is_approval:
        # 修改模式：AI 根据反馈修改本章
        revised = ai.revise_chapter(
            current_chapter.content,
            user_message,
            "\n".join([m["content"] for m in history[-80:]]),
        )
        current_chapter.content = revised
        db.commit()

        reply = ai.preview_chat(
            style_description=session.style_preference,
            basic_info=basic_info,
            name_guide=name_guide,
            book_title="",
            chapter_list=chapter_list,
            current_chapter_num=current_chapter.order,
            current_chapter_title=current_chapter.title,
            current_chapter_content=revised,
            completed_chapters=completed_str,
            conversation_summary=conv_text,
            user_message=user_message,
            conversation_history=history,
        )
    else:
        # 确认/推进模式
        if is_approval:
            # 标记当前章为完成
            current_chapter.status = "final"
            db.commit()

            # 有下一章吗？
            next_chapter = (
                db.query(Chapter)
                .filter(
                    Chapter.session_id == session.id,
                    Chapter.order == current_chapter.order + 1,
                )
                .first()
            )

            if next_chapter:
                # 生成下一章内容
                conv_text_full = "\n".join([m["content"] for m in history])
                next_content = ai.generate_chapter(
                    style_description=session.style_preference,
                    book_title="",
                    chapter_title=next_chapter.title,
                    chapter_summary="",
                    previous_context=f"前面已完成：{completed_str}、{current_chapter.title}",
                    relevant_messages=conv_text_full,
                    narrative_style=session.narrative_style or "chronological",
                )
                next_chapter.content = next_content
                next_chapter.status = "draft"
                db.commit()

                # 更新列表
                all_chapters = (
                    db.query(Chapter).filter(Chapter.session_id == session.id).order_by(Chapter.order).all()
                )
                chapter_list = "\n".join([
                    f"第{i+1}章《{ch.title}》{' ✅已确认' if ch.status == 'final' else ' ⏳预览中'}"
                    for i, ch in enumerate(all_chapters)
                ])
                completed_str = "、".join([ch.title for ch in completed + [current_chapter]])

            reply = ai.preview_chat(
                style_description=session.style_preference,
                basic_info=basic_info,
                name_guide=name_guide,
                book_title="",
                chapter_list=chapter_list,
                current_chapter_num=next_chapter.order if next_chapter else current_chapter.order,
                current_chapter_title=next_chapter.title if next_chapter else current_chapter.title,
                current_chapter_content=next_chapter.content if next_chapter else current_chapter.content,
                completed_chapters=completed_str,
                conversation_summary=conv_text,
                user_message=user_message,
                conversation_history=history,
            )
            if not next_chapter:
                session.phase = "done"
                db.commit()
        else:
            # 模糊输入，让 AI 自由回应
            reply = ai.preview_chat(
                style_description=session.style_preference,
                basic_info=basic_info,
                name_guide=name_guide,
                book_title="",
                chapter_list=chapter_list,
                current_chapter_num=current_chapter.order,
                current_chapter_title=current_chapter.title,
                current_chapter_content=current_chapter.content,
                completed_chapters=completed_str,
                conversation_summary=conv_text,
                user_message=user_message,
                conversation_history=history,
            )

    # 保存 AI 回复
    assistant_msg = Message(session_id=session.id, role="assistant", content=reply)
    db.add(assistant_msg)
    db.commit()

    all_done = session.phase == "done"

    return {
        "reply": reply,
        "phase": session.phase,
        "previewing": not all_done,
        "preview_done": all_done,
    }


@app.post("/api/sessions/{session_id}/start-writing")
def start_writing(session_id: str, db: DbSession = Depends(get_db)):
    """开始写书——规划目录，生成第一章，进入预览模式。"""
    session = _get_session(db, session_id)

    existing = db.query(Chapter).filter(Chapter.session_id == session_id).all()
    if existing:
        # 之前生成过，直接进入预览模式
        session.phase = "previewing"
        db.commit()
        draft = [ch for ch in existing if ch.status == "draft"]
        first_draft = draft[0] if draft else existing[0]
        return {
            "reply": f"好嘞！咱们来一段一段看。这是第1章《{first_draft.title}》，您看看~\n\n---\n{first_draft.content}\n---\n\n写得对不对？有什么要改的您直接说~",
            "phase": "previewing",
            "previewing": True,
        }

    # 还没选叙事方式 → 先问她
    if not session.narrative_style:
        question = (
            "在开始写之前，想问您一个问题~ 📝\n\n"
            "您希望这本回忆录按什么方式来写呢？\n\n"
            "📅 **按时间顺序写**——从童年一路写到退休，顺着人生的河流往下走，清清楚楚\n\n"
            "🎭 **打破时间线写**——让过去和现在交织在一起，"
            "比如聊到某个道理时跳回小时候的故事，聊到一个人时跳到后来重逢的场景。"
            "像电影一样，回忆和当下穿插着来\n\n"
            "您觉得哪种更适合您？或者也可以两种结合~"
        )
        msg = Message(session_id=session_id, role="assistant", content=question)
        db.add(msg)
        session.phase = "choosing_narrative"
        db.commit()
        return {
            "reply": question,
            "phase": "choosing_narrative",
            "asking_narrative": True,
        }

    all_messages = [
        m.content for m in db.query(Message)
        .filter(Message.session_id == session_id, Message.role.in_(["user", "assistant"]))
        .all()
    ]
    conversation_summary = "\n".join(all_messages[-200:])
    if len(all_messages) > 200:
        conversation_summary = (
            "\n".join(all_messages[:50]) + "\n\n...(中间省略)...\n\n" + "\n".join(all_messages[-150:])
        )

    # 1. 规划目录
    plan = ai.plan_book(
        style_description=session.style_preference,
        stages_summary=_stages_summary(session),
        conversation_summary=conversation_summary,
        narrative_style=session.narrative_style or "chronological",
    )
    book_title = plan.get("book_title", "我的人生故事")
    chapters_plan = plan.get("chapters", [])

    # 2. 只生成第一章
    previous_context = "这是第一章。"
    first_chapter_content = ""
    first_chapter_title = ""
    if chapters_plan:
        first = chapters_plan[0]
        first_chapter_title = first["title"]
        first_chapter_content = ai.generate_chapter(
            style_description=session.style_preference,
            book_title=book_title,
            chapter_title=first["title"],
            chapter_summary=first.get("summary", ""),
            previous_context=previous_context,
            relevant_messages=conversation_summary,
            narrative_style=session.narrative_style or "chronological",
        )

    # 3. 保存所有章节（后面的暂时为空，状态 pending）
    for ch_plan in chapters_plan:
        content = first_chapter_content if ch_plan["order"] == 1 else ""
        status = "draft" if ch_plan["order"] == 1 else "pending"
        chapter = Chapter(
            session_id=session_id,
            title=ch_plan["title"],
            content=content,
            order=ch_plan.get("order", len(db.query(Chapter).filter(Chapter.session_id == session_id).all()) + 1),
            status=status,
        )
        db.add(chapter)

    session.phase = "previewing"
    session.updated_at = datetime.datetime.utcnow()
    db.commit()

    # 4. 以聊天消息形式返回第一章预览
    greeting = f"好嘞！我帮您把回忆录整理出来了，书名就叫《{book_title}》。咱们一段一段看~\n\n这是第1章《{first_chapter_title}》，您看看写得怎么样：\n\n---\n{first_chapter_content}\n---\n\n写得对不对？有什么要改的您直接说，咱们慢慢改~"

    # 保存 AI 消息
    msg = Message(session_id=session_id, role="assistant", content=greeting)
    db.add(msg)
    db.commit()

    return {
        "reply": greeting,
        "phase": "previewing",
        "previewing": True,
    }


@app.post("/api/sessions/{session_id}/chapters/{chapter_id}/revise")
def revise_chapter(
    session_id: str,
    chapter_id: int,
    req: ReviseRequest = Body(...),
    db: DbSession = Depends(get_db),
):
    feedback = req.feedback
    if not feedback.strip():
        raise HTTPException(status_code=400, detail="修改意见不能为空")

    session = _get_session(db, session_id)
    chapter = db.query(Chapter).filter(Chapter.id == chapter_id, Chapter.session_id == session_id).first()
    if not chapter:
        raise HTTPException(status_code=404, detail="章节不存在")

    all_messages = [
        m.content for m in db.query(Message)
        .filter(Message.session_id == session_id, Message.role.in_(["user", "assistant"]))
        .all()
    ]
    relevant = "\n".join(all_messages[-100:])

    revised = ai.revise_chapter(chapter.content, feedback, relevant)
    chapter.content = revised
    chapter.status = "reviewed"
    db.commit()

    return {"id": chapter.id, "title": chapter.title, "content": chapter.content, "order": chapter.order, "status": chapter.status}


@app.get("/api/sessions/{session_id}/export")
def export_book(
    session_id: str,
    format: str = Query(default="docx", pattern="^(docx|pdf)$"),
    db: DbSession = Depends(get_db),
):
    session = _get_session(db, session_id)
    chapters = db.query(Chapter).filter(Chapter.session_id == session_id).order_by(Chapter.order).all()

    if not chapters:
        raise HTTPException(status_code=400, detail="还没有生成章节，请先开始写书")

    book_title = "我的人生故事"
    chapters_data = [{"title": ch.title, "content": ch.content} for ch in chapters]

    filepath = export_lib.export_book(book_title=book_title, chapters=chapters_data, format=format)

    media_type = (
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
        if format == "docx" else "application/pdf"
    )
    return FileResponse(path=filepath, filename=f"回忆录.{format}", media_type=media_type)


@app.get("/")
def index():
    import os
    html_path = os.path.join(os.path.dirname(__file__), "..", "frontend", "index.html")
    if os.path.exists(html_path):
        with open(html_path, "r", encoding="utf-8") as f:
            return HTMLResponse(content=f.read())
    return HTMLResponse(content="<h1>前端页面未找到</h1>", status_code=404)


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
