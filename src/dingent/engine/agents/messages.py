from typing import Any, cast

from langchain_core.messages import BaseMessage


class ActivityMessage(BaseMessage):
    type: str = "activity"

    def __init__(self, content: list[dict[str, Any]], **kwargs):
        super().__init__(content=cast(Any, content), **kwargs)
