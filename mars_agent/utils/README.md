# Mars Agent 事件管理器

## 概述

Mars Agent 事件管理器提供了统一的事件处理方案，用于替代项目中重复的 `yield` 代码模式。通过使用 `EventManager`，您可以：

- 🔄 **统一事件格式**：标准化所有流式事件的数据结构
- 🚀 **减少重复代码**：消除大量重复的 yield 代码块
- 🎯 **类型安全**：提供完整的类型注解和枚举支持
- 💡 **易于维护**：集中管理事件逻辑，便于修改和扩展

## 问题现状

在当前代码库中，存在大量重复的 yield 代码模式：

```python
# 心跳事件 - 在多个文件中重复
yield {
    "type": "heartbeat",
    "timestamp": time.time(),
    "data": {"message": "连接保持中..."}
}

# 响应块事件 - 在多个文件中重复  
yield {
    "type": "response_chunk",
    "timestamp": time.time(),
    "data": {
        "chunk": chunk.content,
        "accumulated": response_content
    }
}

# 进度事件 - 在多个文件中重复
yield {
    "type": "event", 
    "timestamp": time.time(),
    "data": {
        "title": f"执行 MCP Agent: {name}",
        "message": "开始执行...",
        "status": "START"
    }
}
```

## 解决方案

### 1. 基本用法

```python
from mars_agent.utils.event_manager import EventManager

# 创建事件管理器
event_manager = EventManager()

# 替代原有的重复代码
async def improved_stream_method():
    # 心跳事件 - 一行代码
    yield event_manager.create_heartbeat_event()
    
    # 响应块事件 - 一行代码  
    yield event_manager.create_response_chunk_event(chunk, accumulated)
    
    # 进度事件 - 一行代码
    yield event_manager.create_progress_event("任务名", "消息", "START")
```

### 2. 高级用法

```python
# 带心跳的流式处理
async def advanced_stream(tasks):
    async for event in event_manager.stream_with_heartbeat(tasks):
        yield event

# 错误处理
try:
    # 处理逻辑
    yield event_manager.create_response_chunk_event("成功", "完成")
except Exception as err:
    yield event_manager.create_event(EventType.ERROR, {"error": str(err)})
```

## 重构指南

### 步骤 1: 导入事件管理器

```python
from mars_agent.utils.event_manager import EventManager, EventType
```

### 步骤 2: 创建事件管理器实例

```python
class YourAgent:
    def __init__(self):
        self.event_manager = EventManager(self.event_queue)
```

### 步骤 3: 替换重复的 yield 代码

**原始代码:**
```python
# 大量重复的代码
yield {
    "type": "heartbeat",
    "timestamp": time.time(), 
    "data": {"message": "连接保持中..."}
}
```

**重构后:**
```python
# 简洁的一行代码
yield self.event_manager.create_heartbeat_event()
```

### 步骤 4: 使用类型安全的枚举

```python
# 使用枚举替代字符串字面量
yield self.event_manager.create_event(EventType.PROGRESS, data)
```

## API 参考

### EventManager 类

#### 主要方法

- `create_heartbeat_event(message)`: 创建心跳事件
- `create_response_chunk_event(chunk, accumulated)`: 创建响应块事件  
- `create_progress_event(title, message, status)`: 创建进度事件
- `create_event(event_type, data)`: 创建通用事件
- `stream_with_heartbeat(tasks)`: 带心跳的流式处理

#### EventType 枚举

- `HEARTBEAT`: 心跳事件
- `RESPONSE_CHUNK`: 响应块事件
- `EVENT`: 通用事件
- `PROGRESS`: 进度事件
- `ERROR`: 错误事件
- `START`: 开始事件  
- `END`: 结束事件

## 迁移清单

以下文件需要重构以使用新的事件管理器：

- [ ] `mars_agent/agent.py` - astream 方法中的 yield 代码
- [ ] `mars_agent/agents/stream_agent.py` - 流式处理中的 yield 代码
- [ ] `mars_agent/agents/mcp_agent.py` - emit_event 方法的使用

## 性能优势

1. **代码减少**: 每个 yield 事件从 6-8 行减少到 1 行
2. **内存优化**: 统一的事件创建避免重复的字典构建
3. **类型安全**: 编译时类型检查减少运行时错误
4. **维护性**: 集中的事件逻辑便于统一修改

## 示例

完整的使用示例请参考 `mars_agent/examples/refactor_example.py` 文件。

---

**注意**: 这个重构保持了所有现有功能不变，只是统一了代码模式，提高了可维护性。 