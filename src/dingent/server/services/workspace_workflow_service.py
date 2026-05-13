from __future__ import annotations

from threading import RLock
from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy.orm import selectinload
from sqlmodel import Session, select

from dingent.core.db.crud import workflow as crud_workflow
from dingent.core.db.models import Workflow, WorkflowNode
from dingent.core.workflows.schemas import WorkflowCreate, WorkflowEdgeRead, WorkflowNodeCreate, WorkflowNodeRead, WorkflowRead, WorkflowReadBasic, WorkflowReplace, WorkflowUpdate
from dingent.server.services.workspace_assistant_service import WorkspaceAssistantService


class WorkflowNotFoundError(ValueError):
    pass


class WorkflowAlreadyRunningError(RuntimeError):
    pass


class AssistantServiceUnavailableError(RuntimeError):
    pass


class WorkspaceWorkflowService:
    def __init__(
        self,
        *,
        workspace_id: UUID,
        user_id: UUID | None,
        visitor_id: UUID | None,
        session: Session,
        assistant_service: WorkspaceAssistantService | None,
        log_manager,
    ) -> None:
        self.workspace_id = workspace_id
        self.user_id = user_id
        self.visitor_id = visitor_id
        self.session = session
        self.assistant_service = assistant_service
        self._log = log_manager

        self._lock = RLock()

    def _ensure_write_access(self):
        """确保当前操作者有写入权限。游客通常只有读取权限。"""
        if self.user_id is None:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Guests have read-only access. Please sign in to modify workflows.")

    def list_workflows(self, *, eager: bool = False) -> list[WorkflowReadBasic | WorkflowRead]:
        if eager:
            wfs = self.session.exec(
                select(Workflow)
                .where(Workflow.workspace_id == self.workspace_id)
                .options(
                    selectinload(Workflow.nodes).selectinload(WorkflowNode.assistant),
                    selectinload(Workflow.edges),
                )
            ).all()
            return [WorkflowRead.model_validate(wf) for wf in wfs]
        else:
            wfs = self.session.exec(select(Workflow).where(Workflow.workspace_id == self.workspace_id)).all()
            return [WorkflowReadBasic.model_validate(wf) for wf in wfs]

    def get_workflow(self, workflow_id: UUID, *, eager: bool = False) -> WorkflowRead | WorkflowReadBasic | None:
        wf = self._get_workflow(workflow_id, eager=eager)
        if wf is None:
            return None
        if eager:
            return WorkflowRead.model_validate(wf)
        else:
            return WorkflowReadBasic.model_validate(wf)

    def create_workflow(self, wf_create: WorkflowCreate) -> WorkflowReadBasic:
        self._ensure_write_access()
        if self.user_id is None:
            raise RuntimeError("user_id unexpectedly None after write access check")
        if crud_workflow.get_workflow_by_name(self.session, name=wf_create.name, workspace_id=self.workspace_id):
            raise ValueError(f"Workflow name '{wf_create.name}' already exists.")
        wf = crud_workflow.create_workflow(self.session, wf_create=wf_create, workspace_id=self.workspace_id, user_id=self.user_id)
        return WorkflowReadBasic.model_validate(wf)

    def replace_workflow(self, workflow_id: UUID, wf_create: WorkflowReplace):
        self._ensure_write_access()
        if self.user_id is None:
            raise RuntimeError("user_id unexpectedly None after write access check")
        wf = self._get_workflow(workflow_id)
        if wf is None:
            raise WorkflowNotFoundError(f"Workflow '{workflow_id}' not found or access denied.")

        if wf_create.name != wf.name:
            if crud_workflow.get_workflow_by_name(self.session, name=wf_create.name, workspace_id=self.workspace_id):
                raise ValueError(f"Another workflow already uses the name '{wf_create.name}'.")

        crud_workflow.replace_workflow(self.session, db_workflow=wf, wf_create=wf_create)

    def update_workflow(self, workflow_id: UUID, wf_update: WorkflowUpdate) -> WorkflowReadBasic:
        self._ensure_write_access()
        if self.user_id is None:
            raise RuntimeError("user_id unexpectedly None after write access check")
        wf = self._get_workflow(workflow_id)
        if wf is None:
            raise WorkflowNotFoundError(f"Workflow '{workflow_id}' not found or access denied.")

        if wf_update.name and wf_update.name != wf.name:
            if crud_workflow.get_workflow_by_name(self.session, name=wf_update.name, workspace_id=self.workspace_id):
                raise ValueError(f"Another workflow already uses the name '{wf_update.name}'.")

        updated = crud_workflow.update_workflow(self.session, db_workflow=wf, wf_update=wf_update)
        return WorkflowReadBasic.model_validate(updated)

    def delete_workflow(self, workflow_id: UUID) -> bool:
        self._ensure_write_access()
        if self.user_id is None:
            raise RuntimeError("user_id unexpectedly None after write access check")
        wf = self._get_workflow(workflow_id)
        if wf is None:
            return False
        crud_workflow.delete_workflow(self.session, db_workflow=wf)
        return True

    # ---------------------------------------------------------------------
    # Nodes CRUD
    # ---------------------------------------------------------------------
    def list_nodes(self, workflow_id: UUID):
        wf = self._get_workflow(workflow_id)
        if wf is None:
            raise WorkflowNotFoundError(f"Workflow '{workflow_id}' not found or access denied.")
        crud_workflow.list_workflow_nodes(self.session, workflow_id=workflow_id)
        node_reads = [WorkflowNodeRead.model_validate(node) for node in wf.nodes]
        return node_reads

    def create_node(self, workflow_id: UUID, payload: WorkflowNodeCreate):  # payload: WorkflowNodeCreate
        self._ensure_write_access()
        if self.user_id is None:
            raise RuntimeError("user_id unexpectedly None after write access check")
        wf = self._get_workflow(workflow_id)
        if wf is None:
            raise WorkflowNotFoundError(f"Workflow '{workflow_id}' not found or access denied.")
        node = crud_workflow.create_workflow_node(self.session, workflow_id=workflow_id, node_in=payload)
        return WorkflowNodeRead.model_validate(node)

    def update_node(self, workflow_id: UUID, node_id: UUID, payload):  # payload: WorkflowNodeUpdate
        self._ensure_write_access()
        if self.user_id is None:
            raise RuntimeError("user_id unexpectedly None after write access check")
        node = crud_workflow.update_workflow_node(self.session, workflow_id=workflow_id, node_id=node_id, node_update=payload)
        return WorkflowNodeRead.model_validate(node)

    def delete_node(self, workflow_id: UUID, node_id: UUID) -> bool:
        self._ensure_write_access()
        if self.user_id is None:
            raise RuntimeError("user_id unexpectedly None after write access check")
        wf = self._get_workflow(workflow_id)
        if wf is None:
            raise WorkflowNotFoundError(f"Workflow '{workflow_id}' not found or access denied.")
        db_node = crud_workflow.get_workflow_node(self.session, workflow_id=workflow_id, node_id=node_id)
        if not db_node or db_node.workflow_id != workflow_id:
            return False
        crud_workflow.delete_workflow_node(self.session, workflow_id=workflow_id, node_id=node_id)
        return True

    # ---------------------------------------------------------------------
    # Edges CRUD
    # ---------------------------------------------------------------------
    def list_edges(self, workflow_id: UUID):
        wf = self._get_workflow(workflow_id)
        if wf is None:
            raise WorkflowNotFoundError(f"Workflow '{workflow_id}' not found or access denied.")
        edges = crud_workflow.list_workflow_edges(self.session, workflow_id=workflow_id)
        edge_reads = [WorkflowEdgeRead.model_validate(edge) for edge in edges]
        return edge_reads

    def create_edge(self, workflow_id: UUID, payload):  # payload: WorkflowEdgeCreate
        self._ensure_write_access()
        if self.user_id is None:
            raise RuntimeError("user_id unexpectedly None after write access check")
        wf = self._get_workflow(workflow_id)
        if wf is None:
            raise WorkflowNotFoundError(f"Workflow '{workflow_id}' not found or access denied.")
        edge = crud_workflow.create_workflow_edge(self.session, workflow_id=workflow_id, edge_in=payload)
        return WorkflowEdgeRead.model_validate(edge)

    def update_edge(self, workflow_id: UUID, edge_id: UUID, payload):  # payload: WorkflowEdgeUpdate
        self._ensure_write_access()
        if self.user_id is None:
            raise RuntimeError("user_id unexpectedly None after write access check")
        wf = self._get_workflow(workflow_id)
        if wf is None:
            raise WorkflowNotFoundError(f"Workflow '{workflow_id}' not found or access denied.")
        db_edge = crud_workflow.get_workflow_edge(self.session, workflow_id=workflow_id, edge_id=edge_id)
        if not db_edge or db_edge.workflow_id != workflow_id:
            raise HTTPException(status_code=404, detail="Edge not found")
        edge = crud_workflow.update_workflow_edge(self.session, workflow_id=workflow_id, edge_id=edge_id, edge_update=payload)
        return WorkflowEdgeRead.model_validate(edge)

    def delete_edge(self, workflow_id: UUID, edge_id: UUID) -> bool:
        self._ensure_write_access()
        if self.user_id is None:
            raise RuntimeError("user_id unexpectedly None after write access check")
        wf = self._get_workflow(workflow_id)
        if wf is None:
            raise WorkflowNotFoundError(f"Workflow '{workflow_id}' not found or access denied.")
        db_edge = crud_workflow.get_workflow_edge(self.session, workflow_id=workflow_id, edge_id=edge_id)
        if not db_edge or db_edge.workflow_id != workflow_id:
            return False
        crud_workflow.delete_workflow_edge(self.session, workflow_id=workflow_id, edge_id=edge_id)
        return True

    # ---------------------------------------------------------------------
    # Internals
    # ---------------------------------------------------------------------
    def _get_workflow(self, workflow_id: UUID, *, eager: bool = False) -> Workflow | None:
        stmt = select(Workflow).where(Workflow.id == workflow_id, Workflow.workspace_id == self.workspace_id)
        if eager:
            stmt = stmt.options(
                selectinload(Workflow.nodes).selectinload(WorkflowNode.assistant),
                selectinload(Workflow.edges),
            )
        return self.session.exec(stmt).first()

    @staticmethod
    def _build_adjacency(
        wf: Workflow,
        *,
        include_self_loops: bool,
        honor_bidirectional: bool,
    ) -> dict[str, list[str]]:
        """assistant_name -> sorted(list(destination_assistant_names))"""
        node_id_to_name: dict[UUID, str] = {node.id: node.assistant.name for node in wf.nodes if getattr(node, "assistant", None)}
        adj: dict[str, set[str]] = {name: set() for name in node_id_to_name.values()}

        for edge in wf.edges:
            src = node_id_to_name.get(edge.source_node_id)
            tgt = node_id_to_name.get(edge.target_node_id)
            if not src or not tgt:
                continue

            if include_self_loops or src != tgt:
                adj.setdefault(src, set()).add(tgt)

            if honor_bidirectional and bool(getattr(edge, "bidirectional", False)):
                if include_self_loops or src != tgt:
                    adj.setdefault(tgt, set()).add(src)

        return {k: sorted(v) for k, v in adj.items()}
