"""
FastAPI server for the Emergency Response Agent.

Run:
    python main.py
Then open:
    http://localhost:8000

Optional:
    python main.py --reload
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import time

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel, Field

from grid import Grid, CellState, TRAFFIC_CYCLE
from pathfinder import adjacent_walls, direction_name, find_decision_points, find_path, normalize_algorithm
from reasoning import (
    async_reason_arrival,
    async_reason_blocked,
    async_reason_dispatch,
    async_reason_obstacle,
    async_reason_traffic_wait,
)


BASE_DIR = os.path.dirname(os.path.abspath(__file__))
INDEX_FILE = os.path.join(BASE_DIR, "index.html")
STYLE_FILE = os.path.join(BASE_DIR, "style.css")
APP_FILE = os.path.join(BASE_DIR, "app.js")

sys.path.insert(0, BASE_DIR)

app = FastAPI(title="Emergency Response Agent")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


class GridConfig(BaseModel):
    rows: int = 8
    cols: int = 10
    start: list = Field(default_factory=lambda: [3, 0])
    end: list = Field(default_factory=lambda: [4, 9])
    density: float = 0.20


class TerrainRequest(BaseModel):
    cells: list
    row: int
    col: int
    terrain: str
    rows: int
    cols: int
    start: list
    end: list


class RunRequest(BaseModel):
    cells: list
    rows: int
    cols: int
    start: list
    end: list
    algorithm: str = "astar"


@app.get("/")
async def index():
    return FileResponse(INDEX_FILE)


@app.get("/style.css")
async def style():
    return FileResponse(STYLE_FILE, media_type="text/css")


@app.get("/app.js")
async def script():
    return FileResponse(APP_FILE, media_type="application/javascript")


@app.post("/api/new-grid")
async def new_grid(config: GridConfig):
    grid = Grid(
        rows=config.rows,
        cols=config.cols,
        start=tuple(config.start),
        end=tuple(config.end),
    )
    grid.place_random_obstacles(density=config.density)
    return grid.serialize()


@app.post("/api/set-terrain")
async def set_terrain(req: TerrainRequest):
    grid = _load(req.cells, req.rows, req.cols, tuple(req.start), tuple(req.end))
    try:
        terrain = CellState(req.terrain)
    except ValueError:
        terrain = CellState.WALL
    grid.set_terrain(req.row, req.col, terrain)
    return grid.serialize()


@app.post("/api/run")
async def run_agent(req: RunRequest):
    grid = _load(req.cells, req.rows, req.cols, tuple(req.start), tuple(req.end))
    algorithm = normalize_algorithm(req.algorithm)
    algorithm_label = _algorithm_label(algorithm)

    async def stream():
        yield _sse(
            "status",
            {
                "message": f"Computing route with {algorithm_label}...",
                "phase": "planning",
            },
        )

        path = find_path(grid, algorithm)
        if path is None:
            reason = await async_reason_blocked(grid.wall_count(), algorithm_label)
            yield _sse("blocked", {"reason": reason})
            return

        decision_points = set(find_decision_points(path, grid, max_points=5))
        wall_count = grid.wall_count()
        terrain_counts = grid.terrain_counts()
        start_time = time.time()

        yield _sse("thinking", {"step": f"Dispatch - {algorithm_label} assessment"})
        intro = await async_reason_dispatch(
            grid.start,
            grid.end,
            grid.rows,
            grid.cols,
            wall_count,
            len(path),
            terrain_counts,
            algorithm_label,
        )
        yield _sse(
            "log",
            {
                "step": "Dispatch - initial assessment",
                "message": f"Route computed with {algorithm_label}: {len(path) - 1} steps.",
                "trace": intro,
                "phase": "dispatch",
            },
        )
        yield _sse(
            "status",
            {
                "message": f"En route - {algorithm_label}",
                "phase": "moving",
            },
        )

        step_count = 0

        for index in range(1, len(path)):
            row, col = path[index]
            cell_state = grid.cells[row][col].state.value
            step_count += 1

            if grid.cells[row][col].state == CellState.TRAFFIC:
                is_red = (step_count // TRAFFIC_CYCLE) % 2 == 0
                yield _sse("traffic", {"row": row, "col": col, "red": is_red})
                if is_red:
                    yield _sse("thinking", {"step": f"Step {index} - traffic hold"})
                    wait_reason = await async_reason_traffic_wait(row, col, len(path) - 1 - index)
                    yield _sse(
                        "log",
                        {
                            "step": f"Step {index} - traffic signal",
                            "message": f"Red light at ({row},{col}) - holding.",
                            "trace": wait_reason,
                            "phase": "traffic",
                        },
                    )
                    await asyncio.sleep(0.9)

            slow_delay = 0.36 if grid.cells[row][col].state == CellState.SLOW else 0.18
            yield _sse(
                "move",
                {
                    "row": row,
                    "col": col,
                    "step": index,
                    "total": len(path) - 1,
                    "terrain": cell_state,
                },
            )
            await asyncio.sleep(slow_delay)

            if index in decision_points:
                prev_row, prev_col = path[index - 1]
                heading = direction_name(prev_row, prev_col, row, col)
                walls = adjacent_walls(row, col, grid)
                remaining = len(path) - 1 - index

                yield _sse("thinking", {"step": f"Step {index} - terrain decision"})
                trace = await async_reason_obstacle(
                    row,
                    col,
                    heading,
                    walls,
                    remaining,
                    cell_state,
                )
                yield _sse(
                    "log",
                    {
                        "step": f"Step {index} - {_terrain_label(cell_state)}",
                        "message": f"Position ({row},{col}), heading {heading}.",
                        "trace": trace,
                        "phase": _terrain_phase(cell_state),
                    },
                )

        elapsed = time.time() - start_time
        yield _sse("thinking", {"step": "Target reached - debrief"})
        debrief = await async_reason_arrival(
            len(path) - 1,
            wall_count,
            len(path),
            elapsed,
            terrain_counts,
            algorithm_label,
        )
        yield _sse(
            "arrived",
            {
                "steps": len(path) - 1,
                "dist": len(path),
                "elapsed": round(elapsed, 1),
                "trace": debrief,
            },
        )
        yield _sse("status", {"message": "Target reached", "phase": "arrived"})

    return StreamingResponse(stream(), media_type="text/event-stream")


def _sse(event, data):
    return f"event: {event}\ndata: {json.dumps(data)}\n\n"


def _load(cells_data, rows, cols, start, end):
    grid = Grid(rows=rows, cols=cols, start=start, end=end)
    for row_index, row in enumerate(cells_data):
        for col_index, cell in enumerate(row):
            grid.cells[row_index][col_index].wall = cell["wall"]
            grid.cells[row_index][col_index].state = CellState(cell["state"])
    return grid


def _terrain_label(state):
    return {
        "slow": "slow zone",
        "traffic": "traffic signal",
        "oneway_e": "one-way east",
        "oneway_s": "one-way south",
        "wall": "wall detour",
    }.get(state, "navigation point")


def _terrain_phase(state):
    return {
        "slow": "slow",
        "traffic": "traffic",
        "oneway_e": "oneway",
        "oneway_s": "oneway",
        "wall": "obstacle",
    }.get(state, "obstacle")


def _algorithm_label(name):
    return {
        "astar": "A*",
        "bfs": "BFS",
        "dfs": "DFS",
        "ucs": "UCS",
    }.get(name, "A*")


def _env_flag(name, default=False):
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


if __name__ == "__main__":
    import uvicorn

    parser = argparse.ArgumentParser(description="Run the Emergency Response Agent server.")
    parser.add_argument("--host", default=os.getenv("HOST", "0.0.0.0"))
    parser.add_argument("--port", type=int, default=int(os.getenv("PORT", "8000")))
    parser.add_argument(
        "--reload",
        action="store_true",
        default=_env_flag("UVICORN_RELOAD", False),
        help="Enable auto-reload for local development.",
    )
    args = parser.parse_args()

    print("\nEmergency Response Agent")
    print(f"http://localhost:{args.port}\n")

    target = "main:app" if args.reload else app
    try:
        uvicorn.run(target, host=args.host, port=args.port, reload=args.reload)
    except KeyboardInterrupt:
        pass
