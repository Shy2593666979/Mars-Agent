import inspect
from typing import Any, Literal, Union, Optional, Callable, Annotated, Awaitable, get_origin, get_args, TypeVar

from pydantic.v1 import BaseModel as BaseModelV1
from pydantic import ConfigDict, ValidationError, BaseModel, SkipValidation, Field


class ValidationErrorV1:
    pass

TypeBaseModel = type[BaseModel]
ArgsSchema = Union[TypeBaseModel, dict[str, Any]]

class ToolException(Exception):
    """Exception thrown when a tool execution error occurs.

    This exception allows tools to signal errors without stopping the agent.
    The error is handled according to the tool's handle_tool_error setting,
    and the result is returned as an observation to the agent.
    """

class BaseTool(BaseModel):
    """Base class for all LangChain tools.

    This abstract class defines the interface that all LangChain tools must implement.
    Tools are components that can be called by agents to perform specific actions.
    """

    name: str
    """The unique name of the tool that clearly communicates its purpose."""
    description: str
    """Used to tell the model how/when/why to use the tool.

    You can provide few-shot examples as a part of the description.
    """

    args_schema: Annotated[Optional[ArgsSchema], SkipValidation()] = Field(
        default=None, description="The tool schema."
    )
    """Pydantic model class to validate and parse the tool's input arguments.

    Args schema should be either:

    - A subclass of pydantic.BaseModel.
    - A subclass of pydantic.v1.BaseModel if accessing v1 namespace in pydantic 2
    - a JSON schema dict
    """
    return_direct: bool = False
    """Whether to return the tool's output directly.

    Setting this to True means
    that after the tool is called, the AgentExecutor will stop looping.
    """
    verbose: bool = False
    """Whether to log the tool's progress."""

    tags: Optional[list[str]] = None
    """Optional list of tags associated with the tool. Defaults to None.
    These tags will be associated with each call to this tool,
    and passed as arguments to the handlers defined in `callbacks`.
    You can use these to eg identify a specific instance of a tool with its use case.
    """
    metadata: Optional[dict[str, Any]] = None
    """Optional metadata associated with the tool. Defaults to None.
    This metadata will be associated with each call to this tool,
    and passed as arguments to the handlers defined in `callbacks`.
    You can use these to eg identify a specific instance of a tool with its use case.
    """

    handle_tool_error: Optional[Union[bool, str, Callable[[ToolException], str]]] = (
        False
    )
    """Handle the content of the ToolException thrown."""

    handle_validation_error: Optional[
        Union[bool, str, Callable[[Union[ValidationError, ValidationErrorV1]], str]]
    ] = False
    """Handle the content of the ValidationError thrown."""

    response_format: Literal["content", "content_and_artifact"] = "content"
    """The tool response format. Defaults to 'content'.

    If "content" then the output of the tool is interpreted as the contents of a
    ToolMessage. If "content_and_artifact" then the output is expected to be a
    two-tuple corresponding to the (content, artifact) of a ToolMessage.
    """

    def __init__(self, **kwargs: Any) -> None:
        """Initialize the tool."""
        if (
            "args_schema" in kwargs
            and kwargs["args_schema"] is not None
            and not isinstance(kwargs["args_schema"], dict)
        ):
            msg = (
                "args_schema must be a subclass of pydantic BaseModel or "
                f"a JSON schema dict. Got: {kwargs['args_schema']}."
            )
            raise TypeError(msg)
        super().__init__(**kwargs)

    model_config = ConfigDict(
        arbitrary_types_allowed=True,
    )


class InjectedToolArg:
    """Annotation for tool arguments that are injected at runtime.

    Tool arguments annotated with this class are not included in the tool
    schema sent to language models and are instead injected during execution.
    """

class StructuredTool(BaseTool):
    """Tool that can operate on any number of inputs."""

    description: str = ""
    args_schema: Annotated[ArgsSchema, SkipValidation()] = Field(
        ..., description="The tool schema."
    )
    """The input arguments' schema."""
    func: Optional[Callable[..., Any]] = None
    """The function to run when the tool is called."""
    coroutine: Optional[Callable[..., Awaitable[Any]]] = None
    """The asynchronous version of the function."""

