# Observability Lab

Учебный стенд наблюдаемости на Docker Compose: FastAPI и PostgreSQL,
метрики приложения, хоста и контейнеров, дашборд Grafana,
алерты Prometheus и доставка уведомлений через Alertmanager в локальный webhook.

Проект позволяет воспроизвести недоступность API, ошибки подключения к БД
и медленные запросы, затем обнаружить их по метрикам и уведомлениям.

## Архитектура

```text
k6 / curl → FastAPI → PostgreSQL
                ↑
          scrape /metrics
                │
Node Exporter ← Prometheus → Alertmanager → webhook → Docker logs
    (хост)      ↑     ↑
                │     └── Grafana запрашивает PromQL
          cAdvisor
        (контейнеры)
```

Prometheus опрашивает targets и оценивает правила каждые 5 секунд.
Grafana автоматически получает источник Prometheus и дашборд из файлов.
PostgreSQL exporter в эту версию проекта не входит.

## Требования

- Linux-хост с Docker Engine, Compose и Buildx. Стенд проверен на Arch Linux,
  x86_64, с системным Docker daemon.
- Доступ к Docker от текущего пользователя.
- Свободные локальные порты 8001, 3000, 9090, 9093 и порт хоста 9100.

Node Exporter использует `network_mode: host`, `pid: host` и чтение файловой
системы хоста. Он слушает 9100 на интерфейсах хоста. Prometheus обращается
к нему через `host.docker.internal`, добавленный с помощью `host-gateway`.
cAdvisor использует расширенные права и подключения каталогов хоста.
В Compose указан стандартный Docker Root Dir `/var/lib/docker`;
при другом расположении нужно изменить источник соответствующего bind mount.

Проверить расположение данных Docker:

```bash
docker info --format '{{.DockerRootDir}}'
```

Compose рассчитан на локальную учебную среду: используются демонстрационные
учётные данные БД; API не имеет авторизации и HTTPS. Rootless Docker,
Docker Desktop и другие платформы требуют отдельной адаптации доступа
exporters к хосту.

## Запуск

Из корня репозитория:

```bash
docker compose config --quiet
docker compose up -d --build
docker compose ps
```

Сервис `k6` имеет профиль `tools` и не запускается обычным `up`.
Тома Compose создаются автоматически. При пустом томе БД `schema.sql`
создаёт таблицу задач; при существующей БД начальный скрипт не повторяется.
Файл `.env` для текущей конфигурации не требуется.

