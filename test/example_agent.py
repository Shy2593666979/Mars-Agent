import asyncio

from mars_agent.agent import MarsAgent
from mars_agent.schema import MarsModelConfig, MCPSSEConfig, MCPStdioConfig


def test_get_weather(location: str):
    """Check weather conditions for the provided location
    location: Provided city name
    """
    return f"The weather in {location} is really nice, it has reached 40°"


async def main():
    print("-" * 50)

    mars = MarsAgent(
        model_config=MarsModelConfig(model="qwen3-coder-plus", api_key="sk-fc40dd0604f041******", base_url="https://dashscope.aliyuncs.com/compatible-mode/v1"),
        functions=[test_get_weather],
        mcp_configs=[
            MCPSSEConfig(
                server_name="Gaode map",
                url="https://mcp.api-inference.modelscope.net/77df8a09751e4c/sse",
            ),
            MCPSSEConfig(
                server_name="Lark",
                url="http://47.95.***.***:8000/sse",
                personal_config={"app_id": "cli_a8e97890b****", "app_secret": "Li5w1A3yxy2GCfaa****"}
            )
        ],
        mcp_as_agent=True
    )
    print("*" * 50)

    print("=" * 50)

    final_answer = ""
    async for chunk in mars.astream("创建一个日程，时间从现在开始，两个小时之后结束，会议的主题就是月度总结大会，邀请用户19939306458入会"):
        if chunk.get("type") == "response_chunk":
            final_answer += chunk.get("data").get("chunk")
            print(chunk.get("data").get("chunk"), end="")
            continue
        print(chunk)


if __name__ == "__main__":
    asyncio.run(main())
