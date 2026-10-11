# Архитектура Event-Driven ToDo Manager

Система состоит из следующих микросервисов:

- **task-service** (порт 8001): управление задачами, PostgreSQL, Redis кэш, rate limiter, Web UI.
- **event-service** (порт 8002): приём событий, сохранение в MongoDB, отправка в Kafka.
- **notification-service** (порт 8003): consumer Kafka, вывод уведомлений.

Базы данных:
- PostgreSQL: хранит задачи (таблица tasks).
- MongoDB: хранит все события (коллекция events).
- Redis: кэш списка задач (TTL 30 секунд) и хранение rate limiter.

Брокер сообщений: Apache Kafka (топик "tasks").