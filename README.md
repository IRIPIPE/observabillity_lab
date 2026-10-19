# Observability Lab

Учебный стенд наблюдаемости на Docker Compose: FastAPI и PostgreSQL,
метрики приложения, хоста и контейнеров, JSON-логи в Loki,
tracing через OpenTelemetry и Tempo, дашборд Grafana,
алерты Prometheus и доставка уведомлений через Alertmanager в локальный webhook.

Проект позволяет воспроизвести недоступность API, ошибки подключения к БД
и медленные запросы, затем обнаружить их по метрикам и уведомлениям.
Для отдельного запроса можно найти причину ошибки в логах, перейти к trace
и увидеть время подключения к БД и выполнения SQL. Отдельный клиент
демонстрирует передачу контекста трассировки через HTTP.

## Архитектура

```text
k6 / curl / lab-client → FastAPI → PostgreSQL

Метрики: API /metrics, Node Exporter, cAdvisor
                        ↓ scrape
                    Prometheus → Alertmanager → webhook

Логи:    API stdout/stderr → Docker API → Alloy → Loki
Traces:  API / lab-client ── OTLP/HTTP ──→ Alloy ── OTLP/gRPC ──→ Tempo

Grafana запрашивает Prometheus, Loki и Tempo.
Переходы между логами и traces связаны через trace_id.
```

Prometheus опрашивает targets и оценивает правила каждые 5 секунд.
Grafana автоматически получает источники Prometheus, Loki, Tempo и дашборд
из файлов. Alloy собирает логи сервиса `api` по Docker labels проекта
`observability-lab`. Для traces он слушает `alloy:4318` и отправляет их
в `tempo:4317`; оба порта используются внутри Compose-сети.
PostgreSQL exporter в эту версию проекта не входит.

## Требования

- Linux-хост с Docker Engine, Compose и Buildx. Стенд проверен на Arch Linux,
  x86_64, с системным Docker daemon.
- Доступ к Docker от текущего пользователя.
- Свободные локальные порты 8001, 3000, 9090, 9093, 3100, 3200, 12345
  и порт хоста 9100.

Node Exporter использует `network_mode: host`, `pid: host` и чтение файловой
системы хоста. Он слушает 9100 на интерфейсах хоста. Prometheus обращается
к нему через `host.docker.internal`, добавленный с помощью `host-gateway`.
cAdvisor использует расширенные права и подключения каталогов хоста.
В Compose указан стандартный Docker Root Dir `/var/lib/docker`;
при другом расположении нужно изменить источник соответствующего bind mount.
Alloy получает доступ к Docker API через `/var/run/docker.sock`.
Монтирование сокета с `:ro` не ограничивает методы самого Docker API.

Проверить расположение данных Docker:

```bash
docker info --format '{{.DockerRootDir}}'
```

Compose рассчитан на локальную учебную среду: используются демонстрационные
учётные данные БД; API не имеет авторизации и HTTPS. Rootless Docker,
Docker Desktop и другие платформы требуют отдельной адаптации доступа
exporters к хосту.

## Запуск

Из корня репозитория в каталоге `observability-lab`:

```bash
docker compose config --quiet
docker compose up -d --build
docker compose ps
```

