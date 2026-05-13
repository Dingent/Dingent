import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Annotated, Any, cast

from ag_ui.core.types import RunAgentInput
from ag_ui.encoder import EventEncoder
from fastapi import APIRouter, Depends, Header, HTTPException, Request
from fastapi.responses import StreamingResponse
from sqlmodel import col, delete, select

from dingent.core.db.crud.workflow import get_workflow_by_name
from dingent.core.db.models import Conversation, Workflow

# from dingent.core.managers.llm_manager import get_llm_service
from dingent.core.workflows.presets import get_fallback_workflow_spec
from dingent.core.workflows.schemas import ExecutableWorkflow
from dingent.core.workspaces.schemas import ThreadRead
from dingent.server.api.dependencies import (
    CurrentUserOptional,
    CurrentWorkspaceAllowGuest,
    DbSession,
    get_visitor_id,
)
from dingent.server.copilot.agents import DingLangGraphAGUIAgent
from dingent.server.services.copilotkit_service import CopilotKitSdk

router = APIRouter(prefix="/chat", tags=["chat"])


def get_copilot_sdk(request: Request) -> CopilotKitSdk:
    return request.app.state.copilot_sdk


CopilotSDK = Annotated[CopilotKitSdk, Depends(get_copilot_sdk)]


@dataclass
class AgentContext:
    """
    这是一个上下文容器，包含执行 Agent 所需的所有准备工作。
    """

    session: DbSession
    agent: DingLangGraphAGUIAgent
    conversation: Conversation
    encoder: EventEncoder
    input_data: RunAgentInput


def update_conversation_title(conversation: Conversation, input_data: RunAgentInput, max_length: int = 50) -> None:
    """
    Update conversation title based on first message if title is "New Chat".

    Args:
        conversation: The conversation object to update
        input_data: The input data containing messages
        max_length: Maximum length for the title (default: 50)
    """
    if conversation.title == "New Chat" and input_data.messages:
        conversation.title = cast(str, input_data.messages[0].content)[:max_length]


async def get_workflow_spec(workflow: Workflow | None) -> ExecutableWorkflow:
    if not workflow or not workflow.to_spec().start_node:
        return get_fallback_workflow_spec()
    return workflow.to_spec()


