from sqlalchemy import Column, Integer, String, DateTime, Text, JSON
from sqlalchemy.orm import declarative_base
from datetime import datetime, timezone


def utc_now():
    return datetime.now(timezone.utc)

Base = declarative_base()


class KnowledgeDocument(Base):
    __tablename__ = 'knowledge_documents'
    id = Column(Integer, primary_key=True)
    content = Column(Text, nullable=False)
    category = Column(String, nullable=False)
    keywords = Column(JSON, nullable=True)
    embedding = Column(JSON, nullable=True)
    created_at = Column(DateTime, default=utc_now)
    updated_at = Column(DateTime, default=utc_now, onupdate=utc_now)
    is_active = Column(Integer, default=1)


class UserBehavior(Base):
    __tablename__ = 'user_behaviors'
    id = Column(Integer, primary_key=True)
    user_id = Column(String, nullable=False, default='default_user')
    # action_type: 'incident_escalation', 'runbook_lookup', 'comms_drafting', 'postmortem'
    action_type = Column(String, nullable=False)
    action_data = Column(JSON, nullable=True)
    session_id = Column(String, nullable=True)
    created_at = Column(DateTime, default=utc_now)


class UserPreference(Base):
    __tablename__ = 'user_preferences'
    id = Column(Integer, primary_key=True)
    user_id = Column(String, nullable=False, default='default_user')
    # preference_type: 'service', 'severity', 'team'
    preference_type = Column(String, nullable=False)
    preference_value = Column(String, nullable=False)
    confidence_score = Column(Integer, default=1)
    last_updated = Column(DateTime, default=utc_now, onupdate=utc_now)


class UserRecommendation(Base):
    __tablename__ = 'user_recommendations'
    id = Column(Integer, primary_key=True)
    user_id = Column(String, nullable=False, default='default_user')
    # recommendation_type: 'postmortem_reminder', 'pattern_alert', 'runbook_suggestion'
    recommendation_type = Column(String, nullable=False)
    content = Column(Text, nullable=False)
    is_sent = Column(Integer, default=0)
    created_at = Column(DateTime, default=utc_now)
    sent_at = Column(DateTime, nullable=True)
