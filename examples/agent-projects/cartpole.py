#!/usr/bin/env python3
"""
CartPole Environment — Pure Python, Gym-style API.

State space (4-d):
    0: Cart position (m)
    1: Cart velocity (m/s)
    2: Pole angle (rad)  (0 = upright)
    3: Pole angular velocity (rad/s)

Action space (2):
    0: Push cart left  (-10 N)
    1: Push cart right (+10 N)

Reward: +1 per timestep pole stays upright.
Episode ends when:
    - Pole angle > ±12° (≈0.209 rad)
    - Cart position > ±2.4 m
    - Episode length reaches max_steps (default 500)
"""

import math
import sys
import time
from typing import Optional, Tuple, List

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
GRAVITY = 9.8
MASSCART = 1.0
MASSPOLE = 0.1
TOTAL_MASS = MASSCART + MASSPOLE
LENGTH = 0.5          # half the pole length
POLEMASS_LENGTH = MASSPOLE * LENGTH
FORCE_MAG = 10.0
TAU = 0.02            # seconds between state updates

# Angle at which to fail the episode
THETA_THRESHOLD_RADIANS = 12.0 * math.pi / 180.0  # ~0.209 rad
X_THRESHOLD = 2.4

# ---------------------------------------------------------------------------
# Environment
# ---------------------------------------------------------------------------
class CartPoleEnv:
    """CartPole balancing environment."""

    metadata = {"render.modes": ["human", "ansi"]}

    def __init__(self, max_steps: int = 500):
        self.max_steps = max_steps
        self.action_space = 2          # discrete actions
        self.observation_space = 4     # continuous

        self.state: Optional[List[float]] = None
        self.steps: int = 0
        self.done: bool = True

        # Rendering history
        self._render_history: List[Tuple[float, float]] = []

    # ----- Public API ------------------------------------------------------

    def reset(
        self,
        *,
        seed: Optional[int] = None,
        return_info: bool = False,
    ) -> Tuple[List[float], dict]:
        """Reset environment to initial state.

        Args:
            seed: RNG seed for reproducibility (optional).
            return_info: If True, return (state, info).

        Returns:
            state: [x, x_dot, theta, theta_dot]
            info: optional metadata dict
        """
        if seed is not None:
            random.seed(seed)

        # Slightly randomised initial conditions near upright
        self.state = [
            random.uniform(-0.05, 0.05),   # x
            random.uniform(-0.05, 0.05),   # x_dot
            random.uniform(-0.05, 0.05),   # theta
            random.uniform(-0.05, 0.05),   # theta_dot
        ]
        self.steps = 0
        self.done = False
        self._render_history.clear()
        self._render_history.append((self.state[0], self.state[2]))

        if return_info:
            return self.state, {}
        return self.state

    def step(self, action: int) -> Tuple[List[float], float, bool, dict]:
        """Apply action and advance simulation by one timestep.

        Args:
            action: 0 (left) or 1 (right)

        Returns:
            state, reward, done, info
        """
        if self.done:
            raise RuntimeError("Episode is done. Call reset() first.")

        if action not in (0, 1):
            raise ValueError(f"Invalid action {action}. Use 0 or 1.")

        x, x_dot, theta, theta_dot = self.state
        force = -FORCE_MAG if action == 0 else FORCE_MAG

        # --- Physics (Euler integration) ---
        costheta = math.cos(theta)
        sintheta = math.sin(theta)

        temp = (force + POLEMASS_LENGTH * theta_dot * theta_dot * sintheta) / TOTAL_MASS

        thetaacc = (GRAVITY * sintheta - costheta * temp) / (
            LENGTH * (4.0 / 3.0 - MASSPOLE * costheta * costheta / TOTAL_MASS)
        )

        xacc = temp - POLEMASS_LENGTH * thetaacc * costheta / TOTAL_MASS

        # Update state
        x += TAU * x_dot
        x_dot += TAU * xacc
        theta += TAU * theta_dot
        theta_dot += TAU * thetaacc

        self.state = [x, x_dot, theta, theta_dot]
        self.steps += 1
        self._render_history.append((x, theta))

        # --- Termination conditions ---
        pole_done = abs(theta) > THETA_THRESHOLD_RADIANS
        cart_done = abs(x) > X_THRESHOLD
        max_steps_reached = self.steps >= self.max_steps

        self.done = pole_done or cart_done or max_steps_reached

        # Reward: +1 every step the pole is up
        reward = 1.0

        info = {
            "pole_angle": theta,
            "cart_position": x,
            "steps": self.steps,
            "termination_reason": (
                "pole_angle" if pole_done else
                "cart_position" if cart_done else
                "max_steps" if max_steps_reached else
                None
            ),
        }

        return self.state, reward, self.done, info

    def render(self, mode: str = "human"):
        """Render the current state.

        Supported modes:
            "human" — ASCII art in terminal (live-updating).
            "ansi"  — return a string representation.
        """
        if self.state is None:
            return "" if mode == "ansi" else None

        x, _, theta, _ = self.state
        ansi_str = self._build_frame(x, theta)

        if mode == "ansi":
            return ansi_str

        # "human" mode — print to terminal
        sys.stdout.write("\033[H\033[J")          # clear screen
        sys.stdout.write(ansi_str)
        sys.stdout.write(f"\nSteps: {self.steps}  |  "
                         f"Angle: {theta:+.4f} rad  |  "
                         f"X: {x:+.3f} m\n")
        sys.stdout.flush()
        # Small sleep so animation is visible
        time.sleep(TAU * 10)  # scale to ~real-time feel

    def close(self):
        """Clean up resources."""
        self.state = None
        self._render_history.clear()
        self.done = True

    # ----- Private helpers -------------------------------------------------

    def _build_frame(self, x: float, theta: float) -> str:
        """Return a string-based frame showing cart + pole."""
        # Track width (characters)
        half_width = 20
        cart_width = 7
        pole_len = 10

        # Scale x to screen coordinate (clamp for display)
        screen_scale = half_width / X_THRESHOLD
        cart_col = int(round(x * screen_scale)) + half_width
        cart_col = max(0, min(2 * half_width, cart_col))

        # Pole tip position relative to cart centre
        tip_x_offset = -pole_len * math.sin(theta)
        tip_col = cart_col + int(round(tip_x_offset))
        tip_col = max(0, min(2 * half_width, tip_col))

        # Build ground line
        ground = "=" * (2 * half_width + 1)

        # Build cart
        cart = [" "] * (2 * half_width + 1)
        cart_left = max(0, cart_col - cart_width // 2)
        cart_right = min(2 * half_width, cart_col + cart_width // 2)
        for i in range(cart_left, cart_right + 1):
            cart[i] = "#"

        # Overwrite pole tip
        if 0 <= tip_col < len(cart):
            if not (cart_left <= tip_col <= cart_right):
                # Pole extends beyond cart
                cart[tip_col] = "@"
            else:
                cart[tip_col] = "O"  # pivot on cart

        # Build pole line (simple approach: show pole as characters)
        # Better: draw pole segments between cart and tip
        lines = []
        # Pole row (above cart)
        pole_row = [" "] * (2 * half_width + 1)
        # Draw pole from cart to tip
        if tip_col != cart_col:
            step = 1 if tip_col > cart_col else -1
            for c in range(cart_col, tip_col + step, step):
                if 0 <= c < len(pole_row):
                    pole_row[c] = "|"
        # Mark tip
        if 0 <= tip_col < len(pole_row):
            pole_row[tip_col] = "@"
        # Mark cart centre
        if 0 <= cart_col < len(pole_row):
            pole_row[cart_col] = "O"

        lines.append("".join(pole_row))
        lines.append("".join(cart))
        lines.append(ground)

        # Label
        angle_deg = math.degrees(theta)
        lines.append(f"Angle: {angle_deg:+.1f}°    Position: {x:+.2f}m")

        return "\n".join(lines)

    def __repr__(self) -> str:
        return f"CartPoleEnv(state={self.state}, steps={self.steps}, done={self.done})"


# ---------------------------------------------------------------------------
# Simple demo / test
# ---------------------------------------------------------------------------
def _demo():
    """Run a quick random-policy demo."""
    env = CartPoleEnv(max_steps=200)

    print("CartPole Demo — Random Policy")
    print("=" * 40)
    input("Press Enter to start...")

    state = env.reset()
    total_reward = 0
    done = False

    while not done:
        action = random.randint(0, 1)
        state, reward, done, info = env.step(action)
        total_reward += reward
        env.render(mode="human")

    print(f"\n{'=' * 40}")
    print(f"Episode finished after {info['steps']} steps.")
    print(f"Total reward: {total_reward}")
    print(f"Reason: {info['termination_reason']}")

    env.close()


# ---------------------------------------------------------------------------
# Alternative: manual-play (arrow keys)
# ---------------------------------------------------------------------------
def _manual_play():
    """Let a human play using keyboard input (left/right arrows)."""
    try:
        pass  # readline not available; raw input used instead
    except ImportError:
        pass

    env = CartPoleEnv(max_steps=500)
    state = env.reset()
    total_reward = 0
    done = False

    print("Manual Play — Press 'a' (left) or 'd' (right), then Enter.")
    print("Press 'q' to quit.\n")

    while not done:
        env.render(mode="human")
        key = input("Action (a/d/q): ").strip().lower()
        if key == "q":
            break
        action = 0 if key == "a" else 1
        state, reward, done, info = env.step(action)
        total_reward += reward

    print(f"\nTotal reward: {total_reward}  |  Steps: {info['steps']}")
    print(f"Reason: {info['termination_reason']}")
    env.close()


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    import random

    if "--manual" in sys.argv:
        _manual_play()
    else:
        _demo()
