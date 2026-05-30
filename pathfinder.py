"""
Pathfinding algorithms for the Emergency Response Agent.

Supported algorithms:
  - BFS
  - DFS
  - UCS
  - A*
"""

from __future__ import annotations

from collections import deque
import heapq


DIRS = [(-1, 0), (1, 0), (0, -1), (0, 1)]
ALGORITHM_ALIASES = {
    "a*": "astar",
    "astar": "astar",
    "bfs": "bfs",
    "dfs": "dfs",
    "ucs": "ucs",
    "usc": "ucs",
}


def heuristic(a, b):
    return abs(a[0] - b[0]) + abs(a[1] - b[1])


def neighbors(grid, current):
    row, col = current
    for dr, dc in DIRS:
        next_row = row + dr
        next_col = col + dc
        if grid.is_passable(next_row, next_col, from_r=row, from_c=col):
            yield (next_row, next_col)


def normalize_algorithm(name):
    return ALGORITHM_ALIASES.get((name or "astar").strip().lower(), "astar")


def find_path(grid, algorithm="astar"):
    selected = normalize_algorithm(algorithm)
    return {
        "astar": astar,
        "bfs": bfs,
        "dfs": dfs,
        "ucs": ucs,
    }[selected](grid)


def bfs(grid):
    start = grid.start
    end = grid.end
    queue = deque([start])
    came_from = {start: None}

    while queue:
        current = queue.popleft()
        if current == end:
            return _reconstruct(came_from, current)

        for neighbor in neighbors(grid, current):
            if neighbor in came_from:
                continue
            came_from[neighbor] = current
            queue.append(neighbor)

    return None


def dfs(grid):
    start = grid.start
    end = grid.end
    stack = [start]
    came_from = {start: None}

    while stack:
        current = stack.pop()
        if current == end:
            return _reconstruct(came_from, current)

        next_steps = list(neighbors(grid, current))
        next_steps.reverse()
        for neighbor in next_steps:
            if neighbor in came_from:
                continue
            came_from[neighbor] = current
            stack.append(neighbor)

    return None


def ucs(grid):
    start = grid.start
    end = grid.end
    heap = [(0, 0, start)]
    came_from = {start: None}
    cost_so_far = {start: 0}
    visit_order = 0

    while heap:
        current_cost, _, current = heapq.heappop(heap)
        if current_cost > cost_so_far.get(current, float("inf")):
            continue

        if current == end:
            return _reconstruct(came_from, current)

        for neighbor in neighbors(grid, current):
            step_cost = grid.movement_cost(*neighbor)
            new_cost = current_cost + step_cost
            if new_cost >= cost_so_far.get(neighbor, float("inf")):
                continue

            cost_so_far[neighbor] = new_cost
            came_from[neighbor] = current
            visit_order += 1
            heapq.heappush(heap, (new_cost, visit_order, neighbor))

    return None


def astar(grid):
    start = grid.start
    end = grid.end
    heap = [(heuristic(start, end), 0, 0, start)]
    came_from = {start: None}
    cost_so_far = {start: 0}
    visit_order = 0

    while heap:
        _, current_cost, _, current = heapq.heappop(heap)
        if current_cost > cost_so_far.get(current, float("inf")):
            continue

        if current == end:
            return _reconstruct(came_from, current)

        for neighbor in neighbors(grid, current):
            step_cost = grid.movement_cost(*neighbor)
            new_cost = current_cost + step_cost
            if new_cost >= cost_so_far.get(neighbor, float("inf")):
                continue

            cost_so_far[neighbor] = new_cost
            came_from[neighbor] = current
            visit_order += 1
            priority = new_cost + heuristic(neighbor, end)
            heapq.heappush(heap, (priority, new_cost, visit_order, neighbor))

    return None


def _reconstruct(came_from, current):
    path = [current]
    while came_from.get(current) is not None:
        current = came_from[current]
        path.append(current)
    path.reverse()
    return path


def find_decision_points(path, grid, max_points=5):
    """
    Return path indices worth pausing to reason at:
    turns, near-walls, slow zones, traffic, one-way entries.
    """
    from grid import CellState

    special_states = {
        CellState.SLOW,
        CellState.TRAFFIC,
        CellState.ONEWAY_E,
        CellState.ONEWAY_S,
    }

    points = []
    for index in range(1, len(path) - 1):
        prev_row, prev_col = path[index - 1]
        cur_row, cur_col = path[index]
        next_row, next_col = path[index + 1]

        turning = (cur_row - prev_row != next_row - cur_row) or (
            cur_col - prev_col != next_col - cur_col
        )
        near_wall = any(
            grid.in_bounds(cur_row + dr, cur_col + dc)
            and grid.cells[cur_row + dr][cur_col + dc].state.value == "wall"
            for dr, dc in DIRS
        )
        special = grid.cells[cur_row][cur_col].state in special_states

        if turning or near_wall or special:
            points.append(index)
            if len(points) >= max_points:
                break

    return points


def direction_name(from_row, from_col, to_row, to_col):
    delta = (to_row - from_row, to_col - from_col)
    return {
        (-1, 0): "north",
        (1, 0): "south",
        (0, 1): "east",
        (0, -1): "west",
    }.get(delta, "unknown")


def adjacent_walls(row, col, grid):
    return [
        name
        for dr, dc, name in [
            (-1, 0, "north"),
            (1, 0, "south"),
            (0, -1, "west"),
            (0, 1, "east"),
        ]
        if grid.in_bounds(row + dr, col + dc)
        and grid.cells[row + dr][col + dc].state.value == "wall"
    ]
