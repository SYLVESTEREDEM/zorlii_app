import secrets
import time


GAMES = {
    "tile-quest": {"name": "Tile Quest", "description": "Slide and merge matching tiles to build your score."},
    "summit-steps": {"name": "Summit Steps", "description": "Choose a reachable hold and climb as high as you can."},
    "quick-math": {"name": "Quick Math", "description": "Solve ten arithmetic problems."},
    "word-scramble": {"name": "Word Scramble", "description": "Unscramble ten words."},
    "odd-one-out": {"name": "Odd One Out", "description": "Find the item that does not belong."},
    "number-pattern": {"name": "Number Pattern", "description": "Find the next number in each sequence."},
    "color-match": {"name": "Color Match", "description": "Match each color to its hex code."},
}

QUIZ_GAMES = {"quick-math", "word-scramble", "odd-one-out", "number-pattern", "color-match"}


def _quiz_question(game):
    if game == "quick-math":
        a, b = secrets.randbelow(19) + 1, secrets.randbelow(19) + 1
        answer = str(a + b)
        prompt = f"What is {a} + {b}?"
        options = [answer, str(a + b + 1), str(a + b + 2), str(a + b + 3)]
    elif game == "word-scramble":
        words = [("planet", "tanelp"), ("garden", "dengar"), ("rocket", "tekcor"),
                 ("castle", "tsalec"), ("puzzle", "zzulep"), ("silver", "versil")]
        answer, scrambled = secrets.choice(words)
        prompt = f"Unscramble: {scrambled}"
        options = [answer] + [word for word, _ in words if word != answer][:3]
    elif game == "odd-one-out":
        group, answer = secrets.choice([
            (["apple", "pear", "plum"], "carrot"),
            (["eagle", "sparrow", "owl"], "dolphin"),
            (["violin", "guitar", "harp"], "trumpet"),
            (["circle", "square", "triangle"], "cube"),
        ])
        prompt = "Which item does not belong?"
        options = group + [answer]
    elif game == "number-pattern":
        first, step = secrets.randbelow(10) + 1, secrets.randbelow(5) + 2
        answer = str(first + 3 * step)
        prompt = f"What comes next: {first}, {first + step}, {first + 2 * step}?"
        options = [answer, str(first + 3 * step + 1), str(first + 3 * step + 2), str(first + 3 * step + 3)]
    else:
        colors = [("red", "#FF0000"), ("green", "#00FF00"), ("blue", "#0000FF"),
                  ("yellow", "#FFFF00"), ("magenta", "#FF00FF"), ("cyan", "#00FFFF")]
        name, answer = secrets.choice(colors)
        prompt = f"Which hex code represents {name}?"
        options = [answer] + [code for _, code in colors if code != answer][:3]
    secrets.SystemRandom().shuffle(options)
    choices = [{"id": str(i), "label": option} for i, option in enumerate(options)]
    return {"prompt": prompt, "choices": choices, "_answer": str(options.index(answer))}


def public_state(state):
    return {key: value for key, value in state.items() if not key.startswith("_")}


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
    if game in QUIZ_GAMES:
        return {**_quiz_question(game), "round": 1, "total_rounds": 10, "score": 0, "over": False}
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
    if game in QUIZ_GAMES:
        if action not in {choice["id"] for choice in state["choices"]}:
            raise ValueError("Choose one of the available answers.")
        correct = action == state["_answer"]
        score = state["score"] + (10 if correct else 0)
        if state["round"] == state["total_rounds"]:
            return {"prompt": "", "choices": [], "round": state["round"], "total_rounds": state["total_rounds"],
                    "score": score, "over": True, "correct": correct}
        return {**_quiz_question(game), "round": state["round"] + 1, "total_rounds": state["total_rounds"],
                "score": score, "over": False, "correct": correct}
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
