import pytest
import requests
import time

# Конфигурация
AGENT_URL = "http://localhost:8500"
TASK_API_URL = "http://localhost:8001"

def ask_agent(query: str) -> str:
    """Отправить запрос агенту и вернуть текстовый ответ."""
    resp = requests.get(f"{AGENT_URL}/ask", params={"q": query}, timeout=240)
    assert resp.status_code == 200
    data = resp.json()
    return data.get("answer", "")

def create_task_via_api(title: str) -> str:
    """Создать задачу напрямую через API task-service."""
    resp = requests.post(f"{TASK_API_URL}/tasks", json={"title": title}, timeout=240)
    assert resp.status_code == 200
    return resp.json()["id"]

def delete_task_via_api(task_id: str):
    """Удалить задачу напрямую через API."""
    requests.delete(f"{TASK_API_URL}/tasks/{task_id}", timeout=240)

def test_agent_create_task():
    """Агент должен создать задачу и вернуть подтверждение."""
    answer = ask_agent("создай задачу evals тест")
    assert "создана" in answer, f"Ответ агента: {answer}"

def test_agent_get_tasks():
    """Агент должен показать список задач."""
    answer = ask_agent("покажи мои задачи")
    # Может быть "Список пуст" или список задач
    assert any(word in answer.lower() for word in ["-", "(ID:"]), answer

def test_agent_delete_task():
    """Сначала создадим задачу, потом попросим агента удалить её по ID."""
    task_id = create_task_via_api("задача для удаления")
    answer = ask_agent(f"удали задачу {task_id}")
    assert any(word in answer.lower() for word in ["удалена.", "Задача"]), answer

def test_agent_does_not_create_task_on_question():
    """Агент НЕ должен создавать задачу, когда спрашивают 'что такое Redis'."""
    answer = ask_agent("Что такое Redis?")
    # Проверяем, что в ответе нет слов "создана"
    assert "создана" not in answer.lower()
    # И что ответ содержит информацию о Redis/кэше
    assert any(word in answer.lower() for word in ["redis", "кэш", "in-memory"]), answer

def test_agent_rag_architecture():
    """Агент должен ответить на вопрос об архитектуре, используя RAG."""
    answer = ask_agent("Какая архитектура проекта?")
    # Ожидаем упоминание микросервисов или Kafka
    assert any(word in answer.lower() for word in ["task-service", "event", "kafka", "микросервис"]), answer

# Тесты API task-service (прямые вызовы)
def test_api_create_and_get():
    """Создать задачу через API, затем получить список и убедиться, что она там есть."""
    title = "тест апи"
    task_id = create_task_via_api(title)
    # Получаем список задач
    resp = requests.get(f"{TASK_API_URL}/tasks")
    assert resp.status_code == 200
    tasks = resp.json()
    found = any(t["id"] == task_id for t in tasks)
    assert found, f"Задача {task_id} не найдена в списке"
    delete_task_via_api(task_id)

def test_api_rate_limiter():
    """Проверяем, что rate limiter (10/сек) срабатывает при быстрых запросах."""
    # Делаем 12 быстрых запросов
    for _ in range(12):
        resp = requests.get(f"{TASK_API_URL}/tasks")
        if resp.status_code == 429:
            break
    else:
        pytest.fail("Rate limiter не сработал после 12 запросов")
    # Ожидаем, что хотя бы один запрос вернул 429

if __name__ == "__main__":
    pytest.main(["-v", __file__])