from datetime import datetime
from typing import Optional, List
from sqlalchemy import Column, Integer, String, Text, DateTime
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, Session
from sqlalchemy import create_engine

Base = declarative_base()


class ChatHistory(Base):
    """Chat history record model"""
    __tablename__ = "chat_history"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    agent_id = Column(Integer, nullable=False, comment="Agent ID")
    user_message = Column(Text, nullable=False, comment="User message")
    ai_message = Column(Text, nullable=False, comment="AI reply message")
    created_at = Column(DateTime, default=datetime.utcnow, comment="Creation time")

    def __repr__(self):
        return f"<ChatHistory(id={self.id}, agent_id={self.agent_id}, created_at={self.created_at})>"


class ChatHistoryDAO:
    """Chat history data access object (using classmethod form)"""

    # Class-level database connection configuration
    _engine = None
    _SessionLocal = None
    _db_url = "sqlite:///./chat_history.db"

    @classmethod
    def _init_db(cls):
        """Initialize database connection (lazy initialization)"""
        if cls._engine is None:
            cls._engine = create_engine(
                cls._db_url,
                connect_args={"check_same_thread": False}
            )
            cls._SessionLocal = sessionmaker(
                autocommit=False,
                autoflush=False,
                bind=cls._engine
            )
            # Create all tables
            Base.metadata.create_all(bind=cls._engine)

    @classmethod
    def get_session(cls) -> Session:
        """Get database session"""
        cls._init_db()
        return cls._SessionLocal()

    @classmethod
    def create_history(cls, agent_id: int, user_message: str, ai_message: str) -> ChatHistory:
        """Create history record"""
        with cls.get_session() as session:
            history = ChatHistory(
                agent_id=agent_id,
                user_message=user_message,
                ai_message=ai_message
            )
            session.add(history)
            session.commit()
            session.refresh(history)
            return history

    @classmethod
    def get_history_by_id(cls, history_id: int) -> Optional[ChatHistory]:
        """Get history record by ID"""
        with cls.get_session() as session:
            return session.query(ChatHistory).filter(ChatHistory.id == history_id).first()

    @classmethod
    def get_history_by_agent_id(cls, agent_id: int, limit: int = 50) -> List[ChatHistory]:
        """Get history records by agent ID"""
        with cls.get_session() as session:
            return session.query(ChatHistory) \
                .filter(ChatHistory.agent_id == agent_id) \
                .order_by(ChatHistory.created_at.desc()) \
                .limit(limit) \
                .all()

    @classmethod
    def get_all_history(cls, limit: int = 100) -> List[ChatHistory]:
        """Get all history records"""
        with cls.get_session() as session:
            return session.query(ChatHistory) \
                .order_by(ChatHistory.created_at.desc()) \
                .limit(limit) \
                .all()

    @classmethod
    def delete_history_by_id(cls, history_id: int) -> bool:
        """Delete history record by ID"""
        with cls.get_session() as session:
            history = session.query(ChatHistory).filter(ChatHistory.id == history_id).first()
            if history:
                session.delete(history)
                session.commit()
                return True
            return False

    @classmethod
    def delete_history_by_agent_id(cls, agent_id: int) -> int:
        """Delete history records by agent ID, return number of deleted records"""
        with cls.get_session() as session:
            count = session.query(ChatHistory).filter(ChatHistory.agent_id == agent_id).count()
            session.query(ChatHistory).filter(ChatHistory.agent_id == agent_id).delete()
            session.commit()
            return count

    @classmethod
    def update_history(cls, history_id: int, user_message: str = None, ai_message: str = None) -> Optional[ChatHistory]:
        """Update history record"""
        with cls.get_session() as session:
            history = session.query(ChatHistory).filter(ChatHistory.id == history_id).first()
            if history:
                if user_message is not None:
                    history.user_message = user_message
                if ai_message is not None:
                    history.ai_message = ai_message
                session.commit()
                session.refresh(history)
                return history
            return None

    @classmethod
    def search_history(cls, keyword: str, limit: int = 50) -> List[ChatHistory]:
        """Search history records"""
        with cls.get_session() as session:
            return session.query(ChatHistory) \
                .filter(
                (ChatHistory.user_message.contains(keyword)) |
                (ChatHistory.ai_message.contains(keyword))
            ) \
                .order_by(ChatHistory.created_at.desc()) \
                .limit(limit) \
                .all()

    @classmethod
    def get_history_count(cls, agent_id: Optional[int] = None) -> int:
        """Get history record count"""
        with cls.get_session() as session:
            query = session.query(ChatHistory)
            if agent_id is not None:
                query = query.filter(ChatHistory.agent_id == agent_id)
            return query.count()

    @classmethod
    def set_db_url(cls, db_url: str) -> None:
        """Set database connection URL"""
        cls._db_url = db_url
        # Reset database connection
        cls._engine = None
        cls._SessionLocal = None


# Usage example
if __name__ == "__main__":
    # Optionally set custom database URL
    # ChatHistoryDAO.set_db_url("sqlite:///./custom_chat_history.db")

    # Call directly through class methods, no need to create instance
    history = ChatHistoryDAO.create_history(
        agent_id=1,
        user_message="Hello, please introduce yourself",
        ai_message="Hello! I am an AI assistant, happy to serve you."
    )
    print(f"Created history record: {history}")

    # Get history records for specified agent
    histories = ChatHistoryDAO.get_history_by_agent_id(agent_id=1, limit=10)
    print(f"Number of history records for agent 1: {len(histories)}")

    # Search history records
    search_results = ChatHistoryDAO.search_history("Hello")
    print(f"Number of search results: {len(search_results)}")
