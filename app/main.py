import os

import psycopg
from time import perf_counter
from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.responses import JSONResponse
from psycopg.rows import dict_row
from pydantic import BaseModel, Field
from prometheus_client import (
    Counter,
    Gauge,
    Histogram,
    CONTENT_TYPE_LATEST,
    generate_latest,
)

app = FastAPI()

TASK_LIST_REQUESTS = Counter(
    "task_list_requests_total",
    "Number of completed calls to the task list handler",
    ["outcome"],
)

TASK_LIST_IN_PROGRESS = Gauge(
    "task_list_in_progress",
    "Number of task list handlers currently executing",
)

TASK_LIST_DURATION = Histogram(
    "task_list_duration_seconds",
    "Time spent executing the task list handler",
    buckets=(
        0.005,
        0.01,
        0.015,
        0.02,
        0.03,
        0.05,
        0.1,
        0.5,
        1,
        2,
        5,
    ),
)

TASK_LIST_REQUESTS.labels(outcome="success")
TASK_LIST_REQUESTS.labels(outcome="error")

DATABASE_URL = os.environ["DATABASE_URL"]


def get_connection():
    return psycopg.connect(
        DATABASE_URL,
        connect_timeout=3,
        row_factory=dict_row,
    )


@app.exception_handler(psycopg.OperationalError)
async def database_error_handler(
    request: Request,
    exc: psycopg.OperationalError,
):
    return JSONResponse(
        status_code=503,
        content={"detail": "Database unavailable"},
    )


class TaskCreate(BaseModel):
    title: str = Field(min_length=1, max_length=200)


class TaskUpdate(BaseModel):
    completed: bool


class TaskResponse(BaseModel):
    id: int
    title: str
    completed: bool


@app.get("/")
def root():
    return {"message": "Hello from Docker project"}


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/health/db")
def health_db():
    with get_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute("SELECT current_database() AS database")
            row = cursor.fetchone()

    return {"status": "ok", "database": row["database"]}


@app.post("/tasks", response_model=TaskResponse, status_code=201)
def create_task(task: TaskCreate):
    with get_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO tasks (title)
                VALUES (%s)
                RETURNING id, title, completed
                """,
                (task.title,),
            )
            created_task = cursor.fetchone()

    return created_task


@app.get("/tasks", response_model=list[TaskResponse])
def list_tasks():
    started_at = perf_counter()
    outcome = "error"
    TASK_LIST_IN_PROGRESS.inc()

    try:
        with get_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    "SELECT id, title, completed FROM tasks ORDER BY id"
                )
                tasks = cursor.fetchall()

        outcome = "success"
        return tasks

    finally:
        duration = perf_counter() - started_at
        TASK_LIST_DURATION.observe(duration)

        TASK_LIST_IN_PROGRESS.dec()
        TASK_LIST_REQUESTS.labels(outcome=outcome).inc()


@app.patch("/tasks/{task_id}", response_model=TaskResponse)
def update_task(task_id: int, task: TaskUpdate):
    with get_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute(
                """
                UPDATE tasks
                SET completed = %s
                WHERE id = %s
                RETURNING id, title, completed
                """,
                (task.completed, task_id),
            )
            updated_task = cursor.fetchone()

            if updated_task is None:
                raise HTTPException(
                    status_code=404,
                    detail="Task not found",
                )

    return updated_task


@app.delete("/tasks/{task_id}", status_code=204)
def delete_task(task_id: int) -> Response:
    with get_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute(
                "DELETE FROM tasks WHERE id = %s RETURNING id",
                (task_id,),
            )
            deleted_task = cursor.fetchone()

            if deleted_task is None:
                raise HTTPException(
                    status_code=404,
                    detail="Task not found",
                )

    return Response(status_code=204)

@app.get("/metrics")
def metrics():
    return Response(
        content=generate_latest(),
        headers={"Content-Type": CONTENT_TYPE_LATEST},
    )
