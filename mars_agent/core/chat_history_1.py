from datetime import datetime
from typing import Optional, List
from sqlalchemy import Column, Integer, String, Text, DateTime
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, Session
from sqlalchemy import create_engine

Base = declarative_base()


class ChatHistory(Base):
    """聊天历史记录模型"""
    __tablename__ = "chat_history"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    agent_id = Column(Integer, nullable=False, comment="代理ID")
    user_message = Column(Text, nullable=False, comment="用户消息")
    ai_message = Column(Text, nullable=False, comment="AI回复消息")
    created_at = Column(DateTime, default=datetime.utcnow, comment="创建时间")

    def __repr__(self):
        return f"<ChatHistory(id={self.id}, agent_id={self.agent_id}, created_at={self.created_at})>"


class ChatHistoryDAO:
    """聊天历史记录数据访问对象（使用classmethod形式）"""

    # 类级别的数据库连接配置
    _engine = None
    _SessionLocal = None
    _db_url = "sqlite:///./chat_history.db"

    @classmethod
    def _init_db(cls):
        """初始化数据库连接（延迟初始化）"""
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
            # 创建所有表
            Base.metadata.create_all(bind=cls._engine)

    @classmethod
    def get_session(cls) -> Session:
        """获取数据库会话"""
        cls._init_db()
        return cls._SessionLocal()

    @classmethod
    def create_history(cls, agent_id: int, user_message: str, ai_message: str) -> ChatHistory:
        """创建历史记录"""
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
        """根据ID获取历史记录"""
        with cls.get_session() as session:
            return session.query(ChatHistory).filter(ChatHistory.id == history_id).first()

    @classmethod
    def get_history_by_agent_id(cls, agent_id: int, limit: int = 50) -> List[ChatHistory]:
        """根据代理ID获取历史记录"""
        with cls.get_session() as session:
            return session.query(ChatHistory) \
                .filter(ChatHistory.agent_id == agent_id) \
                .order_by(ChatHistory.created_at.desc()) \
                .limit(limit) \
                .all()

    @classmethod
    def get_all_history(cls, limit: int = 100) -> List[ChatHistory]:
        """获取所有历史记录"""
        with cls.get_session() as session:
            return session.query(ChatHistory) \
                .order_by(ChatHistory.created_at.desc()) \
                .limit(limit) \
                .all()

    @classmethod
    def delete_history_by_id(cls, history_id: int) -> bool:
        """根据ID删除历史记录"""
        with cls.get_session() as session:
            history = session.query(ChatHistory).filter(ChatHistory.id == history_id).first()
            if history:
                session.delete(history)
                session.commit()
                return True
            return False

    @classmethod
    def delete_history_by_agent_id(cls, agent_id: int) -> int:
        """根据代理ID删除历史记录，返回删除的记录数"""
        with cls.get_session() as session:
            count = session.query(ChatHistory).filter(ChatHistory.agent_id == agent_id).count()
            session.query(ChatHistory).filter(ChatHistory.agent_id == agent_id).delete()
            session.commit()
            return count

    @classmethod
    def update_history(cls, history_id: int, user_message: str = None, ai_message: str = None) -> Optional[ChatHistory]:
        """更新历史记录"""
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
        """搜索历史记录"""
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
        """获取历史记录数量"""
        with cls.get_session() as session:
            query = session.query(ChatHistory)
            if agent_id is not None:
                query = query.filter(ChatHistory.agent_id == agent_id)
            return query.count()

    @classmethod
    def set_db_url(cls, db_url: str) -> None:
        """设置数据库连接URL"""
        cls._db_url = db_url
        # 重置数据库连接
        cls._engine = None
        cls._SessionLocal = None


# 使用示例
if __name__ == "__main__":
    # 可以选择设置自定义数据库URL
    # ChatHistoryDAO.set_db_url("sqlite:///./custom_chat_history.db")

    # 直接通过类方法调用，无需创建实例
    history = ChatHistoryDAO.create_history(
        agent_id=1,
        user_message="你好，请介绍一下自己",
        ai_message="你好！我是AI助手，很高兴为您服务。"
    )
    print(f"创建的历史记录: {history}")

    # 获取指定代理的历史记录
    histories = ChatHistoryDAO.get_history_by_agent_id(agent_id=1, limit=10)
    print(f"代理1的历史记录数量: {len(histories)}")

    # 搜索历史记录
    search_results = ChatHistoryDAO.search_history("你好")
    print(f"搜索结果数量: {len(search_results)}")
