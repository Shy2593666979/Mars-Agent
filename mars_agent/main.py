import asyncio

from mars_agent.agent import MarsAgent, MCPConfig
from mars_agent.types import MarsModelConfig


def test_get_weather(location: str):
    """查看提供地理位置的天气情况
    location: 提供的城市名称
    """
    return f"{location}的天气是真好啊，已经达到了40°"


async def main():
    mars = MarsAgent(
        model_config=MarsModelConfig(model="qwen3-coder-plus", api_key="sk-fc40dd0604f04142a0730793ec74585f", base_url="https://dashscope.aliyuncs.com/compatible-mode/v1"),
        functions = [test_get_weather],
        mcp_configs=[
            MCPConfig(
                server_name="高德地图",
                url="https://mcp.api-inference.modelscope.net/77df8a09751e4c/sse",
                type="sse",
                user_config={}
            )
        ],
        mcp_as_agent=False

    )
    await mars.init_mars_agent()
    async for chunk in mars.astream("你好啊, 今天北京的天气如何呢？"):
        print(chunk)


if __name__ == "__main__":
    asyncio.run(main())