# Emergency Response Agent

Small FastAPI + HTML/JS app that visualizes grid-based emergency routing with multiple search algorithms.

## What it does

- Generates a grid map with start and target points
- Lets you paint terrain such as walls, slow zones, traffic, and one-way cells
- Runs pathfinding with `BFS`, `DFS`, `A*`, or `UCS`
- Streams the responder movement and reasoning log in the browser
- Uses local reasoning only, so no external API key is required

## Project files

- `main.py` - FastAPI server and API routes
- `app.js` - frontend logic
- `style.css` - page styling
- `grid.py` - grid model and terrain rules
- `pathfinder.py` - search algorithms
- `reasoning.py` - local reasoning text generation

## Requirements

- Python 3
- `pip`

Install dependencies:

```powershell
pip install -r requirements.txt
```

## Recommended setup on Windows

Create and activate a virtual environment:

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

## How to run

Start the backend server:

```powershell
python main.py
```

Then open this in your browser:

```text
http://localhost:8000
```

## Development mode

For auto-reload while editing:

```powershell
python main.py --reload
```

## How to use the app

1. Open the page in the browser.
2. Choose a terrain type from the toolbar.
3. Click cells on the grid to paint obstacles or terrain.
4. Pick an algorithm from the dropdown.
5. Click `Dispatch` to run the route simulation.
6. Use `New Map` to generate a fresh grid.
7. Use `Reset` to reload the grid again.

## Important note

Do not rely on opening `index.html` directly from the file system if you want full functionality. The app is meant to run through the FastAPI server so the API endpoints work correctly.

If the backend is not running, the page may still show a local preview grid, but live dispatch and backend-driven updates will not work.

## Troubleshooting

If the page does not load:

- Make sure the server is running with `python main.py`
- Check that `http://localhost:8000` opens in the browser
- If port `8000` is busy, run:

```powershell
python main.py --port 8010
```

Then open:

```text
http://localhost:8010
```

If dependencies fail to install, upgrade `pip` first:

```powershell
python -m pip install --upgrade pip
pip install -r requirements.txt
```
