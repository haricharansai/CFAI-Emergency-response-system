const API = "";
const DEFAULT_GRID = {
  rows: 8,
  cols: 10,
  start: [3, 0],
  end: [4, 9],
  density: 0.2
};

let gridState = null;
let running = false;
let activeTerrain = "wall";

const gridEl = document.getElementById("grid");
const logEl = document.getElementById("log");
const statusEl = document.getElementById("status-pill");
const logDotEl = document.getElementById("log-dot");
const sSteps = document.getElementById("s-steps");
const sDist = document.getElementById("s-dist");
const sTime = document.getElementById("s-time");
const btnDispatch = document.getElementById("btn-dispatch");
const btnNew = document.getElementById("btn-new");
const btnReset = document.getElementById("btn-reset");
const paletteEl = document.getElementById("palette");
const algorithmEl = document.getElementById("algorithm");

if (paletteEl) {
  paletteEl.addEventListener("click", (event) => {
    const button = event.target.closest(".terrain-btn");
    if (!button) return;

    document.querySelectorAll(".terrain-btn").forEach((item) => {
      item.classList.remove("active");
    });

    button.classList.add("active");
    activeTerrain = button.dataset.t || "wall";
  });
}

function getErrorMessage(error, fallbackMessage) {
  if (error instanceof TypeError) {
    return "Could not reach the API. Start the backend server and reload the page.";
  }

  if (error && typeof error.message === "string" && error.message.trim()) {
    return error.message;
  }

  return fallbackMessage;
}

