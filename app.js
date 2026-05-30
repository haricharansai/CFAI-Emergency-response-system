const DEFAULT_GRID = {
  rows: 8,
  cols: 10,
  start: [3, 0],
  end: [4, 9],
  density: 0.2
};
const API_REQUEST_TIMEOUT_MS = 3500;
const FALLBACK_API_ORIGINS = [
  "http://127.0.0.1:8000",
  "http://localhost:8000",
  "http://127.0.0.1:8010",
  "http://localhost:8010"
];

let gridState = null;
let running = false;
let activeTerrain = "wall";
let apiBase = null;

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
  if (isConnectivityError(error) && error?.name === "AbortError") {
    return "The API took too long to respond. Start the backend server and reload the page.";
  }

  if (isConnectivityError(error)) {
    return "Could not reach the API. Start the backend server and reload the page.";
  }

  if (error && typeof error.message === "string" && error.message.trim()) {
    return error.message;
  }

  return fallbackMessage;
}

function isConnectivityError(error) {
  return error instanceof TypeError || error?.name === "AbortError";
}

function buildApiCandidates() {
  const candidates = [];

  if (window.location.protocol.startsWith("http")) {
    candidates.push(window.location.origin);
  }

  candidates.push(...FALLBACK_API_ORIGINS);

  return [...new Set(candidates)].map((base) => base.replace(/\/$/, ""));
}

function requestTargets(allowFallbackOrigins) {
  const targets = [];

  if (apiBase !== null) {
    targets.push(apiBase);
  }

  if (allowFallbackOrigins) {
    targets.push(...buildApiCandidates());
  }

  if (!targets.length) {
    targets.push("");
  }

  return [...new Set(targets)];
}

async function fetchWithTimeout(url, options) {
  const controller = new AbortController();
  const timeoutId = window.setTimeout(() => controller.abort(), API_REQUEST_TIMEOUT_MS);

  try {
    return await fetch(url, { ...options, signal: controller.signal });
  } finally {
    window.clearTimeout(timeoutId);
  }
}

function makeCell(row, col, state = "empty") {
  return {
    row,
    col,
    state,
    wall: state === "wall"
  };
}

function buildLocalGrid(config = DEFAULT_GRID) {
  const rows = config.rows ?? DEFAULT_GRID.rows;
  const cols = config.cols ?? DEFAULT_GRID.cols;
  const start = [...(config.start ?? DEFAULT_GRID.start)];
  const end = [...(config.end ?? DEFAULT_GRID.end)];
  const density = config.density ?? DEFAULT_GRID.density;
  const terrainPool = ["wall", "wall", "wall", "slow", "traffic", "oneway_e", "oneway_s"];
  const cells = Array.from({ length: rows }, (_, row) =>
    Array.from({ length: cols }, (_, col) => makeCell(row, col))
  );

  for (let row = 0; row < rows; row += 1) {
    for (let col = 0; col < cols; col += 1) {
      const isStart = row === start[0] && col === start[1];
      const isEnd = row === end[0] && col === end[1];

      if (isStart) {
        cells[row][col] = makeCell(row, col, "start");
        continue;
      }

      if (isEnd) {
        cells[row][col] = makeCell(row, col, "end");
        continue;
      }

      if (Math.random() < density) {
        const state = terrainPool[Math.floor(Math.random() * terrainPool.length)];
        cells[row][col] = makeCell(row, col, state);
      }
    }
  }

  return { rows, cols, start, end, cells };
}

function renderPreviewGrid() {
  gridState = buildLocalGrid(DEFAULT_GRID);
  renderGrid();
  resetStats();
  clearLog();
  addLog(
    "system",
    "Preview loaded",
    "Showing a local preview grid while the backend map initializes.",
    ""
  );
  setStatus("Loading map", "blue");
}

function paintCellLocally(row, col) {
  if (!gridState) return;

  const cell = gridState.cells[row][col];
  if (!cell || cell.state === "start" || cell.state === "end") {
    return;
  }

  if (cell.state === activeTerrain) {
    cell.state = "empty";
    cell.wall = false;
  } else {
    cell.state = activeTerrain;
    cell.wall = activeTerrain === "wall";
  }

  renderGrid();
}

async function postJson(path, payload, { allowFallbackOrigins = true } = {}) {
  let lastError = new TypeError("Could not reach the API.");

  for (const base of requestTargets(allowFallbackOrigins)) {
    try {
      const response = await fetchWithTimeout(`${base}${path}`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload)
      });

      if (!response.ok) {
        lastError = new Error(`Request failed (${response.status})`);
        continue;
      }

      apiBase = base;
      return response;
    } catch (error) {
      lastError = error;
    }
  }

  throw lastError;
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

function init() {
  renderPreviewGrid();
  void fetchNewGrid();
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
    if (!gridState) {
      gridState = buildLocalGrid(DEFAULT_GRID);
    }

    renderGrid();
    resetStats();
    clearLog();
    addLog(
      "blocked",
      "Preview mode",
      `${getErrorMessage(error, "Could not load the map.")} Showing a local preview grid instead.`,
      "Start the FastAPI server to enable dispatch and backend-driven updates."
    );
    setStatus("Preview mode", "amber");
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
    if (isConnectivityError(error)) {
      paintCellLocally(row, col);
      setStatus("Preview mode", "amber");
      return;
    }

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