async def get_agent_context(
    agent_id: str,
    input_data: RunAgentInput,
    request: Request,
    sdk: CopilotSDK,
    session: DbSession,
    user: CurrentUserOptional,
    workspace: CurrentWorkspaceAllowGuest,
    visitor_id: str | None = Header(None, alias="X-Visitor-ID"),
) -> AgentContext:
    # --- A. 验证 thread_id ---
    try:
        thread_uuid = uuid.UUID(input_data.thread_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid thread_id format")

    conversation = session.exec(select(Conversation).where(Conversation.id == thread_uuid)).first()

    if conversation:
        if conversation.workspace_id != workspace.id:
            raise HTTPException(status_code=403, detail="This conversation belongs to a different workspace.")

        if user:
            if conversation.user_id != user.id:
                raise HTTPException(status_code=403, detail="You do not have permission to access this conversation.")
        else:
            if not visitor_id:
                raise HTTPException(status_code=400, detail="Guest users must provide X-Visitor-ID header")

            if conversation.user_id is not None:
                raise HTTPException(status_code=403, detail="This conversation belongs to a registered user.")

            if conversation.visitor_id != visitor_id:
                raise HTTPException(status_code=403, detail="You do not have permission to access this conversation.")

    else:
        # === 创建逻辑合并 ===
        new_conversation = Conversation(
            id=thread_uuid,
            workspace_id=workspace.id,
            title="New Chat",
        )

        if user:
            new_conversation.user_id = user.id
        elif visitor_id:
            new_conversation.visitor_id = visitor_id
        else:
            # 既没登录也没传 visitor_id
            raise HTTPException(status_code=400, detail="Authentication or X-Visitor-ID required")

        session.add(new_conversation)
        session.commit()
        session.refresh(new_conversation)
        conversation = new_conversation

    # --- C. 解析 Agent ---
    workflow = get_workflow_by_name(session, agent_id, workspace.id)
    if not workflow and agent_id != "default":
        raise HTTPException(status_code=404, detail=f"Workflow '{agent_id}' not found")

    # Use context-aware model resolution with cascading strategy
    from dingent.core.llms.service import get_llm_for_context

    workflow_id = workflow.id if workflow else None
    llm = get_llm_for_context(
        session=session,
        workflow_id=workflow_id,
        workspace_id=workspace.id,
    )

    spec = await get_workflow_spec(workflow)
    agent = await sdk.resolve_agent(spec, llm)

    # --- D. 准备 Encoder ---
    accept_header = request.headers.get("accept")
    encoder = EventEncoder(accept=cast(str, accept_header))

    return AgentContext(
        session=session,
        agent=agent,
        conversation=conversation,
        encoder=encoder,
        input_data=input_data,
    )


@router.get("/info")
async def get_agents(
    sdk: CopilotSDK,
    user: CurrentUserOptional,
    workspace: CurrentWorkspaceAllowGuest,
    session: DbSession,
):
    return sdk.list_agents_for_user(user, session, workspace.id)


@router.post("/agent/{agent_id}/run")
async def run(
    ctx: AgentContext = Depends(get_agent_context),
):
    async def event_generator():
        async for event in ctx.agent.run(
            ctx.input_data,
        ):
            encoded_event = ctx.encoder.encode(cast(Any, event))
            yield encoded_event

    # Update conversation title if needed
    update_conversation_title(ctx.conversation, ctx.input_data)

    ctx.conversation.updated_at = datetime.now(UTC)
    ctx.session.add(ctx.conversation)
    ctx.session.commit()
    headers = {
        "X-Accel-Buffering": "no",
        "Cache-Control": "no-cache, no-transform",
        "Connection": "keep-alive",
    }

    return StreamingResponse(
        event_generator(),
        media_type=ctx.encoder.get_content_type(),
        headers=headers,
    )


@router.post("/agent/{agent_id}/connect")
async def connect(
    ctx: AgentContext = Depends(get_agent_context),
):
    async def event_generator():
        async for event in ctx.agent.get_thread_messages(ctx.input_data.thread_id, ctx.input_data.run_id):
            encoded_event = ctx.encoder.encode(cast(Any, event))
            yield encoded_event

    return StreamingResponse(event_generator(), media_type=ctx.encoder.get_content_type())


@router.get("/threads", response_model=list[ThreadRead])
async def list_threads(
    user: CurrentUserOptional,
    workspace: CurrentWorkspaceAllowGuest,
    session: DbSession,
    visitor_id: str | None = Depends(get_visitor_id),
) -> list[ThreadRead]:
    query = select(Conversation).where(Conversation.workspace_id == workspace.id)

    if user:
        # 查询属于该用户的
        query = query.where(Conversation.user_id == user.id)
    elif visitor_id:
        # 查询属于该游客的
        query = query.where(Conversation.visitor_id == visitor_id)
        # 且确保不包含已绑定用户的会话
        query = query.where(col(Conversation.user_id).is_(None))
    else:
        return []

    threads = session.exec(query).all()
    return [ThreadRead.model_validate(thread) for thread in threads]


@router.delete("/threads", status_code=200)
async def delete_all_threads(
    user: CurrentUserOptional,
    session: DbSession,
    workspace: CurrentWorkspaceAllowGuest,
    visitor_id: str | None = Depends(get_visitor_id),
):
    """
    删除当前用户/游客在当前工作空间下的所有对话
    """
    # 直接构建 DELETE 语句，效率更高，不需要先 fetch 数据
    if user:
        statement = delete(Conversation).where(
            col(Conversation.workspace_id) == workspace.id,
            col(Conversation.user_id) == user.id,
        )
    elif visitor_id:
        statement = delete(Conversation).where(
            col(Conversation.workspace_id) == workspace.id,
            col(Conversation.visitor_id) == visitor_id,
        )
    else:
        raise Exception("Cannot delete threads without user or visitor_id")

    result = session.exec(statement)
    session.commit()

    return {"detail": f"Deleted all threads in workspace. Count: {result.rowcount}"}


@router.delete("/threads/{thread_id}")
async def delete_thread(
    thread_id: uuid.UUID,
    user: CurrentUserOptional,
    session: DbSession,
    workspace: CurrentWorkspaceAllowGuest,
    visitor_id: str | None = Depends(get_visitor_id),
):
    if user:
        statement = select(Conversation).where(
            Conversation.id == thread_id,
            Conversation.workspace_id == workspace.id,
            Conversation.user_id == user.id,
        )
    elif visitor_id:
        statement = select(Conversation).where(
            Conversation.id == thread_id,
            Conversation.workspace_id == workspace.id,
            Conversation.visitor_id == visitor_id,
        )
    else:
        raise Exception("Cannot delete thread without user or visitor_id")
    thread = session.exec(statement).first()

    if not thread:
        raise HTTPException(status_code=404, detail="Thread not found")

    session.delete(thread)
    session.commit()

    return {"detail": "Thread deleted successfully"}
