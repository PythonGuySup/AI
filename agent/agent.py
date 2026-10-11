import os
import re
import time
import requests
import logging
import random
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse
from prometheus_client import Counter, Histogram, start_http_server
from langchain_ollama import ChatOllama
from langchain_core.tools import Tool
from langchain_classic.agents import initialize_agent, AgentType
from langchain_community.vectorstores import Chroma
from langchain_ollama import OllamaEmbeddings
from langchain_chroma import Chroma

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

# RAG
embedding_model = OllamaEmbeddings(
    model="llama3.2:3b",
    base_url=os.getenv("OLLAMA_BASE_URL", "http://ollama:11434")
)

vectorstore = Chroma(
    persist_directory="./chroma_db",
    embedding_function=embedding_model
)

retriever = vectorstore.as_retriever(search_kwargs={"k": 3})

# Logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("task_agent")

# Metrics
REQUESTS = Counter("agent_requests_total", "Total user requests")
LATENCY = Histogram("agent_latency_seconds", "Latency")

# Config
TASK_SERVICE_URL = os.getenv("TASK_SERVICE_URL", "http://task-service:8001")

# STYLE
def add_style(text: str) -> str:
    styles = [
        f"Ну держи: {text}",
        f"Сделал. Не благодари. {text}",
        f"Вот тебе результат, гений: {text}",
        f"Я, конечно, сомневался, но вот: {text}",
        f"Ладно, вот твоя задача: {text}",
        f"Готово. Надеюсь, не забудешь как обычно: {text}"
    ]
    return random.choice(styles)

#  TOOLS
def clean_text(text: str) -> str:
    text = text.lower().strip()
    text = re.sub(r"(final answer|observation|thought|action).*$", "", text, flags=re.IGNORECASE)
    text = re.sub(r"(создай|создать|добавь|добавить)\s+задачу", "", text)
    return re.sub(r"\s+", " ", text).strip().strip('"').strip("'")

def create_task_func(title: str) -> str:
    print("TOOL CALLED: create_task")

    raw_title = clean_text(title)

    if len(raw_title) < 2:
        return "Название задачи слишком короткое."

    try:
        resp = requests.post(f"{TASK_SERVICE_URL}/tasks", json={"title": raw_title}, timeout=5)
        resp.raise_for_status()
        task = resp.json()
        return f"Задача '{raw_title}' создана с ID {task['id']}"
    except Exception as e:
        logger.error(e)
        return f"Ошибка создания задачи: {e}"

def get_tasks_func(_=None) -> str:
    try:
        resp = requests.get(f"{TASK_SERVICE_URL}/tasks", timeout=5)
        resp.raise_for_status()
        tasks = resp.json()

        if not tasks:
            return "Список задач пуст."

        result = ""
        for t in tasks:
            result += f"- {t['title']} (ID: {t['id']}, статус: {t['status']})\n"

        return result.strip()

    except Exception as e:
        logger.error(e)
        return f"Ошибка получения задач: {e}"

def delete_task_func(task_id: str) -> str:
    print("TOOL CALLED: delete_task")

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
        logger.error(e)
        return f"Ошибка удаления: {e}"

def search_docs_func(query: str) -> str:
    try:
        docs = retriever.invoke(query)
        return "\n\n".join([doc.page_content for doc in docs]) if docs else "Ничего не найдено."
    except Exception as e:
        logger.error(e)
        return "Ошибка поиска."

# TOOLS LIST
task_tools = [
    Tool(name="create_task", func=create_task_func, return_direct=True, description="Создать задачу"),
    Tool(name="get_tasks", func=get_tasks_func, description="Получить задачи"),
    Tool(name="delete_task", func=delete_task_func, description="Удалить задачу"),
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

Важно: выводи ТОЛЬКО в формате: 
Thought: ... 
Action: search_docs 
Action Input: ... 
Observation: ... (это сгенерирует система) 
Final Answer: ... 

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
    model="llama3.2:3b",
    base_url=os.getenv("OLLAMA_BASE_URL", "http://ollama:11434"),
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
    max_iterations=3,
    agent_kwargs={"prefix": RAG_AGENT_PROMPT}
)

# PROCESS
@LATENCY.time()
def process_query(user_input: str) -> str:
    REQUESTS.inc()
    logger.info(user_input)

    try:
        text = user_input.lower()

        if any(w in text for w in ["создай", "добавь", "удали", "покажи"]):
            response = task_agent.invoke({"input": user_input})
        else:
            response = rag_agent.invoke({"input": user_input})

        if isinstance(response, dict) and "output" in response:
            return response["output"]

        return str(response)

    except Exception as e:
        logger.error(e)
        return f"Ошибка: {e}"

# METRICS
start_http_server(9000)