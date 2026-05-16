#!/usr/bin/env python3
"""
Terminal Ping Pong Game
=======================
Two-player: Left player uses W/S, Right player uses Arrow keys.
First to 5 points wins. Uses curses for terminal rendering.

Controls:
  Left player:  W (up), S (down)
  Right player: UP arrow (up), DOWN arrow (down)
  Q or ESC:     Quit
  SPACE:        Start game / Serve
"""

import curses
import time
import sys

# ─── Constants ───────────────────────────────────────────────────────────────

WINNING_SCORE = 5
PADDLE_HEIGHT = 3
PADDLE_CHAR = "█"
BALL_CHAR = "O"
WALL_CHAR = "▒"
TIMESTEP = 0.04  # seconds per game tick

# Colours (curses colour pairs)
COLOR_P1 = 1
COLOR_P2 = 2
COLOR_BALL = 3
COLOR_WALL = 4
COLOR_TEXT = 5

# ─── Game State ──────────────────────────────────────────────────────────────


class Paddle:
    def __init__(self, x, y_top):
        self.x = x
        self.y_top = y_top
        self.height = PADDLE_HEIGHT

    @property
    def y_bot(self):
        return self.y_top + self.height - 1

    def move_up(self, min_y):
        if self.y_top > min_y + 1:
            self.y_top -= 1

    def move_down(self, max_y):
        if self.y_bot < max_y - 1:
            self.y_top += 1

    def contains(self, y):
        return self.y_top <= y <= self.y_bot


class Ball:
    def __init__(self, x, y, dx, dy):
        self.x = x
        self.y = y
        self.dx = dx
        self.dy = dy

    def move(self):
        self.x += self.dx
        self.y += self.dy


