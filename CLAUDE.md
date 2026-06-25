I'm porting an existing rain garden calculator from a Python/Hex notebook into
a clean Python project. Read CLAUDE.md for full context and decisions.

Files in the repo:
- notebooks/DIY_Rain_Garden_Calculator_20260624.yaml  (source of truth for all logic)
- data/usda-plants_8-1-2023.csv  (plant data)

For this first session, do ONLY this:
1. Set up the project: virtual environment, dependency file, pytest,
   python-dotenv, a .gitignore that ignores .env, and a .env.example listing
   RAPIDAPI_KEY and ANTHROPIC_API_KEY with no values.
2. Read the sizing logic in the notebook — the cells computing sizing factor,
   rain garden area, dimensions, depth, plant counts, drainage time, and
   gallons diverted. Port ONLY that into src/rain_garden/sizing.py as clean,
   documented pure functions: no Hex/notebook dependencies, no global state.
3. Write pytest tests that feed the example inputs the notebook uses
   (e.g. 700 sq ft catchment, silty soil, >30 ft from foundation) and assert
   the outputs match the notebook's numbers.

Stop after sizing.py and its tests pass. Show me the results before touching
plants, precipitation, geocoding, or hardiness. Do not write any AI, API, or
frontend code.