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

from optparse import OptionParser
import itertools
from multiprocessing import Lock, Condition, Process, Queue, Pipe

# Simplified fraction class, specifically designed for the purpose in this
# module: it doesn't try reduction on construction or on the result of
# arithmetic operation as it can be very expensive (that's probably why
# the standard fractions.Fraction is slow and why we don't use it).
class Fraction(object):
    def __init__(self, val, denom=1):
        self.n = val            # numerator
        self.d = denom          # denominator

    def add(self, other):
        return Fraction(self.n * other.d + self.d * other.n, self.d * other.d)

    def sub(self, other):
        return Fraction(self.n * other.d - self.d * other.n, self.d * other.d)

    def mult(self, other):
        return Fraction(self.n * other.n, self.d * other.d)

    def div(self, other):
        return Fraction(self.n * other.d, self.d * other.n)

# Mapping from textual operator to the corresponding lambda expression used
# in calc() (see below).  _int() will be used when there's no need to consider
# fractions; otherwise _frac() will be used.
op_conv_int = {'+': lambda a,b: b + a,
               '-': lambda a,b: b - a,
               '*': lambda a,b: b * a,
               '/': lambda a,b: b / a}
op_conv_frac = {'+': lambda a,b: b.add(a),
                '-': lambda a,b: b.sub(a),
                '*': lambda a,b: b.mult(a),
                '/': lambda a,b: b.div(a)}

# A helper to calculate the given expression in the Reverse Polish Notation.
# If 'goal' is not None, we assume the expression only contains '+' or '*',
# so we stop the calculation once an intermediate result exceeds 'goal'.
# 'use_frac' indicates whether we should use fractions (i.e., at least one '/'
# is included).
# It returns None if the result is obviously not what is wanted (different from
# goal if it's specified or the result is not an integer).
def calc(program, goal, use_frac):
    stack = []
    op_conv = op_conv_frac if use_frac else op_conv_int
    for opx in program:
        if opx in op_conv:
            a = stack.pop()
            b = stack.pop()
            stack.append(op_conv[opx](a, b))
            if goal is not None and stack[-1] > goal:
                return None
        elif use_frac:
            stack.append(Fraction(opx))
        else:
            stack.append(opx)
    result = stack[0]
    if use_frac:
        result = int(result.n / result.d) if result.n % result.d == 0 else None
    return result

class Node(object):
    def __init__(self, val, left, right):
        self.val = val
        self.left = left
        self.right = right

def tree2str(root):
    if type(root) is int:
        return str(root)

    l_str = tree2str(root.left)
    r_str = tree2str(root.right)
    if root.val in '*/':
        if type(root.left) is not int and root.left.val in '+-':
            l_str = '(' + l_str + ')'
        if type(root.right) is not int and root.right.val in '+-':
            r_str = '(' + r_str + ')'
    return '%s %s %s' % (l_str, root.val, r_str)

# Tweak the expression tree so we can omit unnecessary parentheses in the
# right hand of the '-/' operator.  We can do this by reversing all right-hand
# descendant '+-' or '*/' nodes that are directly reachable from 'node'
# (i.e., there's no '*/' or '+-' in the middle).  We have to do this
# recursively.
# Note that the tree will not be usable for calculation after this modification
# anymore.  It's okay since we only use it for printing.
def reduce_subdivs(node):
    if type(node) == int:
        return

    reduce_subdivs(node.left)
    reduce_subdivs(node.right)

    if node.val == '-':
        conv = {'+': '-', '-': '+'}
    elif node.val == '/':
        conv = {'*': '/', '/': '*'}
    else:
        return

    nodes = [node.right]
    while nodes:
        n = nodes.pop(0)
        if type(n) is not int:
            if n.val in conv:
                n.val = conv[n.val]
                nodes.append(n.left)
                nodes.append(n.right)

def rpn2str(rpn):
    stack = []
    for opx in rpn:
        if opx in op_conv_int:
            # Pop left and right subtrees from the stack.  Note that the order
            # is important.
            right = stack.pop()
            left = stack.pop()
            stack.append(Node(opx, left, right))
        else:
            stack.append(opx)
    reduce_subdivs(stack[0])
    return tree2str(stack[0])

def run_worker(conn, goal, max_level, tasks, task_lock, task_cv):
    solutions = set()
    while True:
        with task_lock:
            while tasks.empty():
                task_cv.wait()
            task = tasks.get()
        if task is None:
            # received termination command.  Pass the collected solutions to
            # the master process and exit.
            conn.send(solutions)
            break
        numops_list = task

        # Build all possible RPN's for 'numops_list' and '1, 2, ..., M+1',
        # calculate its value, and see if it's equal to the goal value.
        for ops in itertools.product('+-*/', repeat=max_level):
            program = []
            mono = not('-' in ops or '/' in ops) # for optimization
            use_frac = '/' in ops
            for i in range(0, max_level + 1):
                program.append(i + 1)
                program.extend(ops[0:numops_list[i]])
                ops = ops[numops_list[i]:]
            try:
                result = calc(program, goal if mono else None, use_frac)
                if result == goal:
                    solution = rpn2str(program)
                    if solution not in solutions:
                        solutions.add(solution)
            except ZeroDivisionError:
                pass

def solve(max_level, goal, num_workers):
    # prepare message queue shared with workers
    tasks = Queue()
    task_lock = Lock()
    task_cv = Condition(lock=task_lock)

    # create and start workers
    workers = []
    for i in range(0, num_workers):
        solutions = set()
        parent_conn, child_connn = Pipe()
        worker = Process(target=run_worker,
                         args=(child_connn, goal, max_level, tasks,
                               task_lock, task_cv))
        worker.start()
        workers.append((worker, parent_conn))

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
            # Found one valid RPN template.  Pass it to workers and have them
            # work on it.
            numops_list.append(max_level - total_ops)
            with task_lock:
                tasks.put(numops_list)
                task_cv.notify()

    # Tell workers all data have been passed.
    solutions = set()
    with task_lock:
        for _ in workers:
            tasks.put(None)
        task_cv.notify_all()

    # Wait until all workers complete the tasks.  Receive their solutions,
    # unify them with suppressing any duplicates found by different workers,
    # and print the final solutions.
    for w in workers:
        worker_solutions = w[1].recv()
        w[0].join()
        for solution in worker_solutions:
            if solution not in solutions:
                solutions.add(solution)
    for solution in solutions:
        print(solution)

if __name__ == '__main__':
    parser = OptionParser(usage='usage: %prog [options] target [max_number]')
    parser.add_option("-w", "--workers", dest='num_workers',
                      action="store", default=1,
                      help="number of worker processes [default: %default]")
    (options, args) = parser.parse_args()

    max_num = args[1] if len(args) > 1 else 9
    max_level = int(max_num) - 1
    goal = args[0]
    solve(int(max_level), int(goal), int(options.num_workers))
