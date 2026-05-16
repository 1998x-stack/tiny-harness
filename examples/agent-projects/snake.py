#!/usr/bin/env python3
"""
Terminal Snake Game
===================
A self-contained curses-based Snake game with arrow keys, food, and score tracking.

Controls:
  Arrow keys / WASD  - Move the snake
  Q                  - Quit
  P                  - Pause/Resume
  R                  - Restart after game over

Author: AI Assistant
"""

import curses
import random
import time
from typing import List, Tuple, Set

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

SNAKE_HEAD_CHAR  = "O"
SNAKE_BODY_CHAR  = "o"
FOOD_CHAR        = "●"
WALL_CHAR        = "#"
EMPTY_CHAR       = " "

MIN_WIDTH  = 20
MIN_HEIGHT = 10

COLOR_SNAKE_HEAD = 1
COLOR_SNAKE_BODY = 2
COLOR_FOOD       = 3
COLOR_WALL       = 4
COLOR_TEXT       = 5
COLOR_GAMEOVER   = 6
COLOR_PAUSE      = 7

INITIAL_SPEED   = 0.15   # seconds per frame
SPEED_INCREMENT = 0.003  # speed increase per food eaten
MIN_SPEED       = 0.03   # fastest possible speed

# ---------------------------------------------------------------------------
# Snake Game Logic
# ---------------------------------------------------------------------------

class Point:
    """A simple 2D point with row, col coordinates."""
    __slots__ = ("r", "c")

    def __init__(self, r: int, c: int) -> None:
        self.r = r
        self.c = c

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, Point):
            return NotImplemented
        return self.r == other.r and self.c == other.c

    def __hash__(self) -> int:
        return hash((self.r, self.c))

    def __repr__(self) -> str:
        return f"({self.r},{self.c})"


DIRECTIONS = {
    curses.KEY_UP:    Point(-1, 0),
    curses.KEY_DOWN:  Point(1, 0),
    curses.KEY_LEFT:  Point(0, -1),
    curses.KEY_RIGHT: Point(0, 1),
    ord("w"):         Point(-1, 0),
    ord("W"):         Point(-1, 0),
    ord("s"):         Point(1, 0),
    ord("S"):         Point(1, 0),
    ord("a"):         Point(0, -1),
    ord("A"):         Point(0, -1),
    ord("d"):         Point(0, 1),
    ord("D"):         Point(0, 1),
}

OPPOSITES = {
    (0, 1):  (0, -1),
    (0, -1): (0, 1),
    (1, 0):  (-1, 0),
    (-1, 0): (1, 0),
}


class SnakeGame:
    """Holds all game state and logic."""

    def __init__(self, height: int, width: int) -> None:
        self.height = height
        self.width = width

        # Snake starts at the center of the playfield
        start_r = height // 2
        start_c = width // 2
        self.snake: List[Point] = [
            Point(start_r, start_c),
            Point(start_r, start_c - 1),
            Point(start_r, start_c - 2),
        ]
        self.direction = Point(0, 1)   # moving right
        self.next_direction = Point(0, 1)

        self.food: Point = self._place_food()

        self.score = 0
        self.speed = INITIAL_SPEED
        self.game_over = False
        self.paused = False
        self.won = False

    def _get_occupied(self) -> Set[Point]:
        """Return set of all cells occupied by the snake."""
        return set(self.snake)

    def _place_food(self) -> Point:
        """Place food on a random empty cell."""
        occupied = self._get_occupied()
        max_attempts = 2000
        for _ in range(max_attempts):
            r = random.randint(1, self.height - 2)
            c = random.randint(1, self.width - 2)
            p = Point(r, c)
            if p not in occupied:
                return p
        # If board is nearly full, scan linearly
        for r in range(1, self.height - 2):
            for c in range(1, self.width - 2):
                p = Point(r, c)
                if p not in occupied:
                    return p
        # Truly full — player wins!
        self.won = True
        return Point(0, 0)  # dummy

    def change_direction(self, new_dir: Point) -> None:
        """Queue a direction change (cannot reverse instantly)."""
        opp = OPPOSITES.get((self.direction.r, self.direction.c))
        if opp is not None and (new_dir.r, new_dir.c) == opp:
            return  # can't go backwards
        self.next_direction = new_dir

    def tick(self) -> bool:
        """
        Advance the game by one frame.
        Returns True if the game is still running, False if game over.
        """
        if self.game_over or self.paused or self.won:
            return False

        # Apply queued direction
        self.direction = self.next_direction

        # Calculate new head position
        head = self.snake[0]
        new_head = Point(head.r + self.direction.r, head.c + self.direction.c)

        # Check wall collision
        if (new_head.r <= 0 or new_head.r >= self.height - 1 or
                new_head.c <= 0 or new_head.c >= self.width - 1):
            self.game_over = True
            return False

        # Check self collision (except tail which will move away)
        tail = self.snake[-1]
        collidable = set(self.snake[:-1])  # exclude tail
        if new_head in collidable:
            self.game_over = True
            return False

        # Move: insert new head
        self.snake.insert(0, new_head)

        # Check food
        if new_head == self.food:
            self.score += 1
            self.speed = max(MIN_SPEED, self.speed - SPEED_INCREMENT)
            self.food = self._place_food()
            if self.won:
                return True
        else:
            # Remove tail
            self.snake.pop()

        return True

    def restart(self) -> None:
        """Reset the game to initial state."""
        self.__init__(self.height, self.width)


