#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Лила (Leela) — движок игры самопознания.

Агент-ведущий вызывает этот скрипт, а не считает ходы в уме: скрипт кидает кубик,
двигает фишку, применяет правило шестёрок, стрелы и змеи, следит за целью (клетка 68)
и хранит состояние сессии в файле — поэтому партия переживает перезапуск агента.

Данные доски (72 клетки, 9 стрел, 10 змей) — в board.json рядом со скриптом.
Канон: Хариш Джохари, «Лила. Игра самопознания».

Команды:
  new       [--intention "запрос игрока"] [--player Имя] [--state PATH]
  roll      [--die N] [--state PATH]      # сделать ход (N — подсунуть значение кубика 1..6)
  status    [--state PATH]
  board     N                              # описание клетки N
  history   [--state PATH]
  reset     [--state PATH]                 # удалить сессию

Состояние по умолчанию: ~/.leela/session.json  (или $LEELA_STATE, или --state).
Вывод — по-русски, человекочитаемый; ведущий пересказывает и трактует его игроку.
"""
import argparse
import json
import os
import random
import sys
from datetime import datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
BOARD_PATH = os.path.join(HERE, "board.json")


def load_board():
    with open(BOARD_PATH, encoding="utf-8") as f:
        return json.load(f)


BOARD = load_board()
ARROWS = {int(k): v for k, v in BOARD["arrows"].items()}
SNAKES = {int(k): v for k, v in BOARD["snakes"].items()}
CELLS = BOARD["cells"]
GOAL = BOARD["meta"]["goal_cell"]  # 68


def cell_str(n):
    c = CELLS.get(str(n))
    if not c:
        return f"клетка {n}"
    return f"{n} — {c['name']} ({c['sanskrit']})"


def cell_full(n):
    c = CELLS.get(str(n))
    if not c:
        return f"клетка {n}"
    row = BOARD["rows"][str(c["row"])]
    tag = {"vice": "змея/порок", "virtue": "добродетель (стрела)", "plane": "план",
           "energy": "гуна", "goal": "ЦЕЛЬ"}.get(c["type"], c["type"])
    up = ARROWS.get(n)
    down = SNAKES.get(n)
    lines = [
        f"Клетка {n} — {c['name']} ({c['sanskrit']})",
        f"  Ряд {c['row']}: {row['title']} · чакра {row['chakra']}",
        f"  Тип: {tag}",
        f"  {c['essence']}",
    ]
    if up:
        lines.append(f"  ▲ Стрела: возносит на клетку {up} — {CELLS[str(up)]['name']}.")
    if down:
        lines.append(f"  ▼ Змея: низводит на клетку {down} — {CELLS[str(down)]['name']}.")
    return "\n".join(lines)


# ---------- состояние ----------

def state_path(args):
    if getattr(args, "state", None):
        return args.state
    env = os.environ.get("LEELA_STATE")
    if env:
        return env
    return os.path.join(os.path.expanduser("~"), ".leela", "session.json")


def load_state(path):
    if not os.path.exists(path):
        return None
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def save_state(path, st):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(st, f, ensure_ascii=False, indent=2)


def now_iso():
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


# ---------- механика ----------

def roll_die(forced=None):
    if forced is not None:
        return int(forced)
    return random.randint(1, 6)


def resolve_landing(pos):
    """Применить стрелу/змею на клетке приземления. Вернуть (итог, вид, откуда, куда)."""
    if pos in ARROWS:
        return ARROWS[pos], "arrow", pos, ARROWS[pos]
    if pos in SNAKES:
        return SNAKES[pos], "snake", pos, SNAKES[pos]
    return pos, None, None, None


def do_turn(st, dice=None):
    """Один полный ход (с учётом повторных бросков на шестёрку). Меняет st, возвращает лог-строки.

    dice=None  -> цифровой кубик: движок кидает сам, докидывая на каждой шестёрке.
    dice=[...] -> физический кубик: игрок ввёл реальную серию бросков; последний должен быть != 6.
    """
    log = []
    born = st["born"]
    pos = st["pos"]

    # серия бросков: копим шестёрки
    if dice is not None:
        rolls = list(dice)
    else:
        rolls = []
        while True:
            d = roll_die()
            rolls.append(d)
            if d == 6:
                continue
            break
    x = rolls[-1]                      # последний бросок (не 6)
    k = len(rolls) - 1                 # сколько шестёрок подряд в начале
    rolls_txt = "+".join(str(r) for r in rolls)
    log.append(f"Бросок: {rolls_txt}" + (f"  ({k}×6, затем {x})" if k else ""))

    # --- вход в игру (нерождённый) ---
    if not born:
        if k == 0:
            log.append(f"Выпало {x}, а не 6 — войти в игру нельзя. Игрок ждёт нерождённым "
                       f"на клетке 68 (Космическое Сознание).")
            st["turns"] += 1
            st["last_roll"] = rolls
            return log, False
        # родились на клетке 1
        st["born"] = True
        if k == 3:  # три шестёрки сгорают — рождение как первый шаг, идём x клеток
            final = x
            log.append(f"Три шестёрки при входе сгорают. Рождение (клетка 1) — первый шаг, "
                       f"идём на {x}.")
        else:
            final = 1 + 6 * (k - 1) + x
            log.append(f"Рождение! Игрок входит на клетку 1 и движется дальше.")
        return _finish_move(st, 1 if k != 3 else 1, final, log)

    # --- обычный ход ---
    base = pos
    if k == 3:
        final = base + x
        log.append(f"Три шестёрки сгорают — игрок возвращается на клетку {base} и идёт на {x}.")
    else:
        steps = 6 * k + x
        final = base + steps
        if k >= 4:
            log.append(f"Четыре и более шестёрок не сгорают — суммарно {steps} шагов.")
    return _finish_move(st, base, final, log)


def _finish_move(st, base, final, log):
    """Обработать перелёты у вершины, стрелы/змеи, победу."""
    # перелёт за пределы доски
    if final > 72:
        log.append(f"С клетки {base} выпавшее число уводит за клетку 72 — ход невозможен, "
                   f"игрок остаётся на месте (нужно точное число).")
        st["turns"] += 1
        return log, False

    # застревание в 8-м ряду выше цели
    if final in (69, 70, 71):
        st["pos"] = final
        st["turns"] += 1
        log.append(f"Игрок проходит мимо цели и встаёт на {cell_str(final)}. "
                   f"Отсюда к клетке 68 напрямую уже не попасть — только вперёд на клетку 72, "
                   f"откуда змея Тамо-гуны вернёт на землю (клетка 51). "
                   f"Полезны только числа, ведущие ровно на 72 или на один-два шага вперёд.")
        return log, False

    # приземление
    log.append(f"Приземление: {cell_str(final)}.")
    result, kind, frm, to = resolve_landing(final)
    if kind == "arrow":
        log.append(f"  ▲ Стрела! {CELLS[str(frm)]['name']} возносит на {cell_str(to)}.")
    elif kind == "snake":
        log.append(f"  ▼ Змея! {CELLS[str(frm)]['name']} низводит на {cell_str(to)}.")

    st["pos"] = result
    st["turns"] += 1

    if result == GOAL:
        st["won"] = True
        log.append(f"★ Игрок точно на клетке 68 — Космическое Сознание. Игра завершена. "
                   f"Цель достигнута.")
    return log, (result == GOAL)


# ---------- команды ----------

def cmd_new(args):
    path = state_path(args)
    st = {
        "player": args.player or "Игрок",
        "intention": args.intention or "",
        "born": False,
        "pos": 68,          # нерождённый ждёт на 68
        "won": False,
        "turns": 0,
        "started": now_iso(),
        "last_roll": None,
        "log": [],
    }
    save_state(path, st)
    out = ["Новая партия Лилы создана.",
           f"Игрок: {st['player']}",
           (f"Запрос/намерение: {st['intention']}" if st['intention'] else
            "Намерение не задано — предложи игроку сформулировать запрос перед первым броском."),
           "",
           "Игрок стоит нерождённым на клетке 68 (Космическое Сознание).",
           "Чтобы войти в воплощение, нужно выбросить 6. Команда: roll"]
    print("\n".join(out))


def _require(st, path):
    if st is None:
        print(f"Активной партии нет (файл {path} не найден). Создай: new --intention \"...\"")
        sys.exit(2)


def cmd_roll(args):
    path = state_path(args)
    st = load_state(path)
    _require(st, path)
    if st.get("won"):
        print("Партия уже завершена — игрок достиг клетки 68. Начни новую: new")
        return
    dice = None
    raw = args.dice if args.dice is not None else (str(args.die) if args.die is not None else None)
    if raw is not None:
        try:
            dice = [int(x) for x in str(raw).replace(" ", "").split(",") if x != ""]
        except ValueError:
            print("Значения кубика должны быть числами, напр. --dice 6,6,5")
            sys.exit(2)
        if not dice or any(not (1 <= d <= 6) for d in dice):
            print("Каждое значение кубика — 1..6. Пример: --dice 6,5")
            sys.exit(2)
        if dice[-1] == 6:
            print("Последний бросок серии — 6, значит нужен ещё бросок (шестёрка даёт право "
                  "бросить снова). Введи полную серию, напр. --dice 6,3")
            sys.exit(2)
    log, won = do_turn(st, dice=dice)
    st.setdefault("log", []).append({"t": now_iso(), "lines": log})
    save_state(path, st)
    print("\n".join(log))
    print("")
    print(status_line(st))


def status_line(st):
    if not st["born"]:
        return "Статус: нерождён, ждёт на клетке 68. Нужна шестёрка для входа. Ходов: %d" % st["turns"]
    pos = st["pos"]
    c = CELLS[str(pos)]
    extra = " · ПОБЕДА" if st.get("won") else ""
    return f"Статус: клетка {pos} — {c['name']} ({c['sanskrit']}). Ходов: {st['turns']}{extra}"


def cmd_status(args):
    path = state_path(args)
    st = load_state(path)
    _require(st, path)
    print(f"Игрок: {st['player']}")
    if st.get("intention"):
        print(f"Запрос: {st['intention']}")
    print(f"Начата: {st['started']}")
    print(status_line(st))
    if st["born"] and not st.get("won"):
        print("")
        print(cell_full(st["pos"]))


def cmd_board(args):
    n = int(args.cell)
    if not (1 <= n <= 72):
        print("Клетка должна быть 1..72")
        sys.exit(2)
    print(cell_full(n))


def cmd_history(args):
    path = state_path(args)
    st = load_state(path)
    _require(st, path)
    log = st.get("log", [])
    if not log:
        print("Ходов ещё не было.")
        return
    for i, entry in enumerate(log, 1):
        print(f"— Ход {i} ({entry['t']}):")
        for line in entry["lines"]:
            print(f"    {line}")


def cmd_reset(args):
    path = state_path(args)
    if os.path.exists(path):
        os.remove(path)
        print(f"Сессия удалена ({path}).")
    else:
        print("Активной сессии не было.")


def main():
    p = argparse.ArgumentParser(description="Лила — движок игры самопознания")
    sub = p.add_subparsers(dest="cmd", required=True)

    pn = sub.add_parser("new", help="начать новую партию")
    pn.add_argument("--intention", help="запрос/намерение игрока")
    pn.add_argument("--player", help="имя игрока")
    pn.add_argument("--state", help="путь к файлу сессии")
    pn.set_defaults(func=cmd_new)

    pr = sub.add_parser("roll", help="сделать ход")
    pr.add_argument("--dice", help="серия реальных бросков через запятую, напр. 6,6,5 (физический кубик)")
    pr.add_argument("--die", type=int, help="одно значение кубика 1..6 (то же, что --dice N)")
    pr.add_argument("--state", help="путь к файлу сессии")
    pr.set_defaults(func=cmd_roll)

    ps = sub.add_parser("status", help="текущее состояние")
    ps.add_argument("--state", help="путь к файлу сессии")
    ps.set_defaults(func=cmd_status)

    pb = sub.add_parser("board", help="описание клетки")
    pb.add_argument("cell", help="номер клетки 1..72")
    pb.set_defaults(func=cmd_board)

    ph = sub.add_parser("history", help="история ходов")
    ph.add_argument("--state", help="путь к файлу сессии")
    ph.set_defaults(func=cmd_history)

    prs = sub.add_parser("reset", help="удалить сессию")
    prs.add_argument("--state", help="путь к файлу сессии")
    prs.set_defaults(func=cmd_reset)

    args = p.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
