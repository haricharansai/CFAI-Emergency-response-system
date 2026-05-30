"""
grid.py — Grid state + terrain types for the Emergency Agent

Terrain types:
  wall      - impassable permanently
  slow      - passable at cost 2 (mud, roadworks)
  traffic   - cycles red/green every TRAFFIC_CYCLE steps
  oneway_e  - can only be entered moving east (→)
  oneway_s  - can only be entered moving south (↓)
"""

import random
from dataclasses import dataclass, field
from typing import List
from enum import Enum

TRAFFIC_CYCLE = 4   # traffic flips every N agent steps


class CellState(str, Enum):
    EMPTY    = "empty"
    WALL     = "wall"
    START    = "start"
    END      = "end"
    PATH     = "path"
    VISITED  = "visited"
    AGENT    = "agent"
    SLOW     = "slow"       # costs 2 moves
    TRAFFIC  = "traffic"    # red/green cycling
    ONEWAY_E = "oneway_e"   # east-only passage
    ONEWAY_S = "oneway_s"   # south-only passage


# Movement cost for each terrain (used by A*)
TERRAIN_COST = {
    CellState.EMPTY:    1,
    CellState.START:    1,
    CellState.END:      1,
    CellState.PATH:     1,
    CellState.SLOW:     2,
    CellState.TRAFFIC:  1,   # optimistic — agent hopes it'll be green
    CellState.ONEWAY_E: 1,
    CellState.ONEWAY_S: 1,
}

TERRAIN_LABELS = {
    CellState.SLOW:     "SLOW",
    CellState.TRAFFIC:  "TRAF",
    CellState.ONEWAY_E: "→",
    CellState.ONEWAY_S: "↓",
}

PLACEABLE = {CellState.WALL, CellState.SLOW, CellState.TRAFFIC,
             CellState.ONEWAY_E, CellState.ONEWAY_S}


@dataclass
class Cell:
    row:   int
    col:   int
    state: CellState = CellState.EMPTY
    wall:  bool      = False   # True only for WALL type


@dataclass
class Grid:
    rows:  int
    cols:  int
    start: tuple = (0, 0)
    end:   tuple = (0, 0)
    cells: List[List[Cell]] = field(default_factory=list)

    def __post_init__(self):
        self.cells = [
            [Cell(r, c) for c in range(self.cols)]
            for r in range(self.rows)
        ]
        self._set(self.start, CellState.START)
        self._set(self.end,   CellState.END)

    def _set(self, pos, state):
        r, c = pos
        self.cells[r][c].state = state
        self.cells[r][c].wall  = (state == CellState.WALL)

    def in_bounds(self, r, c):
        return 0 <= r < self.rows and 0 <= c < self.cols

    def is_wall(self, r, c):
        """Hard impassable check."""
        if not self.in_bounds(r, c):
            return True
        return self.cells[r][c].state == CellState.WALL

    def is_passable(self, r, c, from_r=None, from_c=None):
        """
        Direction-aware passability.
        from_r/from_c = previous cell (needed for one-way checks).
        """
        if not self.in_bounds(r, c):
            return False
        cell = self.cells[r][c]
        if cell.state == CellState.WALL:
            return False
        if cell.state == CellState.ONEWAY_E:
            # can only enter by moving east: from_c must be c-1
            if from_c is not None and from_c != c - 1:
                return False
        if cell.state == CellState.ONEWAY_S:
            # can only enter by moving south: from_r must be r-1
            if from_r is not None and from_r != r - 1:
                return False
        return True

    def movement_cost(self, r, c):
        return TERRAIN_COST.get(self.cells[r][c].state, 1)

    def is_traffic_red(self, r, c, step):
        """Traffic is red on even cycles."""
        return self.cells[r][c].state == CellState.TRAFFIC and (step // TRAFFIC_CYCLE) % 2 == 0

    def set_terrain(self, r, c, terrain: CellState):
        cell = self.cells[r][c]
        if cell.state in (CellState.START, CellState.END):
            return
        if cell.state == terrain:
            # toggle off
            cell.state = CellState.EMPTY
            cell.wall  = False
        else:
            cell.state = terrain
            cell.wall  = (terrain == CellState.WALL)

    def place_random_obstacles(self, density=0.20):
        terrain_pool = [
            CellState.WALL, CellState.WALL, CellState.WALL,  # walls most common
            CellState.SLOW,
            CellState.TRAFFIC,
            CellState.ONEWAY_E,
            CellState.ONEWAY_S,
        ]
        for r in range(self.rows):
            for c in range(self.cols):
                cell = self.cells[r][c]
                if cell.state in (CellState.START, CellState.END):
                    continue
                if random.random() < density:
                    cell.state = random.choice(terrain_pool)
                    cell.wall  = (cell.state == CellState.WALL)
                else:
                    cell.state = CellState.EMPTY
                    cell.wall  = False
        # guarantee a path exists (ignoring traffic/one-way constraints for safety)
        from pathfinder import astar
        if astar(self) is None:
            for r in range(self.rows):
                for c in range(self.cols):
                    cell = self.cells[r][c]
                    if cell.state not in (CellState.START, CellState.END):
                        cell.state = CellState.EMPTY
                        cell.wall  = False

    def wall_count(self):
        return sum(1 for row in self.cells for c in row
                   if c.state != CellState.EMPTY and c.state not in (CellState.START, CellState.END))

    def terrain_counts(self):
        counts = {t.value: 0 for t in PLACEABLE}
        for row in self.cells:
            for c in row:
                if c.state in PLACEABLE:
                    counts[c.state.value] += 1
        return counts

    def serialize(self):
        return {
            "rows":  self.rows,
            "cols":  self.cols,
            "start": list(self.start),
            "end":   list(self.end),
            "cells": [
                [{"row": c.row, "col": c.col,
                  "state": c.state.value, "wall": c.wall}
                 for c in row]
                for row in self.cells
            ]
        }


def make_default_grid():
    return Grid(rows=8, cols=10, start=(3, 0), end=(4, 9))
