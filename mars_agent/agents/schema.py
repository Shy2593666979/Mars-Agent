from typing import Union, Optional, Literal, Any, List

from pydantic.v1 import BaseModel, Field


#from langchain_core.messages import BaseMessage, AIMessage, ToolMessage, HumanMessage, SystemMessage

class BaseMessage(BaseModel):
    content: Union[str, List[Union[str, dict]]]
    additional_kwargs: dict = Field(default_factory=dict)
    response_metadata: dict = Field(default_factory=dict)
    type: str
    name: Optional[str] = None
    id: Optional[str] = None

    def __init__(
            self, content: Union[str, List[Union[str, dict]]], **kwargs: Any
    ) -> None:
        super().__init__(content=content, **kwargs)


class HumanMessage(BaseMessage):
    type: Literal["human"] = "human"

    def __init__(
            self, content: Union[str, List[Union[str, dict]]], **kwargs: Any
    ) -> None:
        super().__init__(content=content, **kwargs)

class SystemMessage(BaseMessage):
    type: Literal["system"] = "system"

    def __init__(
            self, content: Union[str, List[Union[str, dict]]], **kwargs: Any
    ) -> None:
        super().__init__(content=content, **kwargs)


class AIMessage(BaseMessage):
    type: Literal["ai"] = "ai"

    def __init__(
            self, content: Union[str, List[Union[str, dict]]], **kwargs: Any
    ) -> None:
        super().__init__(content=content, **kwargs)

class ToolMessage(BaseMessage):
    type: Literal["tool"] = "tool"

    def __init__(
            self, content: Union[str, List[Union[str, dict]]], **kwargs: Any
    ) -> None:
        super().__init__(content=content, **kwargs)