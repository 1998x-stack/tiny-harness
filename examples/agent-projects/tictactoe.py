#!/usr/bin/env python3
"""
Terminal Tic-Tac-Toe — Two-player, 3×3 grid, self-contained.
"""

import os
import sys

EMPTY = " "
PLAYERS = ("X", "O")


def clear_screen() -> None:
    """Cross-platform terminal clear."""
    os.system("cls" if os.name == "nt" else "clear")


def render(board: list[list[str]], status: str) -> None:
    """Draw the board and status line."""
    clear_screen()
    print("  TIC-TAC-TOE\n")
    print("    0   1   2")
    for r in range(3):
        print(f"  {r}  {board[r][0]} | {board[r][1]} | {board[r][2]}")
        if r < 2:
            print("    ---+---+---")
    print()
    print(f"  {status}")


def check_winner(board: list[list[str]]) -> str | None:
    """Return the winning mark, or None."""
    # Rows & columns
    for i in range(3):
        if board[i][0] == board[i][1] == board[i][2] != EMPTY:
            return board[i][0]
        if board[0][i] == board[1][i] == board[2][i] != EMPTY:
            return board[0][i]
    # Diagonals
    if board[0][0] == board[1][1] == board[2][2] != EMPTY:
        return board[0][0]
    if board[0][2] == board[1][1] == board[2][0] != EMPTY:
        return board[0][2]
    return None


def is_full(board: list[list[str]]) -> bool:
    """Check if every cell is taken."""
    return all(cell != EMPTY for row in board for cell in row)


def get_move(player: str, board: list[list[str]]) -> tuple[int, int]:
    """Prompt the current player for a valid move."""
    while True:
        try:
            raw = input(f"  Player {player}, enter row and column (e.g. 1 2): ")
            r_str, c_str = raw.strip().split()
            r, c = int(r_str), int(c_str)
        except (ValueError, IndexError):
            print("  Invalid input. Use two numbers separated by a space.")
            continue
        if r not in range(3) or c not in range(3):
            print("  Row and column must be 0, 1, or 2.")
            continue
        if board[r][c] != EMPTY:
            print("  That cell is already taken.")
            continue
        return r, c


def play_again() -> bool:
    """Ask the players whether to start a new game."""
    while True:
        ans = input("  Play again? (y/n): ").strip().lower()
        if ans in ("y", "yes"):
            return True
        if ans in ("n", "no"):
            return False
        print("  Please answer y or n.")


def main() -> None:
    """Main game loop."""
    while True:
        # Fresh board
        board = [[EMPTY] * 3 for _ in range(3)]
        turn = 0  # 0 → player X, 1 → player O

        while True:
            player = PLAYERS[turn]
            render(board, f"Player {player}'s turn")
            r, c = get_move(player, board)
            board[r][c] = player

            winner = check_winner(board)
            if winner:
                render(board, f"Player {winner} wins! 🎉")
                break

            if is_full(board):
                render(board, "It's a draw!")
                break

            turn ^= 1  # switch player

        if not play_again():
            print("\n  Thanks for playing! Goodbye.\n")
            break


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n\n  Game aborted. Goodbye.\n")
        sys.exit(0)
