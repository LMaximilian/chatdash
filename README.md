# ChatDash 1.2

A single-button, neon rhythm platformer built with Python and Pygame.

## Run

```bash
python3 -m pip install pygame
python3 chatdash.py
```

## Controls

- `Space`, `Up`, or left click: jump, flap, flip gravity, teleport, or fly
- Arrow keys / `A` and `D`: navigate the level selector
- `Enter` or `Space`: start the selected level
- `P`: pause
- `R`: restart
- `M`: mute
- `Esc`: back from level selection or quit

## Version 1.2 highlights

- Eight player modes and eight validated levels
- Adaptive rock soundtrack and event-synchronized effects
- Collectible stars, interactive orbs, portals, moving hazards, and chompers
- Reactive security system and complete death summaries
- Clickable level selector and direct back-to-levels navigation
- Persistent first-run Sign In, guided Instructions, and Personalization
- Global confirmed Reset button that clears all local player data
- Cached fonts/backgrounds, bounded effects, and graceful shutdown

## Test

```bash
python3 -m unittest -v test_chatdash.py
```

The suite contains four test platforms:

1. Data and level-fairness validation
2. Player physics and collision validation
3. UI and state-flow integration tests
4. Multi-FPS endurance simulations at 30, 60, and 120 FPS
