from langchain_core.language_models import FakeMessagesListChatModel
import pytest
from langchain_core.messages import HumanMessage, AIMessage
from langgraph_swarm import create_swarm
from dingent.engine.agents.state import MainState
from dingent.engine.agents.simple_agent import build_simple_react_agent
from dingent.engine.agents.tools import create_handoff_tool
from langchain_core.tools import tool


# 1. 创建支持 bind_tools 的 Fake 模型类
class FakeMessagesListChatModelWithTools(FakeMessagesListChatModel):
    def bind_tools(self, tools, **kwargs):
        """
        在 Fake 模型中模拟 bind_tools 行为。
        由于返回的消息是硬编码的，直接返回自身即可。
        """
        return self


@pytest.mark.asyncio
async def test_handoff_behavior():
    # 2. Setup tools
    handoff_b = create_handoff_tool("agent_b", "Agent B can help with math", lambda *args, **kwargs: print(args))

    # 3. Setup Agent A
    # Agent A will first output an AIMessage with a tool call to handoff
    responses_a = [AIMessage(content="", tool_calls=[{"name": "transfer_to_agent_b", "args": {}, "id": "call_123"}])]
    # 使用自定义的 Fake 模型
    llm_a = FakeMessagesListChatModelWithTools(responses=responses_a)  # pyright: ignore[reportArgumentType]
    agent_a = build_simple_react_agent("agent_a", llm_a, tools=[handoff_b], system_prompt="You are Agent A")

    # 4. Setup Agent B
    # Agent B will receive the state and output a response
    responses_b = [AIMessage(content="I am Agent B, I have received the handoff.")]
    # 使用自定义的 Fake 模型
    llm_b = FakeMessagesListChatModelWithTools(responses=responses_b)  # pyright: ignore[reportArgumentType]

    @tool
    def dummy_tool():
        """Dummy"""
        pass

    agent_b = build_simple_react_agent("agent_b", llm_b, tools=[dummy_tool], system_prompt="You are Agent B")

    # 5. Create swarm
    swarm_workflow = create_swarm(
        agents=[agent_a, agent_b],
        state_schema=MainState,
        default_active_agent="agent_a",
        context_schema=dict,
    )

    compiled_swarm = swarm_workflow.compile()

    # 6. Run swarm
    state = {"messages": [HumanMessage(content="Transfer to B")]}

    result = await compiled_swarm.ainvoke(state)

    print("Messages after run:")
    for msg in result["messages"]:
        print(type(msg), msg.dict())