# ---------------------------------------------------------------------------
# Curses UI
# ---------------------------------------------------------------------------

def _draw_border(win, color_pair: int) -> None:
    """Draw the playfield border using wall characters."""
    h, w = win.getmaxyx()
    win.attron(curses.color_pair(color_pair))
    for c in range(w):
        win.addch(0, c, WALL_CHAR)
        win.addch(h - 1, c, WALL_CHAR)
    for r in range(h):
        win.addch(r, 0, WALL_CHAR)
        win.addch(r, w - 1, WALL_CHAR)
    win.attroff(curses.color_pair(color_pair))


def _draw_snake(win, snake: List[Point]) -> None:
    """Draw the snake on the playfield window."""
    for i, seg in enumerate(snake):
        if i == 0:
            win.attron(curses.color_pair(COLOR_SNAKE_HEAD) | curses.A_BOLD)
            win.addch(seg.r, seg.c, SNAKE_HEAD_CHAR)
            win.attroff(curses.color_pair(COLOR_SNAKE_HEAD) | curses.A_BOLD)
        else:
            win.attron(curses.color_pair(COLOR_SNAKE_BODY))
            win.addch(seg.r, seg.c, SNAKE_BODY_CHAR)
            win.attroff(curses.color_pair(COLOR_SNAKE_BODY))


def _draw_food(win, food: Point) -> None:
    """Draw the food item."""
    win.attron(curses.color_pair(COLOR_FOOD) | curses.A_BOLD)
    win.addch(food.r, food.c, FOOD_CHAR)
    win.attroff(curses.color_pair(COLOR_FOOD) | curses.A_BOLD)


