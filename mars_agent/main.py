import asyncio

from mars_agent.agent import MarsAgent
from mars_agent.schema import MarsModelConfig, MCPSSEConfig, MCPStdioConfig


def test_get_weather(location: str):
    """查看提供地理位置的天气情况
    location: 提供的城市名称
    """
    return f"{location}的天气是真好啊，已经达到了40°"


async def main():
    print("-" * 50)

    mars = MarsAgent(
        model_config=MarsModelConfig(model="qwen3-coder-plus", api_key="sk-***************", base_url="https://dashscope.aliyuncs.com/compatible-mode/v1"),
        functions=[test_get_weather],
        mcp_configs=[
            MCPSSEConfig(
                server_name="高德地图",
                url="https://mcp.api-inference.modelscope.net/77df8a09751e4c/sse",
            ),
            MCPSSEConfig(
                server_name="飞书",
                url="http://47.95.23.87:8000/sse",
                personal_config={"app_id": "cli_a8e97890b87d900b", "app_secret": "Li5w1A3yxy2GCfaaEYGlBhEDI5xr2cBT"}
            )
        ],
        mcp_as_agent=True
    )
    print("*" * 50)

    print("=" * 50)

    final_answer = ""
    async for chunk in mars.astream("你好啊, 能否帮我查一下郑州市的天气情况呢？"):
        if chunk.get("type") == "response_chunk":
            final_answer += chunk.get("data").get("chunk")
            print(chunk.get("data").get("chunk"), end="")
            continue
        print(chunk)


if __name__ == "__main__":
    asyncio.run(main())
