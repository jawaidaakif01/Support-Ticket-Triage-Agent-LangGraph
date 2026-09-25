import os
from typing import TypedDict, Literal
from langgraph.graph import StateGraph, END
from langchain_google_genai import ChatGoogleGenerativeAI
from langgraph.checkpoint.memory import MemorySaver
from dotenv import load_dotenv
load_dotenv()

llm = ChatGoogleGenerativeAI(model="gemini-3.5-flash-lite", temperature=0)
checkpointer = MemorySaver()


class TicketState(TypedDict):
    ticket_text: str
    category: str        # "billing", "technical", "general" 
    priority: str        # "high", "low"
    draft_response: str
    revision_count: int
    approved: bool


def classify_ticket(state: TicketState) -> dict:
    prompt = f"""Classify this support ticket into exactly one category:
    billing, technical, or general. Also rate priority as high or low.
    Ticket: {state['ticket_text']}
    Respond in format: category=<x>, priority=<y>
    """

    response = llm.invoke(prompt).text

    if "billing" in response.lower():
        category = "billing"
    elif "technical" in response.lower():
        category = "technical"
    else:
        category = "general"

    if "high" in response.lower():
        priority = "high"
    else:
        priority = "low"

    return {"category": category, "priority": priority}


def draft_response(state: TicketState) -> dict:
    prompt = f"""Write a short professional support response to this {state['category']} ticket: {state['ticket_text']}"""

    draft = llm.invoke(prompt).text
    count = state.get("revision_count", 0) + 1
    return {"draft_response": draft, "revision_count": count}

def check_quality(state: TicketState) -> dict:
    prompt = f"""Is this response professional, on-topic, and helpful? Answer only YES or NO.
    Response: {state['draft_response']}
    """

    verdict = llm.invoke(prompt).text.strip().upper()
    return {"approved": "YES" in verdict}

def escalate(state: TicketState) -> dict:
    print(f"Escalated to human agent: {state['ticket_text']}")
    return {}

def route_by_priority(state: TicketState) -> Literal["escalate", "draft_response"]:
    if state['priority'] == 'high':
        return "escalate"
    return "draft_response"

def route_by_quality(state: TicketState) -> Literal["draft_response", "end"]:
    if not state["approved"] and state["revision_count"] < 3:
        return "draft_response"  # loop back and try again
    return "end"


graph = StateGraph(TicketState)

graph.add_node("classify", classify_ticket)
graph.add_node("escalate", escalate)
graph.add_node("draft_response", draft_response)
graph.add_node("check_quality", check_quality)

graph.set_entry_point("classify")

graph.add_conditional_edges("classify", route_by_priority, {
    "escalate": "escalate",
    "draft_response": "draft_response"
})

graph.add_edge("draft_response", "check_quality")

graph.add_conditional_edges("check_quality", route_by_quality, {
    "draft_response": "draft_response",
    "end": END
})

graph.add_edge("escalate", END)

app = graph.compile(checkpointer=checkpointer, interrupt_before=["escalate"])
config = {"configurable": {'thread_id': "ticket-001"}}


result = app.invoke({
    "ticket_text": "I was charged twice for my subscription this month, please fix urgently!",
    "category": "",
    "priority": "",
    "draft_response": "",
    "revision_count": 0,
    "approved": False
}, config)

print("Paused. Current state:")
print(app.get_state(config).values)

human_decision = input("Approve escalation? (y/n): ")

if human_decision.lower() == "y":
    result = app.invoke(None, config)
    print(result)
else:
    print("Escalation rejected by human - not proceeding.")