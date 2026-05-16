#!/usr/bin/env python3
"""Run direct import of cartpole module and test."""
import sys
import os

# Add the directory containing examples to path
sys.path.insert(0, os.path.dirname(os.path.abspath(".")) or ".")

# Manual import
import importlib.util
spec = importlib.util.spec_from_file_location(
    "cartpole_module",
    os.path.join("examples", "agent-projects", "cartpole.py")
)
cartpole = importlib.util.module_from_spec(spec)
spec.loader.exec_module(cartpole)
CartPoleEnv = cartpole.CartPoleEnv

env = CartPoleEnv(max_steps=20)
state = env.reset()
assert len(state) == 4
print("reset() OK")

s, r, d, info = env.step(0)
assert r == 1.0
assert isinstance(d, bool)
print(f"step(0) -> r={r}, d={d}")

out = env.render(mode="ansi")
assert isinstance(out, str) and len(out) > 0
print(f"render('ansi') OK: {repr(out[:60])}...")

env.reset()
for i in range(100):
    s, r, d, _ = env.step(i % 2)
    if d:
        print(f"Episode ended after {i+1} steps, reason={_['termination_reason']}")
        break

try:
    env.step(2)
except ValueError:
    print("ValueError for bad action OK")

env2 = CartPoleEnv(max_steps=1)
env2.reset()
env2.step(0)
try:
    env2.step(0)
except RuntimeError:
    print("RuntimeError on done OK")

env.close()
print("\nAll checks passed!")
