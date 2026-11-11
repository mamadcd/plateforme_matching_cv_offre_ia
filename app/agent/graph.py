from langgraph.graph import StateGraph, END
from langgraph.prebuilt import ToolNode
from langchain_core.messages import HumanMessage, SystemMessage
from app.agent.state import AgentState
from app.tools.retrieve import retrieve_jobs_for_cv
from app.tools.analyze import analyze_cv_job_match
from app.core.llm import get_llm


tools = [retrieve_jobs_for_cv, analyze_cv_job_match]
llm = get_llm().bind_tools(tools)
tool_node = ToolNode(tools)


def agent_node(state: AgentState):
    messages = state["messages"]
    response = llm.invoke(messages)
    return {"messages": [response]}


def should_continue(state: AgentState):
    last_message = state["messages"][-1]
    if last_message.tool_calls:
        return "tools"
    return END


def build_graph():
    workflow = StateGraph(AgentState)

    workflow.add_node("agent", agent_node)
    workflow.add_node("tools", tool_node)

    workflow.set_entry_point("agent")
    workflow.add_conditional_edges("agent", should_continue, {
        "tools": "tools",
        END: END,
    })
    workflow.add_edge("tools", "agent")

    return workflow.compile()


graph = build_graph()
