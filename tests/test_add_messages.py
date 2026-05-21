from langchain_core.messages import ToolMessage
from langgraph.graph.message import add_messages

state_messages = []
msg = ToolMessage(content="Hello", tool_call_id="123")
print("msg id before:", msg.id)

# first update
state_messages = add_messages(state_messages, [msg])
print("state after 1:", len(state_messages), state_messages[0].id)
print("msg id after 1:", msg.id)

# second update passing the SAME msg
state_messages = add_messages(state_messages, [msg])
print("state after 2:", len(state_messages))
if len(state_messages) > 1:
    print("msg 2 id:", state_messages[1].id)