Имя Compose-проекта важно для фильтра контейнеров в `alloy/config.alloy`.
При другом имени каталога нужно либо изменить фильтр
`com.docker.compose.project`, либо использовать `docker compose -p observability-lab`
во всех командах вместо `docker compose`.

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
| Loki readiness | [localhost:3100/ready](http://localhost:3100/ready) |
| Tempo readiness | [localhost:3200/ready](http://localhost:3200/ready) |
| Интерфейс Alloy | [localhost:12345](http://localhost:12345) |

При первом запуске Grafana логин и пароль — `admin` / `admin`;
после входа установить свой пароль. При сохранённом томе используется
ранее установленный пароль.

Проверка приложения:

```bash
curl -i http://localhost:8001/health/db
curl -i http://localhost:8001/tasks
curl -s http://localhost:8001/metrics
curl -i http://localhost:3100/ready
curl -i http://localhost:3200/ready
```

Для readiness Loki и Tempo ожидается HTTP 200 после завершения запуска.
Это проверка готовности компонентов; доставку логов и traces проверять
отдельным запросом к API и поиском в Grafana Explore.

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

## Логи: Alloy и Loki

API пишет JSON-события в stdout. Alloy находит контейнер через Docker API,
читает его логи и отправляет в Loki. Конфигурации:

- `alloy/config.alloy` — обнаружение контейнера, чтение и отправка логов;
- `loki/config.yml` — файловое хранилище, схема TSDB v13 и retention;
- `app/main.py` — HTTP middleware и логирование ошибок PostgreSQL.

Два прикладных типа событий:

| Событие | Поля и назначение |
|---|---|
| `http_request` | Метод, путь, HTTP-статус, `duration_ms`, `request_id`; результат обращения |
| `database_error` | Тип и сообщение исключения, `request_id`; причина ошибки подключения |

Если есть активный контекст OpenTelemetry, в запись добавляются `trace_id`
и `span_id`. `request_id` также возвращается клиенту в заголовке `X-Request-ID`.
Для одного сбоя БД появляются две ERROR-записи, описывающие один HTTP-запрос.
При подсчёте ошибочных запросов нужно фильтровать `event="http_request"`.

`duration_ms` измеряется до получения ответа от обработчика, без полной
передачи тела клиенту. JSON middleware пропускает `/metrics` и `/health`.
Стандартные текстовые access logs Uvicorn продолжают собираться вместе с JSON.

Индексируемые labels логов: `service_name="task-api"`, `environment="lab"`.
Идентификаторы запросов, HTTP-статус и длительность остаются полями JSON.
`request_id` и `trace_id` не используются как индексируемые labels:
уникальные значения создавали бы отдельные потоки и высокую кардинальность.
Поля, извлечённые через `| json` при поиске, не меняют хранимые потоки.

### Поиск в Grafana Explore

Выбрать источник **Loki**, режим **Code** и интервал, содержащий запрос.
Все JSON-записи API:

```logql
{service_name="task-api", environment="lab"}
| json
| __error__=""
```

`__error__=""` исключает ошибки разбора, например текстовые строки Uvicorn.
Это не фильтр HTTP-ошибок приложения.

Неуспешные HTTP-запросы:

```logql
{service_name="task-api", environment="lab"}
| json
| event="http_request"
| status_code >= 500
| __error__=""
```

Медленные обращения, более 20 миллисекунд:

```logql
{service_name="task-api", environment="lab"}
| json
| event="http_request"
| duration_ms > 20
| __error__=""
```

Связанные записи одного запроса — подставить ID из заголовка ответа:

```logql
{service_name="task-api", environment="lab"}
| json
| __error__=""
| request_id="ВСТАВЬ_REQUEST_ID"
```

Для поиска всего trace можно заменить последний фильтр на `trace_id="ВСТАВЬ_TRACE_ID"`.

### График HTTP 5xx из логов

Панель Time series с источником Loki:

```logql
sum(
  count_over_time(
    {service_name="task-api", environment="lab"}
    | json
    | event="http_request"
    | status_code >= 500
    | __error__=""
    [1m]
  )
)
```

Каждая точка показывает число подходящих записей за предшествующую минуту,
а не RPS. Окно скользящее; одна ошибка может участвовать в соседних точках.
Отсутствие подходящих записей может отображаться как пропуск и само по себе
не доказывает исправность API или сборщика. Запрос проверен в UI; текущий
JSON-экспорт дашборда ещё не содержит эту панель.

### Хранение и проверка конфигурации

В Loki включён Compactor retention: `retention_period: 168h` (7 дней),
`compaction_interval: 10m`, `retention_delete_delay: 2h`.
Очистка асинхронная, а рабочие файлы Compactor находятся в томе `loki-data`.
`schema_config.index.period: 24h` задаёт период индекса, а не срок хранения.
Retention Loki не управляет исходными Docker-логами контейнеров.
Конфигурация проверена и загружена; удаление данных по истечении семи дней
отдельным длительным экспериментом не проверялось.

```bash
docker compose run --rm --no-deps loki \
  -config.file=/etc/loki/config.yml -verify-config=true
docker compose run --rm --no-deps alloy validate /etc/alloy/config.alloy
```

После изменения соответствующего файла:

```bash
docker compose restart loki alloy
```

## Tracing: OpenTelemetry, Alloy и Tempo

OpenTelemetry SDK в API создаёт spans, `BatchSpanProcessor` передаёт их
в фоне через OTLP/HTTP на `http://alloy:4318/v1/traces`.
Alloy объединяет данные в пакеты и отправляет через OTLP/gRPC на `tempo:4317`.
Tempo работает в режиме `-target=all` и сохраняет данные в томе `tempo-data`.
Файл настройки — `tempo/config.yml`. Grafana использует HTTP API `tempo:3200`.

FastAPI instrumentation создаёт серверный HTTP span. Служебные URL,
совпадающие с `/metrics` и `/health`, а также технические ASGI send/receive
spans исключены. Для `GET /tasks` вручную добавлены дочерние spans:

```text
task-api: GET /tasks            SERVER
├── db.connect                 CLIENT — получение соединения
└── db.query.tasks             CLIENT — SQL и получение результата
```

HTTP span включает дочерние операции: складывать его длительность
с длительностями детей нельзя. DB spans измеряются в процессе API,
а не внутри PostgreSQL. Другие маршруты задач имеют HTTP spans,
но отдельных DB spans для них пока нет.

В **Explore → Tempo → TraceQL**:

```traceql
{ resource.service.name = "task-api" }
```

При поиске нового запроса учитывать фоновую отправку spans — она может
занять несколько секунд. Успешный span может иметь статус `unset`;
HTTP-статус смотреть в атрибутах. Исключение, покинувшее ручной блок span,
записывается как событие `exception` и отмечает этот span ошибочным.

Сэмплер в приложении явно не переопределён, политики head/tail sampling
в Alloy не настроены. Практика sampling пропущена. Для обычных запросов
без входящего родительского контекста используется стандартный режим SDK
с записью всех новых traces; входящее решение родителя учитывается.

### Переходы между логами и traces

В `grafana/datasources.yml` настроены оба направления:

1. В Loki раскрыть JSON-запись, при необходимости свернуть **Log line**,
   найти дополнительное поле **TraceID** и нажать **Open trace**.
2. В Tempo выбрать span и нажать **Logs for this trace**.

Для обратного перехода Grafana сопоставляет `service.name` из span/resource
с label Loki `service_name`, фильтрует по Trace ID и расширяет временной
интервал на минуту в обе стороны. Фильтр по Span ID выключен,
поэтому видны записи всего trace. **Log context** в Loki показывает
соседние записи и не является переходом в Tempo.

`trace_context_fields()` добавляет контекст в JSON; `request_id` и `trace_id`
выполняют разные задачи и не обязаны совпадать. Derived field создаёт
ссылку, но не сам trace. Отсутствующий, ещё не доставленный или удалённый
trace по такой ссылке не откроется.

### Передача контекста от клиента

`tests/tracing/client.py` запускает одноразовый HTTP-клиент с именем сервиса
`lab-client`. Он создаёт CLIENT span, через `inject(headers)` передаёт
контекст в заголовке `traceparent` и отправляет свой span через Alloy.
Инструментация FastAPI извлекает входящий контекст, связывая операции API
с клиентским span.

При работающих API, БД, Alloy и Tempo:

```bash
docker compose exec -T api python < tests/tracing/client.py
```

Файл передаётся через stdin отдельному процессу в контейнере; дополнительных
зависимостей или bind mounts для него не требуется. Команда выводит
`traceparent`, Trace ID и HTTP-статус. Найти напечатанный ID в Tempo.
Ожидаются два имени сервисов, четыре spans и один общий Trace ID:

```text
lab-client: GET task-api
└── task-api: GET /tasks
    ├── db.connect
    └── db.query.tasks
```

PostgreSQL здесь не является третьим инструментированным сервисом.

## Конфигурация Grafana в Git

- `grafana/datasources.yml` — источники Prometheus (UID `PBFA97CFB590B2093`,
  интервал сбора `5s`), Loki (UID `loki`) и Tempo (UID `tempo`),
  а также ссылки между логами и traces.
- `grafana/dashboards.yml` — загрузчик файлов дашбордов.
- `grafana/dashboards/overview.json` — дашборд `Task API`, 14 панелей,
  экспорт в формате Grafana V2 Resource, проверенный с Grafana 13.2.4.
  Панель HTTP 5xx из Loki, добавленная в UI, пока не входит в этот файл.

Изменения через UI разрешены, но не записываются обратно в JSON автоматически.
После редактирования сохранить дашборд, экспортировать его как V2 Resource JSON
без замены UID источников и обновить файл в Git. Файловая конфигурация при
последующем обновлении имеет приоритет над сохранёнными в UI изменениями.
Проверка файлов выполняется каждые 30 секунд. При удалении файла дашборд
автоматически не удаляется (`disableDeletion: true`).
После правки файла источников данных перезапустить Grafana:

```bash
docker compose restart grafana
```

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
в ходе выполнения лабораторной до добавления JSON-логирования и tracing.
Это не повторные измерения и не предел производительности приложения;
накладные расходы новой инструментации этими результатами не оценены.

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

### Сбой БД: от лога к ошибочному span

При запущенном стенде выполнить один запрос с остановленной БД и восстановить её:

```bash
docker compose stop db
curl -i http://localhost:8001/tasks
docker compose start db
```

Ожидается HTTP 503 с `X-Request-ID`. Найти запрос в Loki по этому ID:
появятся `http_request` со статусом 503 и `database_error` с причиной,
связанные общими `request_id` и `trace_id`. Нажать **Open trace**.

Ожидаемая структура:

```text
GET /tasks          ERROR, HTTP 503
└── db.connect      ERROR, событие exception
```

`db.query.tasks` отсутствует: подключение не состоялось и SQL не выполнялся.
В выполненном эксперименте сообщение было `failed to resolve host 'db'`:
сбой произошёл при разрешении имени, до TCP-подключения и авторизации.
В других условиях ошибка может быть иной, например отказ подключения
или таймаут; ориентироваться на сообщение конкретного исключения.

После старта PostgreSQL проверить восстановление, повторив при необходимости
после завершения его запуска:

```bash
curl -i http://localhost:8001/health/db
curl -i http://localhost:8001/tasks
```

Оба запроса должны вернуть 200. При одном ошибочном запросе алерт высокой
доли ошибок может не сработать: его правило требует трафик более 1 запроса/с.

## Версии и обновление

В текущем `compose.yaml` явно указаны версии Loki `3.7.8`,
Alloy `v1.21.0`, Tempo `3.1.0`, cAdvisor `0.60.6` и k6 `2.3.0`.
PostgreSQL использует тег `16`, Python — `3.12-slim`; Prometheus, Grafana,
Alertmanager и Node Exporter используют образы без явного тега.
Образы не закреплены по digest: содержимое тегов при обновлении может измениться.
Для воспроизводимого обновления нужно выбрать версии/digests и повторить
проверки конфигурации и работы стенда.

`requirements.txt` перечисляет прямые Python-зависимости, `constraints.txt`
фиксирует перечисленные в нём версии, включая `prometheus-client==0.26.0`,
OpenTelemetry SDK/exporter `1.45.1` и FastAPI instrumentation `0.66b1`.
После добавления OpenTelemetry полный список транзитивных зависимостей
не обновлялся. Constraints не являются lock-файлом с хешами пакетов.

После изменения кода или зависимостей:

```bash
docker compose up -d --build api
```

Проверка совместимости установленных Python-зависимостей:

```bash
docker compose run --rm --no-deps -T api python -m pip check
```

Практические политики sampling, SLI/SLO, error budget и burn-rate alerts
в этой версии лабораторной не реализованы.

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
хранилище Grafana, состояние Alertmanager, логи Loki, данные Tempo
и позиции чтения Alloy. Файловые конфигурации и JSON дашборда останутся,
но не заменяют резервную копию данных.
