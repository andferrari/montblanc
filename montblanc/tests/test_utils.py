#!/usr/bin/env python
# -*- coding: utf-8 -*-
#
# Copyright (c) 2015 Simon Perkins
#
# This file is part of montblanc.
#
# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 2 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program; if not, see <http://www.gnu.org/licenses/>.

import logging
import unittest
import numpy as np
import time

import montblanc
import montblanc.factory
import montblanc.util

class TestUtils(unittest.TestCase):
    """
    TestUtil class defining unit tests for
    montblanc's montblanc.util module
    """

    def setUp(self):
        """ Set up each test case """
        np.random.seed(int(time.time()) & 0xFFFFFFFF)

        # Add a handler that outputs INFO level logging
        fh = logging.FileHandler('test.log')
        fh.setLevel(logging.INFO)

        montblanc.log.addHandler(fh)
        montblanc.log.setLevel(logging.INFO)

    def tearDown(self):
        """ Tear down each test case """
        pass

    def test_numeric_shapes(self):
        """ Test that we can convert shapes with string arguments into numeric shapes """

        shape_one = (5,'ntime','nchan')
        shape_two = (10, 'nsrc')
        ignore = ['ntime']

        ri = np.random.randint

        gns = montblanc.util.get_numeric_shape
        P = { 'ntime' : ri(5,10), 'nbl' : ri(3,5), 'nchan' : 4,
            'nsrc' : ri(4,10) }

        ntime, nbl, nchan, nsrc = P['ntime'], P['nbl'], P['nchan'], P['nsrc']

        self.assertTrue(gns(shape_one, P) == (5,ntime,nchan))
        self.assertTrue(gns(shape_two, P) == (10,nsrc))

        self.assertTrue(gns(shape_one, P, ignore=ignore) == (5,nchan))
        self.assertTrue(gns(shape_two, P, ignore=ignore) == (10,nsrc))

    def test_array_conversion(self):
        """
        Test that we can produce NumPy code that automagically translates
        between shapes with string expressions
        """

        props = { 'ntime' : np.random.randint(5,10),
                    'nbl' : np.random.randint(3,5),
                    'nchan' : 16 }

        ntime, nbl, nchan = props['ntime'], props['nbl'], props['nchan']

        f = montblanc.util.array_convert_function(
            (3,'ntime*nchan','nbl'), ('nchan', 'nbl*ntime*3'), props)

        ary = np.random.random(size=(3, ntime*nchan, nbl))
        self.assertTrue(np.all(f(ary) ==
            ary.reshape(3,ntime,nchan,nbl) \
            .transpose(2,3,1,0) \
            .reshape(nchan, nbl*ntime*3)))

    def test_eval_expr(self):
        """ Test evaluation expression and parsing """
        props = { 'ntime' : 7, 'nbl' : 4 }

        self.assertTrue(montblanc.util.eval_expr(
            '1+2*ntime+nbl', props) == (1+2*props['ntime']+props['nbl']))

        self.assertTrue(montblanc.util.eval_expr(
            'ntime*nbl*3', props) == props['ntime']*props['nbl']*3)

        self.assertTrue(montblanc.util.eval_expr_names_and_nrs(
            '1+2*ntime+nbl') == [1,2,'ntime','nbl'])

        self.assertTrue(montblanc.util.eval_expr_names_and_nrs(
            'ntime*nbl+3-1') == ['ntime','nbl',3,1])

        self.assertTrue(montblanc.util.eval_expr_names_and_nrs(
            'ntime*3+1-nbl') == ['ntime',3,1,'nbl'])

if __name__ == '__main__':
    suite = unittest.TestLoader().loadTestsFromTestCase(TestUtils)
    unittest.TextTestRunner(verbosity=2).run(suite)