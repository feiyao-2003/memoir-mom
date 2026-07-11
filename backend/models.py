import uuid
import datetime
from sqlalchemy import Column, String, Integer, DateTime, Text, ForeignKey
from sqlalchemy.orm import relationship
from database import Base


def generate_uuid():
    return str(uuid.uuid4())


class Session(Base):
    __tablename__ = "sessions"

    id = Column(String, primary_key=True, default=generate_uuid)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.datetime.utcnow, onupdate=datetime.datetime.utcnow)
    phase = Column(String, default="style_select")  # style_select | info_collect | chatting | reviewing | done
    style_preference = Column(Text, default="")
    basic_info = Column(Text, default="")  # JSON: {birth_year, hometown, background, ...}
    custom_stages = Column(Text, default="")  # JSON: [{label, key, order}, ...]
    current_stage_index = Column(Integer, default=0)  # 当前在聊第几个篇章
    narrative_style = Column(String, default="")  # 叙事方式：chronological / nonlinear / 空=未选

    # Relationships
    messages = relationship("Message", back_populates="session", order_by="Message.created_at")
    topic_coverages = relationship("TopicCoverage", back_populates="session")
    chapters = relationship("Chapter", back_populates="session", order_by="Chapter.order")


class Message(Base):
    __tablename__ = "messages"

    id = Column(Integer, primary_key=True, autoincrement=True)
    session_id = Column(String, ForeignKey("sessions.id"), nullable=False)
    role = Column(String, nullable=False)  # user | assistant | system
    content = Column(Text, nullable=False)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)

    session = relationship("Session", back_populates="messages")


class TopicCoverage(Base):
    __tablename__ = "topic_coverage"

    id = Column(Integer, primary_key=True, autoincrement=True)
    session_id = Column(String, ForeignKey("sessions.id"), nullable=False)
    topic_key = Column(String, nullable=False)  # e.g. childhood, school, career
    topic_label = Column(String, nullable=False)  # e.g. 童年时光
    coverage_score = Column(Integer, default=0)  # 0-100
    last_discussed_at = Column(DateTime, default=datetime.datetime.utcnow)

    session = relationship("Session", back_populates="topic_coverages")


class Chapter(Base):
    __tablename__ = "chapters"

    id = Column(Integer, primary_key=True, autoincrement=True)
    session_id = Column(String, ForeignKey("sessions.id"), nullable=False)
    title = Column(String, nullable=False)
    content = Column(Text, default="")
    order = Column(Integer, default=0)
    status = Column(String, default="draft")  # draft | reviewed | final

    session = relationship("Session", back_populates="chapters")
