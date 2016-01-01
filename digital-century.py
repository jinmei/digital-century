#!/usr/bin/env python

# Copyright (C) 2015  JINMEI Tatuya
#
# Permission to use, copy, modify, and distribute this software for any
# purpose with or without fee is hereby granted, provided that the above
# copyright notice and this permission notice appear in all copies.
#
# THE SOFTWARE IS PROVIDED "AS IS" AND THE AUTHOR DISCLAIMS ALL WARRANTIES WITH
# REGARD TO THIS SOFTWARE INCLUDING ALL IMPLIED WARRANTIES OF MERCHANTABILITY
# AND FITNESS.  IN NO EVENT SHALL THE AUTHOR BE LIABLE FOR ANY SPECIAL, DIRECT,
# INDIRECT, OR CONSEQUENTIAL DAMAGES OR ANY DAMAGES WHATSOEVER RESULTING FROM
# LOSS OF USE, DATA OR PROFITS, WHETHER IN AN ACTION OF CONTRACT, NEGLIGENCE
# OR OTHER TORTIOUS ACTION, ARISING OUT OF OR IN CONNECTION WITH THE USE OR
# PERFORMANCE OF THIS SOFTWARE.

import sys
from fractions import Fraction
import itertools

# Mapping from textual operator to the corresponding lambda expression used
# in calc() (see below).   Fraction arithmetic is VERY expensive, so we avoid
# using it unless we may really need it, i.e., it involves division.
op_conv = {'+': lambda a,b: b + a,
           '-': lambda a,b: b - a,
           '*': lambda a,b: b * a,
           '/': lambda a,b: b / Fraction(a)}

# A helper to calculate the given expression in reverse Polish notation.
# If 'goal' is not None, we assume the expression only contains '+' or '*',
# so we stop the calculation once an intermediate result exceeds 'goal'.
def calc(program, goal):
    stack = []
    for opx in program:
        if opx in op_conv:
            a = stack.pop()
            b = stack.pop()
            stack.append(op_conv[opx](a, b))
            if goal is not None and stack[-1] > goal:
                return None     # indicate we interrupted the calculation
        else:
            stack.append(opx)
    return stack[0]

def solve(max_level, goal):
    # Find all possible sequences: [n0, n1, n2, ..., nM] (M=max_level)
    # where nX is the number of binary operators so that
    # '1 <n0 ops> 2 <n1 ops> 3 <n2 ops> ... M+1 <nM ops>' can be a valid
    # Reverse Polish Notation.  Key conditions are:
    # 1. n0 + n1 + ... + nM = M
    # 2. for any X, n0 + n1 + ... + nX <= X
    # (Note that from condition #2 n0 is always 0.)
    # We'll build the sequences in 'numops_list' below while exploring cases
    # in a BFS-like (or DP-like) manner.

    # This is a queue to maintain outstanding search results.  Its each element
    # is a tuple of 2 items: 'numops_list', 'total_ops'
    # A tuple of (N, T) means:
    # - N = [n0, n1, ..., nX]
    # - T = sum(N)
    # (Note that we don't necessarily have to keep T as it can be derived
    # from N.  But we do this for efficiency).
    # The search is completed when len(N) reaches M (i.e., X=M-1) by appending
    # the last item of nM = M - (n0 + n1 + ... + nX) = M - T (see condition #1).
    tmp = [([0], 0)]

    while tmp:
        numops_list, total_ops = tmp.pop(0)
        level = len(numops_list)
        if level < max_level:
            # Expand the sequence with all possible numbers of operators at
            # the current level so we can explore the next level for each of
            # them.
            for i in range(0, level - total_ops + 1): # see condition #2
                tmp.append((numops_list + [i], total_ops + i))
        else:
            numops_list.append(max_level - total_ops)

            # Build all possible RPN's for 'numops_list' and '1, 2, ..., M+1',
            # calculate its value, and see if it's equal to the goal value.
            for ops in itertools.product('+-*/', repeat=max_level):
                program = []
                mono = not('-' in ops or '/' in ops) # for optimization
                for i in range(0, max_level + 1):
                    program.append(i + 1)
                    program.extend(ops[0:numops_list[i]])
                    ops = ops[numops_list[i]:]
                try:
                    result = calc(program, goal if mono else None)
                    if result == goal:
                        print('(%s) = %s' %
                              (' '.join([str(v) for v in program]),
                               str(result)))
                except ZeroDivisionError:
                    pass

if __name__ == '__main__':
    max_num = sys.argv[2] if len(sys.argv) > 2 else 9
    max_level = int(max_num) - 1
    goal = sys.argv[1]
    solve(int(max_level), int(goal))