| Компонент | Адрес |
|---|---|
| API / Swagger | [localhost:8001/docs](http://localhost:8001/docs) |
| Метрики API | [localhost:8001/metrics](http://localhost:8001/metrics) |
| Prometheus targets | [localhost:9090/targets](http://localhost:9090/targets) |
| Правила алертов | [localhost:9090/alerts](http://localhost:9090/alerts) |
| Grafana | [localhost:3000](http://localhost:3000) |
| Дашборд Task API | [Task API](http://localhost:3000/d/adm9j7w) |
| Alertmanager | [localhost:9093](http://localhost:9093) |
| Node Exporter | [localhost:9100/metrics](http://localhost:9100/metrics) |

При первом запуске Grafana логин и пароль — `admin` / `admin`;
после входа установить свой пароль. При сохранённом томе используется
ранее установленный пароль.

Проверка приложения:

```bash
curl -i http://localhost:8001/health/db
curl -i http://localhost:8001/tasks
curl -s http://localhost:8001/metrics
```

На странице Targets должны быть доступны jobs `task-api`, `node`, `cadvisor`.
Состояние `up=1` означает успешный scrape, но не подтверждает работоспособность БД.

## Метрики и дашборд

| Метрика | Тип | Смысл |
|---|---|---|
| `task_list_requests_total{outcome="success\|error"}` | Counter | Завершившиеся вызовы обработчика `GET /tasks`, разделённые по результату |
| `task_list_in_progress` | Gauge | Число выполняющихся обработчиков `GET /tasks` |
| `task_list_duration_seconds` | Histogram | Длительность обработчика, включая подключение к БД и SQL |

`success\|error` в таблице обозначает два допустимых значения label,
а не буквальное значение строки. Метрики относятся к обработчику списка задач,
а не ко всем маршрутам API. Измерение длительности не включает последующую
сериализацию ответа FastAPI и доставку ответа клиенту. Ошибочные обращения
также входят в Histogram. Перезапуск API сбрасывает метрики в памяти.

Дашборд объединяет панели API, памяти/CPU/load average хоста,
файловой системы, дискового I/O, сети и CPU/working set памяти контейнеров.
Сетевой интерфейс и корневая файловая система в запросах выбраны для машины
автора. На другом хосте проверить фильтры `device` и `mountpoint`.

### Примеры PromQL

RPS, суммарно по исходам:

```promql
sum(rate(task_list_requests_total{job="task-api", outcome=~"success|error"}[1m]))
```

Доля ошибок в процентах:

```promql
100 * sum(rate(task_list_requests_total{job="task-api", outcome="error"}[1m]))
/ sum(rate(task_list_requests_total{job="task-api", outcome=~"success|error"}[1m]))
```

p95 в секундах:

```promql
histogram_quantile(0.95,
  sum by (le) (rate(task_list_duration_seconds_bucket{job="task-api"}[1m]))
)
```

Без наблюдений доля ошибок и длительность могут возвращать `NaN`.
Перцентиль Histogram — оценка по корзинам, а не точное измерение отдельных запросов.

## Конфигурация Grafana в Git

- `grafana/datasources.yml` — источник Prometheus с фиксированным UID
  `PBFA97CFB590B2093` и интервалом сбора `5s`.
- `grafana/dashboards.yml` — загрузчик файлов дашбордов.
- `grafana/dashboards/overview.json` — дашборд `Task API`, 14 панелей,
  экспорт в формате Grafana V2 Resource, совместимый с используемой Grafana 13.2.4.

Изменения через UI разрешены, но не записываются обратно в JSON автоматически.
После редактирования сохранить дашборд, экспортировать его как V2 Resource JSON
без замены UID источников и обновить файл в Git. Файловая конфигурация при
последующем обновлении имеет приоритет над сохранёнными в UI изменениями.
Проверка файлов выполняется каждые 30 секунд. При удалении файла дашборд
автоматически не удаляется (`disableDeletion: true`).

## Алерты и уведомления

| Правило | Условие | `for` |
|---|---|---|
| `TaskApiScrapeDown` | `up` для API равен 0 | 30 с |
| `TaskApiHighErrorRate` | Доля ошибок за минуту >20%, трафик >1 запроса/с | 30 с |
| `TaskApiHighLatency` | Оценка p95 за минуту >0,5 с, трафик >1 запроса/с | 30 с |

Prometheus определяет `pending` / `firing` и передаёт алерты в Alertmanager.
Alertmanager группирует их и доставляет JSON в `http://webhook:8080/`.
При восстановлении отправляется `resolved`.

```bash
docker compose logs -f --tail 0 webhook
```

HTTP 200 от webhook подтверждает приём сообщения, а не прочтение человеком.
При прекращении трафика условие алертов ошибок/задержки может перестать
выполняться без фактического восстановления сервиса.

В `routing-demo` сохранены выключенные искусственные правила.
`vector(0) == 1` возвращает пустой результат и отключает алерт;
для включения выбранного правила используется `vector(1)`.
Два warning-алерта группируются по `job` и идут получателю `lab`.
Критический `LabServiceDown` идёт в `lab-critical` и подавляет уведомления
о warning-алертах этого же job через inhibition. Оба получателя используют
локальный webhook. После упражнения все demo-правила выключить.

Проверка и загрузка конфигурации:

```bash
docker compose exec prometheus promtool check config /etc/prometheus/prometheus.yml
docker compose exec alertmanager amtool check-config /etc/alertmanager/alertmanager.yml
docker compose restart prometheus alertmanager
```

## Нагрузочные сценарии k6

Перед запуском убедиться, что API и БД работают и временный `pg_sleep` удалён.

```bash
docker compose run --rm --no-deps k6 run /scripts/baseline.js
docker compose run --rm --no-deps k6 run /scripts/steady.js
docker compose run --rm --no-deps k6 run /scripts/spike.js
```

| Сценарий | Модель |
|---|---|
| `baseline.js` | 2 VU, 30 секунд, пауза 0,5 с после ответа |
| `steady.js` | 5 итераций/с, 1 минута, пул 20 VU |
| `spike.js` | 5 → 30 → 5 итераций/с, 5 этапов, 2 мин 20 с, пул 20 VU |

Одна итерация выполняет один GET `/tasks`. Пороговые условия:
все проверки статуса 200 успешны, ошибок HTTP <1%, p95 HTTP <500 мс;
у arrival-rate сценариев дополнительно нет пропущенных итераций.
При нарушении threshold k6 завершает тест с ненулевым кодом.

### Измеренные результаты

Результаты одного локального запуска каждого сценария, предоставленные
в ходе выполнения лабораторной. Это не повторные измерения и не предел
производительности приложения.

| Сценарий | Запросы | Средний RPS | HTTP avg | HTTP p95 | Ошибки | Пропуски |
|---|---:|---:|---:|---:|---:|---:|
| Baseline | 116 | 3,84 | 19,47 мс | 21,69 мс | 0 | — |
| Steady | 301 | 5,02 | 16,37 мс | 17,27 мс | 0 | 0 |
| Spike | 2449 | 17,49 | 15,86 мс | 19,35 мс | 0 | 0 |

Все thresholds пройдены. Средний RPS всплеска усреднён по всем этапам,
пиковая заданная скорость — 30 запросов/с. Длительный soak-тест пропущен;
отсутствие утечек памяти и длительная стабильность не подтверждены.

## Разборы экспериментов

См. [docs/incidents.md](docs/incidents.md): недоступность API,
остановка БД, медленный SQL, параллельные запросы и тестовые маршруты алертов.
Разборы отражают выполненные упражнения; исходные сырые логи k6 и полная
история метрик в репозитории не сохранены.

## Версии и обновление

Внешние образы в `compose.yaml` и базовый Python в Dockerfile закреплены
по `sha256` digest из использовавшихся локальных образов. Это предотвращает
незаметную смену содержимого тега при следующем запуске. Платформа проверки —
linux/amd64; переносимость каждого digest на другие архитектуры не проверялась.
Обновления выполняются явно: выбрать новый образ, проверить его digest,
изменить ссылку и повторить необходимые проверки.

`requirements.txt` перечисляет прямые Python-зависимости, `constraints.txt`
фиксирует версии текущего набора, включая `prometheus-client==0.26.0`.
Constraints не являются lock-файлом с хешами пакетов.

После изменения кода или зависимостей:

```bash
docker compose up -d --build api
```

## Остановка и данные

```bash
docker compose stop
docker compose start
```

Для удаления контейнеров и сети проекта с сохранением томов:

```bash
docker compose down
```

Повторный запуск — `docker compose up -d`.
В отличие от первоначального Docker-проекта тома этой лабы управляются Compose.
`docker compose down -v` удалит данные PostgreSQL, историю Prometheus,
хранилище Grafana и состояние Alertmanager. Файловые конфигурации и JSON
дашборда останутся, но не заменяют резервную копию данных.
