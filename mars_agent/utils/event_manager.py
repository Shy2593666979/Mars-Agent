"""
Mars Agent 事件管理器

此模块提供统一的事件管理功能，用于标准化项目中的流式事件处理。

Classes:
    EventType: 事件类型枚举
    StreamEvent: 流式事件数据类
    EventManager: 事件管理器类
"""

import time
import asyncio
from enum import Enum
from typing import Dict, Any, Optional, AsyncGenerator, Union
from dataclasses import dataclass
from pydantic import BaseModel


class EventType(str, Enum):
    """
    事件类型枚举
    
    定义了系统中支持的所有事件类型。
    """
    HEARTBEAT = "heartbeat"
    RESPONSE_CHUNK = "response_chunk"
    EVENT = "event"
    START = "start"
    END = "end"
    ERROR = "error"
    PROGRESS = "progress"


@dataclass
class StreamEvent:
    """
    流式事件数据类
    
    Attributes:
        type (EventType): 事件类型
        timestamp (float): 事件时间戳
        data (Dict[str, Any]): 事件数据
    """
    type: EventType
    timestamp: float
    data: Dict[str, Any]

    def to_dict(self) -> Dict[str, Any]:
        """
        将事件转换为字典格式
        
        Returns:
            Dict[str, Any]: 事件的字典表示
        """
        return {
            "type": self.type.value,
            "timestamp": self.timestamp,
            "data": self.data
        }


class EventManager:
    """
    事件管理器类
    
    提供统一的事件创建、发送和管理功能。
    """
    
    def __init__(self, event_queue: Optional[asyncio.Queue] = None):
        """
        初始化事件管理器
        
        Args:
            event_queue (Optional[asyncio.Queue]): 事件队列，如果未提供则创建新队列
        """
        self.event_queue = event_queue or asyncio.Queue()
    
    @staticmethod
    def create_heartbeat_event(message: str = "连接保持中...") -> Dict[str, Any]:
        """
        创建心跳事件
        
        Args:
            message (str): 心跳消息
            
        Returns:
            Dict[str, Any]: 心跳事件字典
        """
        return {
            "type": EventType.HEARTBEAT.value,
            "timestamp": time.time(),
            "data": {"message": message}
        }
    
    @staticmethod
    def create_response_chunk_event(
        chunk: str, 
        accumulated: str, 
        additional_data: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """
        创建响应块事件
        
        Args:
            chunk (str): 当前响应块内容
            accumulated (str): 累积的响应内容
            additional_data (Optional[Dict[str, Any]]): 额外的数据
            
        Returns:
            Dict[str, Any]: 响应块事件字典
        """
        data = {
            "chunk": chunk,
            "accumulated": accumulated
        }
        if additional_data:
            data.update(additional_data)
            
        return {
            "type": EventType.RESPONSE_CHUNK.value,
            "timestamp": time.time(),
            "data": data
        }
    
    @staticmethod
    def create_event(
        event_type: Union[EventType, str], 
        data: Dict[str, Any], 
        timestamp: Optional[float] = None
    ) -> Dict[str, Any]:
        """
        创建通用事件
        
        Args:
            event_type (Union[EventType, str]): 事件类型
            data (Dict[str, Any]): 事件数据
            timestamp (Optional[float]): 时间戳，如果未提供则使用当前时间
            
        Returns:
            Dict[str, Any]: 事件字典
        """
        if isinstance(event_type, EventType):
            event_type = event_type.value
            
        return {
            "type": event_type,
            "timestamp": timestamp or time.time(),
            "data": data
        }
    
    @staticmethod
    def create_progress_event(
        title: str, 
        message: str, 
        status: str, 
        progress: Optional[int] = None
    ) -> Dict[str, Any]:
        """
        创建进度事件
        
        Args:
            title (str): 进度标题
            message (str): 进度消息
            status (str): 状态（START/END/PROGRESS）
            progress (Optional[int]): 进度百分比
            
        Returns:
            Dict[str, Any]: 进度事件字典
        """
        data = {
            "title": title,
            "message": message,
            "status": status
        }
        if progress is not None:
            data["progress"] = progress
            
        return {
            "type": EventType.PROGRESS.value,
            "timestamp": time.time(),
            "data": data
        }
    
    async def emit_event(self, event_data: Dict[str, Any]) -> None:
        """
        发送事件到队列
        
        Args:
            event_data (Dict[str, Any]): 事件数据
        """
        await self.event_queue.put(event_data)
    
    async def emit_heartbeat(self, message: str = "连接保持中...") -> None:
        """
        发送心跳事件
        
        Args:
            message (str): 心跳消息
        """
        event = self.create_heartbeat_event(message)
        await self.emit_event(event)
    
    async def emit_response_chunk(
        self, 
        chunk: str, 
        accumulated: str, 
        additional_data: Optional[Dict[str, Any]] = None
    ) -> None:
        """
        发送响应块事件
        
        Args:
            chunk (str): 当前响应块内容
            accumulated (str): 累积的响应内容
            additional_data (Optional[Dict[str, Any]]): 额外的数据
        """
        event = self.create_response_chunk_event(chunk, accumulated, additional_data)
        await self.emit_event(event)
    
    async def emit_progress(
        self, 
        title: str, 
        message: str, 
        status: str, 
        progress: Optional[int] = None
    ) -> None:
        """
        发送进度事件
        
        Args:
            title (str): 进度标题
            message (str): 进度消息
            status (str): 状态（START/END/PROGRESS）
            progress (Optional[int]): 进度百分比
        """
        event = self.create_progress_event(title, message, status, progress)
        await self.emit_event(event)
    
    async def stream_with_heartbeat(
        self, 
        tasks: list, 
        heartbeat_interval: float = 5.0,
        heartbeat_message: str = "连接保持中..."
    ) -> AsyncGenerator[Dict[str, Any], None]:
        """
        带心跳的流式处理器
        
        Args:
            tasks (list): 要监控的异步任务列表
            heartbeat_interval (float): 心跳间隔（秒）
            heartbeat_message (str): 心跳消息
            
        Yields:
            Dict[str, Any]: 事件数据
        """
        conversation_ended = False
        
        while not conversation_ended:
            try:
                # 等待事件或超时
                event = await asyncio.wait_for(
                    self.event_queue.get(), 
                    timeout=heartbeat_interval
                )
                yield event
                
            except asyncio.TimeoutError:
                # 发送心跳事件
                yield self.create_heartbeat_event(heartbeat_message)
            
            # 检查任务执行是否完成
            if all(task.done() for task in tasks if task is not None):
                conversation_ended = True


# 全局事件管理器实例
_global_event_manager: Optional[EventManager] = None


def get_global_event_manager() -> EventManager:
    """
    获取全局事件管理器实例
    
    Returns:
        EventManager: 全局事件管理器
    """
    global _global_event_manager
    if _global_event_manager is None:
        _global_event_manager = EventManager()
    return _global_event_manager


def set_global_event_manager(event_manager: EventManager) -> None:
    """
    设置全局事件管理器实例
    
    Args:
        event_manager (EventManager): 事件管理器实例
    """
    global _global_event_manager
    _global_event_manager = event_manager 