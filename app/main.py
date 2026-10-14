import os

import psycopg
from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.responses import JSONResponse
from psycopg.rows import dict_row
from pydantic import BaseModel, Field

app = FastAPI()

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
    with get_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute(
                "SELECT id, title, completed FROM tasks ORDER BY id"
            )
            tasks = cursor.fetchall()

    return tasks


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
