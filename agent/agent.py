import os
import re
import logging
import requests
from typing import TypedDict
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse
from prometheus_client import Counter, Histogram, start_http_server
from langchain_ollama import ChatOllama, OllamaEmbeddings
from langchain_chroma import Chroma
from langchain_core.tools import Tool
from langchain_classic.agents import initialize_agent, AgentType
from langgraph.graph import StateGraph, END

# Config
OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://ollama:11434")
TASK_SERVICE_URL = os.getenv("TASK_SERVICE_URL", "http://task-service:8001")
LLM_MODEL = os.getenv("LLM_MODEL", "llama3.2:3b")
EMBED_MODEL = os.getenv("EMBED_MODEL", "llama3.2:3b")
MAX_RETRIES = int(os.getenv("AGENT_MAX_RETRIES", "2"))

# Logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("task_agent")

# Metrics
REQUESTS = Counter("agent_requests_total", "Total user requests")
INTENTS = Counter("agent_intent_total", "Requests by routed intent", ["intent"])
ERRORS = Counter("agent_errors_total", "Failed agent invocations")
LATENCY = Histogram("agent_latency_seconds", "Latency")

# RAG
embedding_model = OllamaEmbeddings(model=EMBED_MODEL, base_url=OLLAMA_BASE_URL)

vectorstore = Chroma(
    persist_directory="./chroma_db",
    embedding_function=embedding_model
)

retriever = vectorstore.as_retriever(search_kwargs={"k": 3})

# TOOLS
_PREFIX_RE = re.compile(r"^\s*(создай|создать|добавь|добавить)(\s+(новую\s+)?задачу)?\s*[:\-]?\s*", re.IGNORECASE)
_GARBAGE_RE = re.compile(r"\b(final answer|observation|thought|action)\b.*$", re.IGNORECASE | re.DOTALL)

def clean_title(text: str) -> str:
    text = _GARBAGE_RE.sub("", text)
    text = _PREFIX_RE.sub("", text)
    return re.sub(r"\s+", " ", text).strip().strip("\"'")

def create_task_func(title: str) -> str:
    logger.info("TOOL CALLED: create_task")

    clean = clean_title(title)

    if len(clean) < 2:
        return "Название задачи слишком короткое."

    try:
        resp = requests.post(f"{TASK_SERVICE_URL}/tasks", json={"title": clean}, timeout=5)
        resp.raise_for_status()
        task = resp.json()
        return f"Задача '{clean}' создана с ID {task['id']}"
    except Exception as e:
        logger.error("create_task failed: %s", e)
        return f"Ошибка создания задачи: {e}"

def get_tasks_func(_=None) -> str:
    logger.info("TOOL CALLED: get_tasks")

    try:
        resp = requests.get(f"{TASK_SERVICE_URL}/tasks", timeout=5)
        resp.raise_for_status()
        tasks = resp.json()

        if not tasks:
            return "Список задач пуст."

        return "\n".join(f"- {t['title']} (ID: {t['id']}, статус: {t['status']})" for t in tasks)
    except Exception as e:
        logger.error("get_tasks failed: %s", e)
        return f"Ошибка получения задач: {e}"

def delete_task_func(task_id: str) -> str:
    logger.info("TOOL CALLED: delete_task")

    clean_id = re.sub(r"[^a-zA-Z0-9\-]", "", task_id)

    if len(clean_id) < 10:
        return "Некорректный ID."

    try:
        resp = requests.delete(f"{TASK_SERVICE_URL}/tasks/{clean_id}", timeout=5)

        if resp.status_code == 404:
            return f"Задача {clean_id} не найдена."

        resp.raise_for_status()
        return f"Задача {clean_id} удалена."
    except Exception as e:
        logger.error("delete_task failed: %s", e)
        return f"Ошибка удаления: {e}"

def search_docs_func(query: str) -> str:
    logger.info("TOOL CALLED: search_docs")

    try:
        docs = retriever.invoke(query)
        return "\n\n".join(d.page_content for d in docs) if docs else "Ничего не найдено."
    except Exception as e:
        logger.error("search_docs failed: %s", e)
        return "Ошибка поиска."

# TOOLS LIST
task_tools = [
    Tool(name="create_task", func=create_task_func, return_direct=True, description="Создать задачу. Вход: название задачи."),
    Tool(name="get_tasks", func=get_tasks_func, description="Получить список всех задач."),
    Tool(name="delete_task", func=delete_task_func, description="Удалить задачу. Вход: ID задачи."),
]

rag_tools = [
    Tool(
        name="search_docs",
        func=search_docs_func,
        return_direct=True,
        description="Отвечает на вопросы о системе, Redis, PostgreSQL, Kafka, архитектуре, как создать/удалить/просмотреть задачу."
    )

]

# PROMPTS
TASK_AGENT_PROMPT = """
Ты AI агент, который управляет задачами.

СТРОГО:
- Один запрос = один вызов инструмента
- После инструмента сразу Final Answer
- Final Answer = ТОЧНО результат инструмента
- Пользователю ты выводишь ТОЛЬКО результат Final Answer
- Ничего не добавлять
- Не выдумывать ID
- Не повторять действия

## КРИТИЧЕСКОЕ ПРАВИЛО
Никогда не пиши Action и Final Answer одновременно.
Если ты вызвал Action - ЖДИ Observation.
После Observation - ТОЛЬКО Final Answer.
Если ты уже написал Final Answer - СРАЗУ ЗАВЕРШИ.
Если ты получил Observation - ты ОБЯЗАН сразу выдать Final Answer.
Запрещено генерировать новый Action после Observation.

Если ты уже получил Observation от инструмента:
- НЕ вызывай инструмент снова
- СРАЗУ выдай Final Answer
- Сделай это за один шаг
Никогда не вызывай один и тот же инструмент дважды подряд.

Ты ОБЯЗАН использовать формат:

Action: <название>
Action Input: <вход>

НИКОГДА не используй JSON.
НИКОГДА не пиши фигурные скобки.
"""

