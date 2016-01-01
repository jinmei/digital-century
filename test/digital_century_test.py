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
import os
sys.path.append(os.path.dirname(os.path.realpath(__file__)) + '/..')
import unittest

# import definitions from the tested module.  this must be done after adjusting
# sys.path (see above)
from digital_century import *

class DigitalCenturyTest(unittest.TestCase):
    def test_rpn2str(self):
        # Basic case
        self.assertEqual('1 + 2 + 3', rpn2str([1, 2, 3, '+', '+']))

        # Check necessary parentheses
        self.assertEqual('1 * (2 + 3)', rpn2str([1, 2, 3, '+', '*']))
        self.assertEqual('1 / (2 + 3)', rpn2str([1, 2, 3, '+', '/']))

        # Subtraction reduction
        # 1 - (2 - 3) = 1 - 2 + 3
        self.assertEqual('1 - 2 + 3', rpn2str([1, 2, 3, '-', '-']))

        # 1 - ((2 - 3) - 4) = 1 - 2 + 3 + 4
        self.assertEqual('1 - 2 + 3 + 4', rpn2str([1, 2, 3, '-', 4, '-', '-']))

        # 1 - (2 - (3 - 4)) = 1 - 2 + 3 - 4
        self.assertEqual('1 - 2 + 3 - 4', rpn2str([1, 2, 3, 4, '-', '-', '-']))

        # 1 * (2 - (3 + 4)) = 1 * (2 - 3 - 4)
        self.assertEqual('1 * (2 - 3 - 4)',
                         rpn2str([1, 2, 3, 4, '+', '-', '*']))

        # (1 - (2 - 3)) * 4) = (1 - 2 + 3) * 4
        self.assertEqual('(1 - 2 + 3) * 4',
                         rpn2str([1, 2, 3, '-', '-', 4, '*']))

        # Division reduction (more complicated are essentially covered in
        # tests for subtraction reduction as the code base is the same)
        # 1 / (2 * 3) => 1 / 2 / 3
        self.assertEqual('1 / 2 / 3', rpn2str([1, 2, 3, '*', '/']))

if '__main__' == __name__:
    unittest.main()
