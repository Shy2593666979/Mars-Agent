"""
Mars Agent Event Manager

This module provides unified event management functionality for standardizing streaming event processing in the project.

Classes:
    EventType: Event type enumeration
    StreamEvent: Streaming event data class
    EventManager: Event manager class
"""

import time
import asyncio
from enum import Enum
from typing import Dict, Any, Optional, AsyncGenerator, Union
from dataclasses import dataclass
from pydantic import BaseModel

from mars_agent.schema import ProgressModel, ResponseModel, MarsResponseChunk, MarsProgressChunk, MarsBaseChunk, \
    MarsHeartbeatChunk


class EventType(str, Enum):
    """
    Event type enumeration
    
    Defines all event types supported by the system.
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
    Streaming event data class
    
    Attributes:
        type (EventType): Event type
        timestamp (float): Event timestamp
        data (Dict[str, Any]): Event data
    """
    type: EventType
    timestamp: float
    data: Dict[str, Any]

    def to_dict(self) -> Dict[str, Any]:
        """
        Convert event to dictionary format
        
        Returns:
            Dict[str, Any]: Dictionary representation of the event
        """
        return {
            "type": self.type.value,
            "timestamp": self.timestamp,
            "data": self.data
        }


class EventManager:
    """
    Event manager class
    
    Provides unified event creation, sending, and management functionality.
    """
    
    def __init__(self, event_queue: Optional[asyncio.Queue] = None):
        """
        Initialize event manager
        
        Args:
            event_queue (Optional[asyncio.Queue]): Event queue, create new queue if not provided
        """
        self.event_queue = event_queue or asyncio.Queue()
    
    @staticmethod
    def create_heartbeat_event(message: str = "Connection maintained...") -> Any:
        """
        Create heartbeat event
        
        Args:
            message (str): Heartbeat message
            
        Returns:
            Dict[str, Any]: Heartbeat event dictionary
        """

        return MarsHeartbeatChunk(
            type=EventType.HEARTBEAT.value,
            timestamp=time.time(),
            data={"message": message}
        )
    
    @staticmethod
    def create_response_chunk_event(
        content: str,
        accumulated: str, 
        additional_data: Optional[Dict[str, Any]] = None
    ) -> MarsBaseChunk:
        """
        Create response chunk event
        
        Args:
            content (str): Current response chunk content
            accumulated (str): Accumulated response content
            additional_data (Optional[Dict[str, Any]]): Additional data
            
        Returns:
            Response chunk event dictionary
        """
        data = ResponseModel(
            content=content,
            accumulated=accumulated
        )
        if additional_data:
            data.additional_data = additional_data
            
        return MarsResponseChunk(
            timestamp=time.time(),
            data=data
        )
    
    @staticmethod
    def create_event(
        event_type: Union[EventType, str], 
        data: Dict[str, Any], 
        timestamp: Optional[float] = None
    ) -> Dict[str, Any]:
        """
        Create generic event
        
        Args:
            event_type (Union[EventType, str]): Event type
            data (Dict[str, Any]): Event data
            timestamp (Optional[float]): Timestamp, use current time if not provided
            
        Returns:
            Event dictionary
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
        progress: Optional[int] = None,
        agent: Optional[str] = None
    ) -> MarsProgressChunk:
        """
        Create progress event
        
        Args:
            title (str): Progress title
            message (str): Progress message
            status (str): Status (START/END/PROGRESS)
            progress (Optional[int]): Progress percentage
            agent (Optional[str]): Agent name, indicates message source
            
        Returns:
            Progress event dictionary
        """
        data = ProgressModel(
            title=title,
            message=message,
            status=status,
            agent=agent
        )
            
        return MarsProgressChunk(
            timestamp=time.time(),
            data=data
        )
    
    async def emit_event(self, event_data: Union[Dict[str, Any], Any]) -> None:
        """
        Send event to queue
        
        Args:
            event_data (Dict[str, Any]): Event data
        """
        await self.event_queue.put(event_data)
    
    async def emit_heartbeat(self, message: str = "Connection maintained...") -> None:
        """
        Send heartbeat event
        
        Args:
            message (str): Heartbeat message
        """
        event = self.create_heartbeat_event(message)
        await self.emit_event(event)
    
    async def emit_response_chunk(
        self, 
        content: str,
        accumulated: str, 
        additional_data: Optional[Dict[str, Any]] = None
    ) -> None:
        """
        Send response chunk event
        
        Args:
            content (str): Current response chunk content
            accumulated (str): Accumulated response content
            additional_data (Optional[Dict[str, Any]]): Additional data
        """
        event = self.create_response_chunk_event(content, accumulated, additional_data)
        await self.emit_event(event)
    
    async def emit_progress(
        self, 
        title: str, 
        message: str, 
        status: str,
        agent: Optional[str] = None,
        progress: Optional[int] = None,
    ) -> None:
        """
        Send progress event
        
        Args:
            title (str): Progress title
            message (str): Progress message
            status (str): Status (START/END/PROGRESS)
            progress (Optional[int]): Progress percentage
            agent (Optional[str]): Agent name, indicates message source
        """
        event = self.create_progress_event(title, message, status, progress, agent)
        await self.emit_event(event)
    
    async def stream_with_heartbeat(
        self, 
        tasks: list, 
        heartbeat_interval: float = 5.0,
        heartbeat_message: str = "Connection maintained..."
    ) -> AsyncGenerator[Any, None]:
        """
        Streaming processor with heartbeat
        
        Args:
            tasks (list): List of async tasks to monitor
            heartbeat_interval (float): Heartbeat interval (seconds)
            heartbeat_message (str): Heartbeat message
            
        Yields:
            Dict[str, Any]: Event data
        """
        conversation_ended = False
        
        while not conversation_ended:
            try:
                # Wait for event or timeout
                event = await asyncio.wait_for(
                    self.event_queue.get(), 
                    timeout=heartbeat_interval
                )
                yield event
                
            except asyncio.TimeoutError:
                # Send heartbeat event
                yield self.create_heartbeat_event(heartbeat_message)
            
            # Check if task execution is completed
            if all(task.done() for task in tasks if task is not None):
                conversation_ended = True


# Global event manager instance
_global_event_manager: Optional[EventManager] = None


def get_global_event_manager() -> EventManager:
    """
    Get global event manager instance
    
    Returns:
        EventManager: Global event manager
    """
    global _global_event_manager
    if _global_event_manager is None:
        _global_event_manager = EventManager()
    return _global_event_manager


def set_global_event_manager(event_manager: EventManager) -> None:
    """
    Set global event manager instance
    
    Args:
        event_manager (EventManager): Event manager instance
    """
    global _global_event_manager
    _global_event_manager = event_manager 