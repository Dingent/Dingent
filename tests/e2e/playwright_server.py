from __future__ import annotations

import os

import uvicorn
from langchain_core.language_models import FakeMessagesListChatModel
from langchain_core.messages import AIMessage, BaseMessage
from langgraph.checkpoint.memory import InMemorySaver
from pydantic import Field
from sqlmodel import Session, SQLModel, select

from dingent.core.db.models import Assistant, Role, Workflow, WorkflowEdge, WorkflowNode, Workspace
from dingent.core.db.session import create_initial_roles, engine
from dingent.core.llms import service as llm_service
from dingent.core.workflows.graph_factory import GraphFactory
from dingent.server.api.routers.frontend import threads as chat_threads
from dingent.server.app import create_app
from dingent.server.services.copilotkit_service import CopilotKitSdk

WORKSPACE_SLUG = "playwright-e2e"
WORKFLOW_NAME = "playwright-e2e-flow"


class FakeMessagesListChatModelWithTools(FakeMessagesListChatModel):
    received_messages: list[list[BaseMessage]] = Field(default_factory=list)
    bound_tool_names: list[list[str]] = Field(default_factory=list)

    def bind_tools(self, tools, **kwargs):
        self.bound_tool_names.append([getattr(tool, "name", "") for tool in tools])
        return self

    def _generate(self, messages: list[BaseMessage], stop=None, run_manager=None, **kwargs):
        self.received_messages.append(messages)
        return super()._generate(messages, stop=stop, run_manager=run_manager, **kwargs)


def _create_workspace(session: Session) -> Workspace:
    workspace = session.exec(select(Workspace).where(Workspace.slug == WORKSPACE_SLUG)).first()
    if workspace:
        return workspace

    workspace = Workspace(name="Playwright E2E", slug=WORKSPACE_SLUG, description="Browser e2e workspace", allow_guest_access=True)
    session.add(workspace)
    session.commit()
    session.refresh(workspace)
    return workspace


def _create_workflow(session: Session, workspace: Workspace) -> None:
    existing = session.exec(select(Workflow).where(Workflow.name == WORKFLOW_NAME, Workflow.workspace_id == workspace.id)).first()
    if existing:
        return

    data_getter = Assistant(
        name="DataGetter",
        description="Data getting assistant",
        instructions="You get data and hand off to the analyst.",
        enabled=True,
        workspace_id=workspace.id,
    )
    analyst = Assistant(
        name="Analyst",
        description="Analysis assistant",
        instructions="You analyze data and hand off to the reviewer.",
        enabled=True,
        workspace_id=workspace.id,
    )
    reviewer = Assistant(
        name="Reviewer",
        description="Review assistant",
        instructions="You review the analysis and provide the final answer.",
        enabled=True,
        workspace_id=workspace.id,
    )
    session.add(data_getter)
    session.add(analyst)
    session.add(reviewer)
    session.commit()
    session.refresh(data_getter)
    session.refresh(analyst)
    session.refresh(reviewer)

    workflow = Workflow(name=WORKFLOW_NAME, description="Playwright browser e2e workflow", workspace_id=workspace.id)
    session.add(workflow)
    session.commit()
    session.refresh(workflow)

    node_a = WorkflowNode(workflow_id=workflow.id, assistant_id=data_getter.id, is_start_node=True, type="assistant", position={})
    node_b = WorkflowNode(workflow_id=workflow.id, assistant_id=analyst.id, is_start_node=False, type="assistant", position={})
    node_c = WorkflowNode(workflow_id=workflow.id, assistant_id=reviewer.id, is_start_node=False, type="assistant", position={})
    session.add(node_a)
    session.add(node_b)
    session.add(node_c)
    session.commit()
    session.refresh(node_a)
    session.refresh(node_b)
    session.refresh(node_c)

    session.add(WorkflowEdge(workflow_id=workflow.id, source_node_id=node_a.id, target_node_id=node_b.id))
    session.add(WorkflowEdge(workflow_id=workflow.id, source_node_id=node_b.id, target_node_id=node_c.id))
    session.commit()


def _seed_database() -> None:
    SQLModel.metadata.create_all(engine)
    create_initial_roles()

    with Session(engine, expire_on_commit=False) as session:
        for role_name in ["admin", "user", "guest"]:
            if not session.exec(select(Role).where(Role.name == role_name)).first():
                session.add(Role(name=role_name, description=f"Default {role_name} role"))
        session.commit()

        workspace = _create_workspace(session)
        _create_workflow(session, workspace)


def _build_fake_llm() -> FakeMessagesListChatModelWithTools:
    return FakeMessagesListChatModelWithTools(
        responses=[
            AIMessage(content="", tool_calls=[{"name": "transfer_to_Analyst", "args": {}, "id": "call_handoff"}]),
            AIMessage(content="", tool_calls=[{"name": "transfer_to_Reviewer", "args": {}, "id": "call_review"}]),
            AIMessage(content="Reviewer final answer: browser e2e completed with mocked LLM output."),
        ]
    )


_seed_database()
app = create_app()
fake_llm = _build_fake_llm()
llm_service.get_llm_for_context = lambda **_kwargs: fake_llm


@app.on_event("startup")
async def _install_e2e_copilot_sdk() -> None:
    graph_factory = GraphFactory(app.state.assistant_factory)
    sdk = CopilotKitSdk(graph_factory=graph_factory, checkpointer=InMemorySaver())
    app.dependency_overrides[chat_threads.get_copilot_sdk] = lambda: sdk


@app.get("/api/v1/__e2e__/state")
def get_e2e_state():
    return {
        "workspaceSlug": WORKSPACE_SLUG,
        "workflowName": WORKFLOW_NAME,
        "receivedMessages": [[{"type": message.type, "content": message.content} for message in messages] for messages in fake_llm.received_messages],
        "boundToolNames": fake_llm.bound_tool_names,
    }


if __name__ == "__main__":
    port = int(os.getenv("E2E_BACKEND_PORT", "8765"))
    uvicorn.run("tests.e2e.playwright_server:app", host="127.0.0.1", port=port, log_level="warning")