class Tool(BaseTool):
    """Tool that takes in function or coroutine directly."""

    description: str = ""
    func: Optional[Callable[..., str]]
    """The function to run when the tool is called."""
    coroutine: Optional[Callable[..., Awaitable[str]]] = None
    """The asynchronous version of the function."""
    @property
    def args(self) -> dict:
        """The tool's input arguments.

        Returns:
            The input arguments for the tool.
        """
        if self.args_schema is not None:
            if isinstance(self.args_schema, dict):
                json_schema = self.args_schema
            else:
                json_schema = self.args_schema.model_json_schema()
            return json_schema["properties"]
        # For backwards compatibility, if the function signature is ambiguous,
        # assume it takes a single string input.
        return {"tool_input": {"type": "string"}}

    def __init__(
        self, name: str, func: Optional[Callable], description: str, **kwargs: Any
    ) -> None:
        """Initialize tool."""
        super().__init__(name=name, func=func, description=description, **kwargs)


def _replace_type_vars(
    type_: type,
    generic_map: Optional[dict[TypeVar, type]] = None,
    *,
    default_to_bound: bool = True,
) -> type:
    """Replace TypeVars in a type annotation with concrete types.

    Args:
        type_: The type annotation to process.
        generic_map: Mapping of TypeVars to concrete types.
        default_to_bound: Whether to use TypeVar bounds as defaults.

    Returns:
        The type with TypeVars replaced.
    """
    generic_map = generic_map or {}
    if isinstance(type_, TypeVar):
        if type_ in generic_map:
            return generic_map[type_]
        if default_to_bound:
            return type_.__bound__ or Any
        return type_
    if (origin := get_origin(type_)) and (args := get_args(type_)):
        new_args = tuple(
            _replace_type_vars(arg, generic_map, default_to_bound=default_to_bound)
            for arg in args
        )
        return _py_38_safe_origin(origin)[new_args]  # type: ignore[index]
    return type_



def is_pydantic_v1_subclass(cls: type) -> bool:
    """Check if the installed Pydantic version is 1.x-like."""
    return issubclass(cls, BaseModelV1)


def is_pydantic_v2_subclass(cls: type) -> bool:
    """Check if the installed Pydantic version is 1.x-like."""
    return issubclass(cls, BaseModel)

def get_all_basemodel_annotations(
    cls: Union[TypeBaseModel, Any], *, default_to_bound: bool = True
) -> dict[str, type]:
    """Get all annotations from a Pydantic BaseModel and its parents.

    Args:
        cls: The Pydantic BaseModel class.
        default_to_bound: Whether to default to the bound of a TypeVar if it exists.
    """
    # cls has no subscript: cls = FooBar
    if isinstance(cls, type):
        # Gather pydantic field objects (v2: model_fields / v1: __fields__)
        fields = getattr(cls, "model_fields", {}) or getattr(cls, "__fields__", {})
        alias_map = {field.alias: name for name, field in fields.items() if field.alias}

        annotations: dict[str, type] = {}
        for name, param in inspect.signature(cls).parameters.items():
            # Exclude hidden init args added by pydantic Config. For example if
            # BaseModel(extra="allow") then "extra_data" will part of init sig.
            if fields and name not in fields and name not in alias_map:
                continue
            field_name = alias_map.get(name, name)
            annotations[field_name] = param.annotation
        orig_bases: tuple = getattr(cls, "__orig_bases__", ())
    # cls has subscript: cls = FooBar[int]
    else:
        annotations = get_all_basemodel_annotations(
            get_origin(cls), default_to_bound=False
        )
        orig_bases = (cls,)

    # Pydantic v2 automatically resolves inherited generics, Pydantic v1 does not.
    if not (isinstance(cls, type) and is_pydantic_v2_subclass(cls)):
        # if cls = FooBar inherits from Baz[str], orig_bases will contain Baz[str]
        # if cls = FooBar inherits from Baz, orig_bases will contain Baz
        # if cls = FooBar[int], orig_bases will contain FooBar[int]
        for parent in orig_bases:
            # if class = FooBar inherits from Baz, parent = Baz
            if isinstance(parent, type) and is_pydantic_v1_subclass(parent):
                annotations.update(
                    get_all_basemodel_annotations(parent, default_to_bound=False)
                )
                continue

            parent_origin = get_origin(parent)

            # if class = FooBar inherits from non-pydantic class
            if not parent_origin:
                continue

            # if class = FooBar inherits from Baz[str]:
            # parent = Baz[str],
            # parent_origin = Baz,
            # generic_type_vars = (type vars in Baz)
            # generic_map = {type var in Baz: str}
            generic_type_vars: tuple = getattr(parent_origin, "__parameters__", ())
            generic_map = dict(zip(generic_type_vars, get_args(parent)))
            for field in getattr(parent_origin, "__annotations__", {}):
                annotations[field] = _replace_type_vars(
                    annotations[field], generic_map, default_to_bound=default_to_bound
                )

    return {
        k: _replace_type_vars(v, default_to_bound=default_to_bound)
        for k, v in annotations.items()
    }