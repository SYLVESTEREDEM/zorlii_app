import secrets
import time


GAMES = {
    "tile-quest": {"name": "Tile Quest", "description": "Slide and merge matching tiles to build your score."},
    "summit-steps": {"name": "Summit Steps", "description": "Choose a reachable hold and climb as high as you can."},
}


def _add_tile(board):
    empty = [(r, c) for r in range(4) for c in range(4) if not board[r][c]]
    if empty:
        r, c = secrets.choice(empty)
        board[r][c] = 4 if secrets.randbelow(10) == 0 else 2


def _can_slide(board):
    return any(not board[r][c] or
               (r < 3 and board[r][c] == board[r + 1][c]) or
               (c < 3 and board[r][c] == board[r][c + 1])
               for r in range(4) for c in range(4))


def _holds(current_lane):
    reachable = [lane for lane in range(3) if abs(lane - current_lane) <= 1]
    required = secrets.choice(reachable)
    return [lane for lane in range(3) if lane == required or secrets.randbelow(2)]


def start(game):
    if game == "tile-quest":
        board = [[0] * 4 for _ in range(4)]
        _add_tile(board)
        _add_tile(board)
        return {"board": board, "score": 0, "over": False}
    if game == "summit-steps":
        return {"lane": 1, "holds": _holds(1), "score": 0, "over": False, "deadline": time.time() + 12}
    raise ValueError("Unknown game.")


def move(game, state, action):
    if state["over"]:
        raise ValueError("This game has ended. Start a new game.")
    if game == "tile-quest":
        if action not in ("left", "right", "up", "down"):
            raise ValueError("Choose a direction.")
        board = state["board"]
        updated = [[0] * 4 for _ in range(4)]
        score = state["score"]
        for i in range(4):
            coordinates = (
                [(i, j) for j in range(4)] if action == "left" else
                [(i, j) for j in range(3, -1, -1)] if action == "right" else
                [(j, i) for j in range(4)] if action == "up" else
                [(j, i) for j in range(3, -1, -1)]
            )
            values = [board[r][c] for r, c in coordinates if board[r][c]]
            merged = []
            while values:
                value = values.pop(0)
                if values and values[0] == value:
                    value *= 2
                    values.pop(0)
                    score += value
                merged.append(value)
            for (r, c), value in zip(coordinates, merged):
                updated[r][c] = value
        if updated == board:
            raise ValueError("The tiles cannot move in that direction.")
        _add_tile(updated)
        return {"board": updated, "score": score, "over": not _can_slide(updated)}
    if game == "summit-steps":
        if action not in ("left", "center", "right"):
            raise ValueError("Choose a hold.")
        lane = ("left", "center", "right").index(action)
        if time.time() > state["deadline"] or lane not in state["holds"] or abs(lane - state["lane"]) > 1:
            return {**state, "over": True}
        score = state["score"] + 10
        return {"lane": lane, "holds": _holds(lane), "score": score,
                "over": False, "deadline": time.time() + 12}
    raise ValueError("Unknown game.")
