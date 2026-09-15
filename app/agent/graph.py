from langgraph.graph import StateGraph, END
from langgraph.prebuilt import ToolNode
from langchain_core.messages import HumanMessage, SystemMessage
from app.agent.state import AgentState
from app.tools.retrieve import retrieve_relevant_jobs
from app.tools.analyze import generate_match_analysis
from app.core.llm import get_llm


tools = [retrieve_relevant_jobs, generate_match_analysis]
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