async function postJson(path, payload) {
  const response = await fetch(`${API}${path}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload)
  });

  if (!response.ok) {
    throw new Error(`Request failed (${response.status})`);
  }

  return response;
}

function selectedAlgorithm() {
  return algorithmEl?.value || "astar";
}

function selectedAlgorithmLabel() {
  return {
    bfs: "BFS",
    dfs: "DFS",
    astar: "A*",
    ucs: "UCS"
  }[selectedAlgorithm()] || "A*";
}

async function init() {
  await fetchNewGrid();
}

async function fetchNewGrid() {
  try {
    const response = await postJson("/api/new-grid", DEFAULT_GRID);
    gridState = await response.json();
    renderGrid();
    resetStats();
    clearLog();
    addLog(
      "system",
      "System ready",
      "Select a terrain type, choose BFS, DFS, A*, or UCS, then dispatch.",
      ""
    );
    setStatus("Awaiting dispatch", "amber");
  } catch (error) {
    gridState = null;
    gridEl.innerHTML = "";
    resetStats();
    clearLog();
    addLog("blocked", "Initialization error", getErrorMessage(error, "Could not load the map."), "");
    setStatus("Initialization failed", "red");
  }
}

function renderGrid() {
  if (!gridState) return;

  const { rows, cols, cells } = gridState;
  gridEl.style.gridTemplateColumns = `repeat(${cols}, var(--cell))`;
  gridEl.innerHTML = "";

  for (let row = 0; row < rows; row += 1) {
    for (let col = 0; col < cols; col += 1) {
      const cell = cells[row][col];
      const div = document.createElement("div");

      div.className = "cell";
      div.dataset.r = String(row);
      div.dataset.c = String(col);

      applyCellClass(div, cell);

      if (!running) {
        div.addEventListener("click", () => {
          paintCell(row, col);
        });
      }

      gridEl.appendChild(div);
    }
  }
}

function applyCellClass(div, cell) {
  div.className = "cell";

  const state = cell.wall ? "wall" : cell.state;
  div.classList.add(state);

  const labels = {
    start: "A",
    end: "B",
    slow: "S",
    traffic: "T",
    oneway_e: "->",
    oneway_s: "v"
  };

  div.textContent = labels[state] || "";
}

function updateCell(row, col) {
  const div = gridEl.querySelector(`[data-r="${row}"][data-c="${col}"]`);
  if (!div || !gridState) return;
  applyCellClass(div, gridState.cells[row][col]);
}

async function paintCell(row, col) {
  if (running || !gridState) return;

  try {
    const response = await postJson("/api/set-terrain", {
      cells: gridState.cells,
      row,
      col,
      terrain: activeTerrain,
      rows: gridState.rows,
      cols: gridState.cols,
      start: gridState.start,
      end: gridState.end
    });

    gridState = await response.json();
    renderGrid();
  } catch (error) {
    addLog("blocked", "Paint error", getErrorMessage(error, "Could not update the cell."), "");
    setStatus("Update failed", "red");
  }
}

async function dispatch() {
  if (running || !gridState) return;

  running = true;
  setButtons(true);
  clearLog();
  resetStats();
  setStatus(`Connecting - ${selectedAlgorithmLabel()}`, "blue");
  logDotEl.classList.add("live");

  try {
    const response = await postJson("/api/run", {
      cells: gridState.cells,
      rows: gridState.rows,
      cols: gridState.cols,
      start: gridState.start,
      end: gridState.end,
      algorithm: selectedAlgorithm()
    });

    if (!response.body) {
      throw new Error("The server did not return a stream.");
    }

    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    let buffer = "";

    while (true) {
      const { done, value } = await reader.read();
      if (done) break;

      buffer += decoder.decode(value, { stream: true });
      const parts = buffer.split("\n\n");
      buffer = parts.pop() || "";

      for (const part of parts) {
        const eventMatch = part.match(/^event: (.+)$/m);
        const dataMatch = part.match(/^data: (.+)$/m);

        if (!eventMatch || !dataMatch) continue;

        try {
          handleEvent(eventMatch[1], JSON.parse(dataMatch[1]));
        } catch {
          addLog("blocked", "Stream error", "Received an invalid update from the server.", "");
        }
      }
    }
  } catch (error) {
    removeThinking();
    addLog("blocked", "Dispatch error", getErrorMessage(error, "Dispatch failed."), "");
    setStatus("Dispatch failed", "red");
  } finally {
    running = false;
    setButtons(false);
    logDotEl.classList.remove("live");
  }
}

function handleEvent(event, data) {
  switch (event) {
    case "status":
      setStatus(data.message, phaseColor(data.phase));
      break;

    case "thinking":
      addThinking(data.step);
      break;

    case "log":
      removeThinking();
      addLog(data.phase, data.step, data.message, data.trace);
      break;

    case "move": {
      const previousAgent = gridEl.querySelector(".cell.agent");

      if (previousAgent && gridState) {
        const previousRow = Number(previousAgent.dataset.r);
        const previousCol = Number(previousAgent.dataset.c);
        const previousState = gridState.cells[previousRow][previousCol].state;

        if (previousState !== "start") {
          gridState.cells[previousRow][previousCol].state = "path";
          gridState.cells[previousRow][previousCol].wall = false;
          applyCellClass(previousAgent, gridState.cells[previousRow][previousCol]);
        }
      }

      if (!gridState) break;

      const { row, col, step, total } = data;
      if (step < total) {
        gridState.cells[row][col].state = "agent";
        gridState.cells[row][col].wall = false;
        updateCell(row, col);
      }
      break;
    }

    case "traffic": {
      const div = gridEl.querySelector(`[data-r="${data.row}"][data-c="${data.col}"]`);
      if (div) {
        div.classList.toggle("green-light", !data.red);
        div.textContent = data.red ? "R" : "G";
      }
      break;
    }

    case "arrived":
      removeThinking();
      sSteps.textContent = String(data.steps);
      sDist.textContent = String(data.dist);
      sTime.textContent = `${data.elapsed}s`;
      addLog("arrived", "Target reached", `Arrived in ${data.steps} steps (${data.elapsed}s).`, data.trace);
      setStatus("Target reached", "green");
      break;

    case "blocked":
      removeThinking();
      addLog("blocked", "Route blocked", "No viable path. Obstacles form a full barrier.", data.reason);
      setStatus("Route blocked", "red");
      break;

    default:
      break;
  }
}

function addLog(phase, step, message, trace) {
  const entry = document.createElement("div");
  entry.className = "log-entry";

  const stepEl = document.createElement("div");
  stepEl.className = `log-step ${phase || "system"}`;
  stepEl.textContent = step || "Update";
  entry.appendChild(stepEl);

  if (message) {
    const messageEl = document.createElement("div");
    messageEl.className = "log-msg";
    messageEl.textContent = message;
    entry.appendChild(messageEl);
  }

  if (trace) {
    const traceEl = document.createElement("div");
    traceEl.className = "log-trace";
    traceEl.textContent = trace;
    entry.appendChild(traceEl);
  }

  logEl.appendChild(entry);
  logEl.scrollTop = logEl.scrollHeight;
}

function addThinking(step) {
  removeThinking();

  const thinking = document.createElement("div");
  thinking.className = "log-thinking";
  thinking.id = "thinking";

  const label = document.createElement("span");
  label.textContent = step || "Processing";

  const dots = document.createElement("span");
  dots.className = "thinking-dots";
  dots.textContent = "...";

  thinking.append(label, dots);
  logEl.appendChild(thinking);
  logEl.scrollTop = logEl.scrollHeight;
}

function removeThinking() {
  document.getElementById("thinking")?.remove();
}

function clearLog() {
  logEl.innerHTML = "";
}

function setStatus(text, color) {
  statusEl.textContent = text;
  statusEl.className = `status-pill ${color}`;
}

function phaseColor(phase) {
  return {
    planning: "blue",
    moving: "blue",
    arrived: "green",
    blocked: "red"
  }[phase] || "amber";
}

function resetStats() {
  sSteps.textContent = "-";
  sDist.textContent = "-";
  sTime.textContent = "-";
}

function setButtons(disabled) {
  btnDispatch.disabled = disabled;
  btnNew.disabled = disabled;
  btnReset.disabled = disabled;
  if (algorithmEl) {
    algorithmEl.disabled = disabled;
  }
}

btnDispatch.addEventListener("click", dispatch);
btnNew.addEventListener("click", () => {
  if (!running) {
    fetchNewGrid();
  }
});
btnReset.addEventListener("click", () => {
  if (!running) {
    fetchNewGrid();
  }
});

init();