def _show_game_over(stdscr, h: int, w: int, score: int) -> None:
    """Display the game-over overlay."""
    msg = f"  GAME OVER  Score: {score}  "
    # Center text
    r = h // 2
    c = (w - len(msg)) // 2
    stdscr.attron(curses.color_pair(COLOR_GAMEOVER) | curses.A_BOLD)
    stdscr.addstr(r, c, msg)
    stdscr.attroff(curses.color_pair(COLOR_GAMEOVER) | curses.A_BOLD)
    hint = "Press R to restart  |  Q to quit"
    stdscr.attron(curses.color_pair(COLOR_TEXT))
    stdscr.addstr(r + 2, (w - len(hint)) // 2, hint)
    stdscr.attroff(curses.color_pair(COLOR_TEXT))
    stdscr.refresh()


def _show_paused(stdscr, w: int) -> None:
    """Display the pause overlay."""
    msg = "  PAUSED  "
    r = 1
    c = (w - len(msg)) // 2
    stdscr.attron(curses.color_pair(COLOR_PAUSE) | curses.A_BOLD)
    stdscr.addstr(r, c, msg)
    stdscr.attroff(curses.color_pair(COLOR_PAUSE) | curses.A_BOLD)


def _show_win(stdscr, h: int, w: int, score: int) -> None:
    """Display the 'you win' overlay."""
    msg = f"  YOU WIN!  Score: {score}  "
    r = h // 2
    c = (w - len(msg)) // 2
    stdscr.attron(curses.color_pair(COLOR_GAMEOVER) | curses.A_BOLD)
    stdscr.addstr(r, c, msg)
    stdscr.attroff(curses.color_pair(COLOR_GAMEOVER) | curses.A_BOLD)
    hint = "Press R to play again  |  Q to quit"
    stdscr.attron(curses.color_pair(COLOR_TEXT))
    stdscr.addstr(r + 2, (w - len(hint)) // 2, hint)
    stdscr.attroff(curses.color_pair(COLOR_TEXT))
    stdscr.refresh()


def _draw_sidebar(sidebar, score: int, speed: float) -> None:
    """Update the side-bar with score and speed info."""
    sidebar.erase()
    h, w = sidebar.getmaxyx()
    sidebar.attron(curses.color_pair(COLOR_TEXT))
    sidebar.addstr(2, 2, "SNAKE")
    sidebar.addstr(4, 2, f"Score: {score}")
    sidebar.addstr(6, 2, f"Speed: {speed:.3f}s")
    sidebar.addstr(8, 2, "Controls:")
    sidebar.addstr(9, 2, "Arrows/WASD")
    sidebar.addstr(10, 2, "P = Pause")
    sidebar.addstr(11, 2, "R = Restart")
    sidebar.addstr(12, 2, "Q = Quit")
    sidebar.attroff(curses.color_pair(COLOR_TEXT))
    sidebar.border()
    sidebar.refresh()


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main(stdscr) -> None:
    """Main curses entry point."""

    # --- Terminal setup ---
    curses.curs_set(0)               # hide cursor
    stdscr.nodelay(1)                # non-blocking getch
    stdscr.timeout(50)               # poll every 50ms
    curses.use_default_colors()

    # Color pairs
    curses.init_pair(COLOR_SNAKE_HEAD, curses.COLOR_GREEN, -1)
    curses.init_pair(COLOR_SNAKE_BODY, curses.COLOR_YELLOW, -1)
    curses.init_pair(COLOR_FOOD, curses.COLOR_RED, -1)
    curses.init_pair(COLOR_WALL, curses.COLOR_CYAN, -1)
    curses.init_pair(COLOR_TEXT, curses.COLOR_WHITE, -1)
    curses.init_pair(COLOR_GAMEOVER, curses.COLOR_RED, -1)
    curses.init_pair(COLOR_PAUSE, curses.COLOR_MAGENTA, -1)

    # --- Layout ---
    max_y, max_x = stdscr.getmaxyx()
    if max_y < MIN_HEIGHT or max_x < MIN_WIDTH:
        stdscr.addstr(0, 0, f"Terminal too small. Need at least {MIN_WIDTH}x{MIN_HEIGHT}.")
        stdscr.refresh()
        stdscr.getch()
        return

    # Playfield dimensions
    play_h = max_y
    play_w = max_x - 16 if max_x > 50 else max_x - 4
    if play_w < MIN_WIDTH:
        play_w = max_x - 4
    if play_w < MIN_WIDTH:
        play_w = max_x

    sidebar_w = max_x - play_w

    # Create windows
    play_win = curses.newwin(play_h, play_w, 0, 0)
    if sidebar_w > 2:
        sidebar = curses.newwin(play_h, sidebar_w, 0, play_w)
    else:
        sidebar = None

    # --- Game loop ---
    game = SnakeGame(play_h, play_w)

    while True:
        # --- Input ---
        key = stdscr.getch()

        if key == ord("q") or key == ord("Q"):
            break

        if key == ord("r") or key == ord("R"):
            if game.game_over or game.won:
                game.restart()
            continue

        if key == ord("p") or key == ord("P"):
            game.paused = not game.paused
            if game.paused:
                _show_paused(play_win, play_w)
            continue

        # Direction change (only if not game over)
        if not game.game_over and not game.won and key in DIRECTIONS:
            game.change_direction(DIRECTIONS[key])

        # --- Update ---
        if not game.game_over and not game.won and not game.paused:
            game.tick()

        # --- Draw ---
        play_win.erase()

        # Border
        _draw_border(play_win, COLOR_WALL)

        if not game.game_over and not game.won:
            # Snake and food
            _draw_snake(play_win, game.snake)
            _draw_food(play_win, game.food)
        elif game.won:
            _draw_snake(play_win, game.snake)
            _draw_food(play_win, game.food)
            _show_win(play_win, play_h, play_w, game.score)
        else:
            # Draw snake where it died (frozen)
            _draw_snake(play_win, game.snake)
            _draw_food(play_win, game.food)
            _show_game_over(play_win, play_h, play_w, game.score)

        play_win.refresh()

        # Sidebar
        if sidebar is not None:
            _draw_sidebar(sidebar, game.score, game.speed)

        # --- Framerate throttle ---
        if not game.game_over and not game.won and not game.paused:
            time.sleep(game.speed)


def run() -> None:
    """Entry point that wraps curses."""
    curses.wrapper(main)


if __name__ == "__main__":
    run()