RAG_AGENT_PROMPT = """
Ты — AI-ассистент, который отвечает на вопросы пользователя, используя только инструмент search_docs.

Никогда не отвечай сам.
Всегда вызывай search_docs с вопросом пользователя в качестве входных данных.

Формат ответа (обязательно):
Thought: нужно найти информацию в документации
Action: search_docs
Action Input: <вопрос пользователя>
Observation: результат поиска
Final Answer: <результат поиска>

Не добавляй никаких пояснений до или после.
Пример:
User: что такое Redis?
Thought: нужно найти информацию о Redis.
Action: search_docs
Action Input: что такое Redis
Observation: Redis — это in-memory база данных, используется для кэширования.
Final Answer: Redis — это in-memory база данных, используется для кэширования.

Теперь ответь на вопрос пользователя.
"""

# LLM
llm = ChatOllama(
    model=LLM_MODEL,
    base_url=OLLAMA_BASE_URL,
    temperature=0,
)

# AGENTS
task_agent = initialize_agent(
    task_tools,
    llm,
    agent=AgentType.ZERO_SHOT_REACT_DESCRIPTION,
    verbose=True,
    handle_parsing_errors="Check your output format and DO NOT return Action and Final Answer together",
    max_iterations=7,
    agent_kwargs={"prefix": TASK_AGENT_PROMPT}
)

rag_agent = initialize_agent(
    rag_tools,
    llm,
    agent=AgentType.STRUCTURED_CHAT_ZERO_SHOT_REACT_DESCRIPTION,
    verbose=True,
    handle_parsing_errors=True,
    max_iterations=3,
    agent_kwargs={"prefix": RAG_AGENT_PROMPT}
)

QUESTION_STARTS = (
    "как", "почему", "зачем", "что ", "что?", "чем", "где", "когда",
    "сколько", "какой", "какая", "какие", "кто", "расскажи", "объясни",
)
COMMAND_STEMS = ("созда", "добав", "удал", "покаж", "выведи", "список задач", "мои задачи")

def classify_intent(user_input: str) -> str:
    text = user_input.lower().strip().lstrip("¿¡\"'«(")

    if text.startswith(QUESTION_STARTS):
        return "rag"
    if any(stem in text for stem in COMMAND_STEMS):
        return "task"
    return "unknown"

def llm_classify(user_input: str) -> str:
    prompt = (
        "Определи тип запроса к ToDo-менеджеру. Ответь ОДНИМ словом.\n"
        "TASK - пользователь хочет создать, показать или удалить задачу.\n"
        "RAG - пользователь задаёт вопрос о системе, архитектуре или технологиях.\n"
        f"Запрос: {user_input}\nОтвет:"
    )
    try:
        answer = llm.invoke(prompt).content.strip().upper()
        return "task" if answer.startswith("TASK") else "rag"
    except Exception as e:
        logger.warning("llm_classify failed: %s", e)
        return "rag"

def run_agent(agent, user_input: str) -> str:
    last_error = None
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            response = agent.invoke({"input": user_input})
            if isinstance(response, dict) and "output" in response:
                return response["output"]
            return str(response)
        except Exception as e:
            last_error = e
            ERRORS.inc()
            logger.warning("agent attempt %d/%d failed: %s", attempt, MAX_RETRIES, e)
    raise last_error

class OrchestratorState(TypedDict):
    input: str
    intent: str
    output: str

def route_node(state: OrchestratorState) -> dict:
    intent = classify_intent(state["input"])
    if intent == "unknown":
        intent = llm_classify(state["input"])
    INTENTS.labels(intent=intent).inc()
    logger.info("query=%r intent=%s", state["input"], intent)
    return {"intent": intent}

def task_node(state: OrchestratorState) -> dict:
    return {"output": run_agent(task_agent, state["input"])}

def rag_node(state: OrchestratorState) -> dict:
    return {"output": run_agent(rag_agent, state["input"])}

def pick_branch(state: OrchestratorState) -> str:
    return state["intent"]

graph = StateGraph(OrchestratorState)
graph.add_node("route", route_node)
graph.add_node("task_agent", task_node)
graph.add_node("rag_agent", rag_node)
graph.set_entry_point("route")
graph.add_conditional_edges("route", pick_branch, {"task": "task_agent", "rag": "rag_agent"})
graph.add_edge("task_agent", END)
graph.add_edge("rag_agent", END)
orchestrator = graph.compile()

# PROCESS
@LATENCY.time()
def process_query(user_input: str) -> str:
    REQUESTS.inc()

    try:
        result = orchestrator.invoke({"input": user_input, "intent": "", "output": ""})
        return result["output"]
    except Exception as e:
        logger.error("process_query failed: %s", e)
        return f"Ошибка: {e}"

app = FastAPI()

@app.get("/ask")
def ask(q: str):
    response = process_query(q)
    return {"answer": response}

app.mount("/static", StaticFiles(directory="static"), name="static")

@app.get("/", response_class=HTMLResponse)
async def serve_chat_ui():
    with open("static/index.html", "r", encoding="utf-8") as f:
        return HTMLResponse(content=f.read())

# METRICS
start_http_server(9000)
