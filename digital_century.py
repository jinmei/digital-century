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

# This class and following several functions is defined to convert a RPN
# expression into normalized string.  We'll first convert the RPN into a
# tree structure.  This class represents nodes of the tree.
class Node(object):
    def __init__(self, val, left, right):
        self.val = val
        self.left = left
        self.right = right

# Convert an expression in the form of binary tree whose root is node into
# string, adding parentheses if and only if they are necessary.
def tree2str(node):
    if type(node) is int:
        return str(node)

    l_str = tree2str(node.left)
    r_str = tree2str(node.right)

    # Assuming left-hand side of '-' and '/' has been reduced to suppress
    # unnecessary parentheses, we should only consider trivial cases
    if node.val in '*/':
        if type(node.left) is not int and node.left.val in '+-':
            l_str = '(' + l_str + ')'
        if type(node.right) is not int and node.right.val in '+-':
            r_str = '(' + r_str + ')'

    return '%s %s %s' % (l_str, node.val, r_str)

# Tweak the expression tree so we can omit unnecessary parentheses in the
# right hand of the '-/' operator.  We can do this by reversing all left-hand
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
        if type(n) is not int and n.val in conv:
            n.val = conv[n.val]
            nodes.append(n.left)
            nodes.append(n.right)

# Convert the given RPN into a string so the result doesn't contain unnecessary
# parentheses.  In addition to use it for printing purposes, we'll also use
# the result as a key to suppress essentially duplicate expressions.
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

# The loop for worker processes.
def run_worker(conn, goal, max_level, tasks, task_lock, task_cv):
    solutions = set()
    while True:
        # get the next task from the master process.
        with task_lock:
            while tasks.empty():
                task_cv.wait()
            task = tasks.get()
        if task is None:
            # received termination command.  Pass the collected solutions to
            # the master and exit.
            conn.send(solutions)
            conn.send(None)
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
            solution = None
            try:
                result = calc(program, goal if mono else None, use_frac)
                if goal is None:
                    solution = '%s = %s' % (rpn2str(program), str(result))
                elif result == goal:
                    solution = rpn2str(program)
            except ZeroDivisionError:
                if goal is None:
                    solution = '%s = Div0' % (rpn2str(program),)
            finally:
                if solution is not None and solution not in solutions:
                    solutions.add(solution)

        # Pass some intermediate solutions to the master process to avoid
        # having too much intermediate data at the cost of having more
        # intermediate duplicates (they'll eventually be unified at the master
        # anyway).  The threshold was an arbitrary choice.  In practice, this
        # only happens when 'goal' is None, i.e., trying to collect all
        # expressions.
        if len(solutions) > 10000:
            conn.send(solutions)
            solutions.clear()

# Top-level code for the master process to solve the problem.
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

    # Wait until all workers complete the tasks, while receiving any
    # intermediate and last solutions.  The received solutions may not
    # necessarily be fully unique, so we have to unify them here, again.
    # Received data of 'None' means the corresponding worker has completed
    # its task.
    # Note: here we assume all workers are reasonably equally active in
    # sending data, so we simply perform blocking receive.
    conns = set([w[1] for w in workers])
    while conns:
        for c in conns.copy():
            worker_data = c.recv()
            if worker_data is None:
                conns.remove(c)
                continue
            for solution in worker_data:
                if solution not in solutions:
                    solutions.add(solution)

    # All workers have completed.  Cleanup them and print the final unified
    # results.
    for w in workers:
        w[0].join()
    for solution in solutions:
        print(solution)

if __name__ == '__main__':
    parser = OptionParser(usage='usage: %prog [options] [target]')
    parser.add_option("-w", "--workers", dest='num_workers',
                      action="store", default=1,
                      help="number of worker processes [default: %default]")
    parser.add_option("-m", "--max_num", dest='max_num',
                      action="store", default=9,
                      help="max number of the sequence [default: %default]")
    (options, args) = parser.parse_args()

    goal = int(args[0]) if len(args) > 0 else None
    max_level = int(options.max_num) - 1
    solve(int(max_level), goal, int(options.num_workers))
