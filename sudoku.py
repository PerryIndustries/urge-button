"""Puzzle generation for the lock screen's Sudoku."""

import random


def solved_grid(rng):
    grid = [[0] * 9 for _ in range(9)]

    def ok(r, c, n):
        if n in grid[r] or any(grid[i][c] == n for i in range(9)):
            return False
        br, bc = 3 * (r // 3), 3 * (c // 3)
        return all(grid[i][j] != n for i in range(br, br + 3) for j in range(bc, bc + 3))

    def fill(pos=0):
        if pos == 81:
            return True
        r, c = divmod(pos, 9)
        nums = list(range(1, 10))
        rng.shuffle(nums)
        for n in nums:
            if ok(r, c, n):
                grid[r][c] = n
                if fill(pos + 1):
                    return True
                grid[r][c] = 0
        return False

    fill()
    return grid


def make_puzzle(rng=None, blanks=42):
    rng = rng or random.Random()
    solution = solved_grid(rng)
    puzzle = [row[:] for row in solution]
    for pos in rng.sample(range(81), blanks):
        puzzle[pos // 9][pos % 9] = 0
    return puzzle, solution


def is_valid_solution(grid):
    full = list(range(1, 10))
    rows = all(sorted(r) == full for r in grid)
    cols = all(sorted(grid[i][c] for i in range(9)) == full for c in range(9))
    boxes = all(
        sorted(grid[br + i][bc + j] for i in range(3) for j in range(3)) == full
        for br in (0, 3, 6) for bc in (0, 3, 6)
    )
    return rows and cols and boxes


def check(entries, puzzle):
    """entries: {(r, c): int}. A cell is wrong if it clashes with a given or another entry.

    Checking against the rules (not one stored solution) means any valid answer counts,
    even when the puzzle has more than one.
    """
    grid = [row[:] for row in puzzle]
    for (r, c), v in entries.items():
        grid[r][c] = v
    wrong = set()
    for (r, c), v in entries.items():
        peers = {(r, j) for j in range(9)} | {(i, c) for i in range(9)}
        br, bc = 3 * (r // 3), 3 * (c // 3)
        peers |= {(br + i, bc + j) for i in range(3) for j in range(3)}
        peers.discard((r, c))
        if any(grid[pr][pc] == v for pr, pc in peers):
            wrong.add((r, c))
    empty = sum(1 for row in grid for v in row if v == 0)
    return wrong, empty
