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

import numpy as np

import pycuda.driver as cuda
import pycuda.gpuarray as gpuarray

import montblanc.impl.rime.v4.gpu.RimeSumCoherencies

class RimeSumCoherencies(montblanc.impl.rime.v4.gpu.RimeSumCoherencies.RimeSumCoherencies):
    def __init__(self):
        super(RimeSumCoherencies, self).__init__()
    def initialise(self, solver, stream=None):
        super(RimeSumCoherencies, self).initialise(solver,stream)
    def shutdown(self, solver, stream=None):
        super(RimeSumCoherencies, self).shutdown(solver,stream)
    def pre_execution(self, solver, stream=None):
        super(RimeSumCoherencies, self).pre_execution(solver,stream)

        if stream is not None:
            cuda.memcpy_htod_async(
                self.rime_const_data[0],
                solver.const_data().ndary(),
                stream=stream)
        else:
            cuda.memcpy_htod(
                self.rime_const_data[0],
                solver.const_data().ndary())

    def post_execution(self, solver, stream=None):
        super(RimeSumCoherencies, self).post_execution(solver,stream)

    def execute(self, solver, stream=None):
        slvr = solver

        # The gaussian shape array can be empty if
        # no gaussian sources were specified.
        gauss = np.intp(0) if np.product(slvr.gauss_shape.shape) == 0 \
            else slvr.gauss_shape

        sersic = np.intp(0) if np.product(slvr.sersic_shape.shape) == 0 \
            else slvr.sersic_shape

        self.kernel(slvr.uvw, gauss, sersic,
            slvr.frequency, slvr.antenna1, slvr.antenna2,
            slvr.jones, slvr.flag, slvr.weight_vector,
            slvr.observed_vis, slvr.G_term,
            slvr.model_vis, slvr.chi_sqrd_result,
            stream=stream, **self.launch_params)