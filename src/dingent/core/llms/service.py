from uuid import UUID

from langchain_litellm import ChatLiteLLM
from sqlmodel import Session

from dingent.core.llms.resolver import ModelResolver


def get_llm_for_context(
    session: Session,
    assistant_id: UUID | None = None,
    workflow_id: UUID | None = None,
    workspace_id: UUID | None = None,
) -> ChatLiteLLM:
    """
    Get a ChatLiteLLM instance using cascading model resolution.

    Priority order:
    1. Assistant-level configuration
    2. Workflow-level configuration
    3. Workspace-level configuration
    4. Environment fallback

    Args:
        session: Database session
        assistant_id: Optional assistant ID
        workflow_id: Optional workflow ID
        workspace_id: Optional workspace ID

    Returns:
        Configured ChatLiteLLM instance
    """
    resolver = ModelResolver(session)
    return resolver.resolve_for_assistant(assistant_id, workflow_id, workspace_id)
