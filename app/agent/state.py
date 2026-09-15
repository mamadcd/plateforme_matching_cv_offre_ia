from typing import TypedDict, Annotated, List
from langgraph.graph.message import add_messages


class AgentState(TypedDict):
    messages: Annotated[List, add_messages]
    cv_text: str
    final_result: str
