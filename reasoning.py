"""
Local reasoning engine for the Emergency Response Agent.
"""

import asyncio
import random


def reason_dispatch(
    start,
    end,
    rows,
    cols,
    wall_count,
    path_len,
    terrain_counts=None,
    algorithm_label="A*",
):
    row_gap = abs(end[0] - start[0])
    col_gap = abs(end[1] - start[1])
    detour = path_len - (row_gap + col_gap)
    density_pct = round((wall_count / (rows * cols)) * 100)

    hazards = []
    if terrain_counts:
        if terrain_counts.get("slow", 0):
            hazards.append(f"{terrain_counts['slow']} slow zone(s)")
        if terrain_counts.get("traffic", 0):
            hazards.append(f"{terrain_counts['traffic']} traffic signal(s)")
        if terrain_counts.get("oneway_e", 0) + terrain_counts.get("oneway_s", 0):
            count = terrain_counts.get("oneway_e", 0) + terrain_counts.get("oneway_s", 0)
            hazards.append(f"{count} one-way section(s)")
        if terrain_counts.get("wall", 0):
            hazards.append(f"{terrain_counts['wall']} wall(s)")

    hazard_str = f"{', '.join(hazards)} detected on route. " if hazards else ""

    if detour <= 0:
        detour_msg = "Direct line to target is clear."
    elif detour <= 2:
        detour_msg = f"Minor detour of {detour} step(s) required."
    else:
        detour_msg = f"Significant detour of {detour} steps required. Obstacle density is {density_pct}%."

    options = [
        f"Dispatch confirmed. Using {algorithm_label}. {hazard_str}{detour_msg} Planned route length is {path_len} steps.",
        f"Route computed with {algorithm_label}. {hazard_str}Current path is {path_len} steps. {detour_msg}",
        f"Navigation initiated with {algorithm_label}. {hazard_str}{detour_msg} Advancing on a {path_len}-step route.",
    ]
    return random.choice(options)


def reason_obstacle(row, col, direction, walls_nearby, steps_remaining, cell_state="empty"):
    wall_str = " and ".join(walls_nearby) if walls_nearby else "none"

    direction_logic = {
        "north": "Moving north reduces row distance to target.",
        "south": "Moving south aligns the route with the target row.",
        "east": "Moving east closes the column gap.",
        "west": "Moving west briefly clears the obstacle cluster before turning back.",
    }
    logic = direction_logic.get(direction, "Choosing the next cell that best preserves progress.")

    terrain_note = {
        "slow": f"Entering a slow zone at ({row},{col}). Speed drops here, but the route remains viable.",
        "traffic": f"Approaching the traffic signal at ({row},{col}). Passing as soon as the signal permits.",
        "oneway_e": f"Using the eastbound one-way section at ({row},{col}) because it matches the current heading.",
        "oneway_s": f"Using the southbound one-way section at ({row},{col}) because it matches the current heading.",
        "wall": f"Wall pressure near ({row},{col}). Rerouting {direction}. {logic}",
        "empty": f"Navigation checkpoint at ({row},{col}). Nearby walls: {wall_str}. {logic}",
    }.get(cell_state, f"Navigation checkpoint at ({row},{col}). {logic}")

    return f"{terrain_note} {steps_remaining} steps remaining."


def reason_traffic_wait(row, col, steps_remaining):
    options = [
        f"Traffic signal at ({row},{col}) is red. Holding for one cycle before moving on. {steps_remaining} steps remain.",
        f"Mandatory stop at traffic signal ({row},{col}). Resuming once the light changes. {steps_remaining} steps remain.",
        f"Traffic control at ({row},{col}) is blocking movement. Waiting out the red cycle before continuing.",
    ]
    return random.choice(options)


def reason_arrival(steps, wall_count, path_len, elapsed, terrain_counts=None, algorithm_label="A*"):
    efficiency = round((path_len / max(steps, 1)) * 100)
    hazards_crossed = []

    if terrain_counts:
        if terrain_counts.get("slow", 0):
            hazards_crossed.append(f"{terrain_counts['slow']} slow zone(s)")
        if terrain_counts.get("traffic", 0):
            hazards_crossed.append(f"{terrain_counts['traffic']} traffic signal(s)")
        if terrain_counts.get("oneway_e", 0) + terrain_counts.get("oneway_s", 0):
            hazards_crossed.append("one-way sections")

    hazard_str = f"Navigated through {', '.join(hazards_crossed)}. " if hazards_crossed else ""
    options = [
        f"Target reached in {elapsed:.1f}s. {hazard_str}{algorithm_label} completed the route at {efficiency}% efficiency.",
        f"Arrived in {steps} steps and {elapsed:.1f}s. {hazard_str}Route chosen by {algorithm_label} held steady to the target.",
        f"Mission complete in {elapsed:.1f}s. {hazard_str}{algorithm_label} finished a {path_len}-step route successfully.",
    ]
    return random.choice(options)


def reason_blocked(wall_count, algorithm_label="A*"):
    options = [
        f"{algorithm_label} found no viable route. {wall_count} terrain obstacles form a complete barrier.",
        f"Route computation failed under {algorithm_label}. {wall_count} blocked cells create an impassable barrier.",
        f"Navigation is blocked. {algorithm_label} could not cross the current obstacle layout of {wall_count} blocked cells.",
    ]
    return random.choice(options)


async def async_reason_dispatch(
    start,
    end,
    rows,
    cols,
    wall_count,
    path_len,
    terrain_counts=None,
    algorithm_label="A*",
):
    await asyncio.sleep(0.4)
    return reason_dispatch(
        start,
        end,
        rows,
        cols,
        wall_count,
        path_len,
        terrain_counts,
        algorithm_label,
    )


async def async_reason_obstacle(
    row,
    col,
    direction,
    walls_nearby,
    steps_remaining,
    cell_state="empty",
):
    await asyncio.sleep(0.3)
    return reason_obstacle(row, col, direction, walls_nearby, steps_remaining, cell_state)


async def async_reason_traffic_wait(row, col, steps_remaining):
    await asyncio.sleep(0.2)
    return reason_traffic_wait(row, col, steps_remaining)


async def async_reason_arrival(
    steps,
    wall_count,
    path_len,
    elapsed,
    terrain_counts=None,
    algorithm_label="A*",
):
    await asyncio.sleep(0.4)
    return reason_arrival(
        steps,
        wall_count,
        path_len,
        elapsed,
        terrain_counts,
        algorithm_label,
    )


async def async_reason_blocked(wall_count, algorithm_label="A*"):
    await asyncio.sleep(0.3)
    return reason_blocked(wall_count, algorithm_label)