class Game:
    def __init__(self, height, width):
        self.height = height
        self.width = width
        self.p1 = Paddle(2, height // 2 - PADDLE_HEIGHT // 2)
        self.p2 = Paddle(width - 3, height // 2 - PADDLE_HEIGHT // 2)
        self.ball = Ball(width // 2, height // 2, 0, 0)
        self.score_p1 = 0
        self.score_p2 = 0
        self.state = "serve"  # "serve" | "play" | "point" | "done"
        self.winner = None
        self.serving_player = 1  # 1 or 2, who lost last point
        self.rally_count = 0

    def recenter_ball(self, toward_player):
        """Place ball at centre and set it moving toward 'toward_player' (1 or 2)."""
        self.ball.x = self.width // 2
        self.ball.y = self.height // 2
        dx = 1 if toward_player == 2 else -1
        import random
        dy = random.choice([-1, 1])
        self.ball.dx = dx
        self.ball.dy = dy

    def serve(self):
        self.state = "play"
        self.rally_count = 0
        self.recenter_ball(toward_player=self.serving_player)

    def update(self):
        if self.state != "play":
            return

        self.ball.move()
        self.rally_count += 1

        # Wall bounces (top / bottom)
        if self.ball.y <= 1 or self.ball.y >= self.height - 2:
            self.ball.dy *= -1
            # Nudge back inside to avoid sticking
            if self.ball.y <= 1:
                self.ball.y = 2
            else:
                self.ball.y = self.height - 3

        # Paddle collisions
        # Left paddle
        if self.ball.x == self.p1.x + 1 and self.ball.dx < 0:
            if self.p1.contains(self.ball.y):
                self.ball.dx *= -1
                # Slight angle change based on where ball hits paddle
                mid = (self.p1.y_top + self.p1.y_bot) // 2
                diff = self.ball.y - mid
                if diff != 0:
                    self.ball.dy = 1 if diff > 0 else -1
                self.ball.x = self.p1.x + 2  # push past paddle
            elif self.ball.x <= 1:
                self._point_for(2)

        # Right paddle
        elif self.ball.x == self.p2.x - 1 and self.ball.dx > 0:
            if self.p2.contains(self.ball.y):
                self.ball.dx *= -1
                mid = (self.p2.y_top + self.p2.y_bot) // 2
                diff = self.ball.y - mid
                if diff != 0:
                    self.ball.dy = 1 if diff > 0 else -1
                self.ball.x = self.p2.x - 2  # push past paddle
            elif self.ball.x >= self.width - 2:
                self._point_for(1)

        # Ball went out of bounds (fallback)
        if self.ball.x < 0:
            self._point_for(2)
        elif self.ball.x >= self.width:
            self._point_for(1)

    def _point_for(self, player):
        """Award a point to 'player' (1 or 2) and update state."""
        if player == 1:
            self.score_p1 += 1
            self.serving_player = 2
        else:
            self.score_p2 += 1
            self.serving_player = 1

        if self.score_p1 >= WINNING_SCORE or self.score_p2 >= WINNING_SCORE:
            self.state = "done"
            self.winner = 1 if self.score_p1 > self.score_p2 else 2
        else:
            self.state = "point"
            self.ball.dx = 0
            self.ball.dy = 0
            self.ball.x = self.width // 2
            self.ball.y = self.height // 2

    def draw(self, stdscr):
        stdscr.erase()

        # ─── Walls ──────────────────────────────────────────
        # Top and bottom walls
        for x in range(self.width):
            stdscr.addch(0, x, WALL_CHAR, curses.color_pair(COLOR_WALL))
            stdscr.addch(self.height - 1, x, WALL_CHAR, curses.color_pair(COLOR_WALL))

        # Side walls
        for y in range(self.height):
            stdscr.addch(y, 0, WALL_CHAR, curses.color_pair(COLOR_WALL))
            stdscr.addch(y, self.width - 1, WALL_CHAR, curses.color_pair(COLOR_WALL))

        # ─── Centre line ────────────────────────────────────
        mid_x = self.width // 2
        for y in range(1, self.height - 1):
            if y % 2 == 0:
                stdscr.addch(y, mid_x, "│", curses.color_pair(COLOR_WALL))

        # ─── Paddles ─────────────────────────────────────────
        for y in range(self.p1.y_top, self.p1.y_bot + 1):
            stdscr.addch(y, self.p1.x, PADDLE_CHAR, curses.color_pair(COLOR_P1))

        for y in range(self.p2.y_top, self.p2.y_bot + 1):
            stdscr.addch(y, self.p2.x, PADDLE_CHAR, curses.color_pair(COLOR_P2))

        # ─── Ball ────────────────────────────────────────────
        bx, by = int(round(self.ball.x)), int(round(self.ball.y))
        if 0 < bx < self.width - 1 and 0 < by < self.height - 1:
            stdscr.addch(by, bx, BALL_CHAR, curses.color_pair(COLOR_BALL))

        # ─── Score ──────────────────────────────────────────
        score_text = f"{self.score_p1}  ║  {self.score_p2}"
        score_x = self.width // 2 - len(score_text) // 2
        stdscr.addstr(0, score_x, score_text, curses.color_pair(COLOR_TEXT))

        # ─── Labels ─────────────────────────────────────────
        p1_label = "P1: W/S"
        p1_label_x = 2
        stdscr.addstr(self.height - 1, p1_label_x, p1_label, curses.color_pair(COLOR_P1))

        p2_label = "P2: ▲/▼  "
        p2_label_x = self.width - len(p2_label) - 2
        stdscr.addstr(self.height - 1, p2_label_x, p2_label, curses.color_pair(COLOR_P2))

        # ─── State messages ─────────────────────────────────
        msg_y = self.height // 2 - 2

        if self.state == "serve" or self.state == "point":
            serve_text = f"Player {self.serving_player}'s serve"
            if self.state == "point":
                serve_text = f"Point! {serve_text}"
            msg = f"  {serve_text}  "
            msg_x = self.width // 2 - len(msg) // 2
            stdscr.addstr(msg_y, msg_x, msg, curses.color_pair(COLOR_TEXT))
            space_msg = "Press SPACE to serve"
            sx = self.width // 2 - len(space_msg) // 2
            stdscr.addstr(msg_y + 1, sx, space_msg, curses.color_pair(COLOR_TEXT))

        elif self.state == "done":
            winner_text = f"🏆  Player {self.winner} WINS!  🏆"
            wx = self.width // 2 - len(winner_text) // 2
            stdscr.addstr(msg_y, wx, winner_text, curses.color_pair(COLOR_TEXT))
            final_score = f"Final Score: {self.score_p1} - {self.score_p2}"
            fx = self.width // 2 - len(final_score) // 2
            stdscr.addstr(msg_y + 1, fx, final_score, curses.color_pair(COLOR_TEXT))
            quit_msg = "Press Q to quit, SPACE to play again"
            qx = self.width // 2 - len(quit_msg) // 2
            stdscr.addstr(msg_y + 2, qx, quit_msg, curses.color_pair(COLOR_TEXT))

        stdscr.refresh()


# ─── Main ────────────────────────────────────────────────────────────────────


def main(stdscr):
    # ─── Curses setup ───────────────────────────────────────
    curses.curs_set(0)  # hide cursor
    stdscr.nodelay(1)   # non-blocking getch
    stdscr.timeout(0)

    # Colors
    if curses.has_colors():
        curses.start_color()
        curses.init_pair(COLOR_P1, curses.COLOR_CYAN, curses.COLOR_BLACK)
        curses.init_pair(COLOR_P2, curses.COLOR_YELLOW, curses.COLOR_BLACK)
        curses.init_pair(COLOR_BALL, curses.COLOR_WHITE, curses.COLOR_BLACK)
        curses.init_pair(COLOR_WALL, curses.COLOR_GREEN, curses.COLOR_BLACK)
        curses.init_pair(COLOR_TEXT, curses.COLOR_WHITE, curses.COLOR_BLACK)

    # ─── Terminal dimensions ────────────────────────────────
    height, width = stdscr.getmaxyx()

    # Minimum size check
    if height < 20 or width < 50:
        stdscr.erase()
        stdscr.addstr(0, 0, f"Terminal too small! Need at least 50x20, got {width}x{height}")
        stdscr.addstr(1, 0, "Press any key to exit...")
        stdscr.refresh()
        stdscr.nodelay(0)
        stdscr.getch()
        return

    game = Game(height, width)
    game.state = "serve"
    game.serving_player = 1

    # ─── Key repeat state ──────────────────────────────────
    # We keep track of which keys are held down
    p1_up = False
    p1_down = False
    p2_up = False
    p2_down = False

    clock = time.time()

    while True:
        now = time.time()
        elapsed = now - clock

        # ─── Input handling ─────────────────────────────────
        while True:
            key = stdscr.getch()
            if key == -1:
                break

            # Quit
            if key in (ord('q'), ord('Q'), 27):  # 27 = ESC
                return

            # Space (serve / restart)
            if key == ord(' '):
                if game.state in ("serve", "point"):
                    game.serve()
                elif game.state == "done":
                    game.__init__(height, width)
                    game.state = "serve"
                    game.serving_player = 1

            # Player 1 (W/S)
            if key == ord('w') or key == ord('W'):
                p1_up = True
            if key == ord('s') or key == ord('S'):
                p1_down = True

            # Player 2 (arrows)
            if key == curses.KEY_UP:
                p2_up = True
            if key == curses.KEY_DOWN:
                p2_down = True

        # Also check KEY_RESIZE if terminal resized
        # We'll just ignore it for simplicity; the game stays at original size.

        # ─── Apply held keys ────────────────────────────────
        if game.state == "play":
            if p1_up:
                game.p1.move_up(0)
            if p1_down:
                game.p1.move_down(game.height)
            if p2_up:
                game.p2.move_up(0)
            if p2_down:
                game.p2.move_down(game.height)

        # ─── Game update at fixed timestep ──────────────────
        if elapsed >= TIMESTEP and game.state == "play":
            clock = now
            # Reset input flags so we only move once per frame
            # but we re-read held keys from the buffer each frame
            game.update()

        # For non-play states, just reset clock so we don't accumulate
        if game.state != "play":
            clock = now

        # ─── Draw ───────────────────────────────────────────
        game.draw(stdscr)

        # ─── Sleep a tiny bit to avoid busy-wait ────────────
        time.sleep(0.001)

        # Reset per-frame key flags (they'll be re-set from input queue)
        p1_up = False
        p1_down = False
        p2_up = False
        p2_down = False


def entry_point():
    try:
        curses.wrapper(main)
    except KeyboardInterrupt:
        sys.exit(0)
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    entry_point()
