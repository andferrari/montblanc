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
import string

from pycuda.compiler import SourceModule

import montblanc
from montblanc.node import Node

FLOAT_PARAMS = {
    'BLOCKDIMX' : 32,   # Number of channels and polarisations
    'BLOCKDIMY' : 32,   # Number of antenna
    'BLOCKDIMZ' : 1,    #
    'maxregs'   : 32    # Maximum number of registers
}

DOUBLE_PARAMS = {
    'BLOCKDIMX' : 32,   # Number of channels and polarisations
    'BLOCKDIMY' : 16,   # Number of antenna
    'BLOCKDIMZ' : 1,    #
    'maxregs'   : 63    # Maximum number of registers
}

KERNEL_TEMPLATE = string.Template("""
#include \"math_constants.h\"
#include <montblanc/include/abstraction.cuh>
#include <montblanc/include/brightness.cuh>

#define NA (${na})
#define NBL (${nbl})
#define NCHAN (${nchan})
#define NTIME (${ntime})
#define NSRC (${nsrc})
#define NPOL (4)
#define NPOLCHAN (NPOL*NCHAN)

#define BEAM_LW (${beam_lw})
#define BEAM_MH (${beam_mh})
#define BEAM_NUD (${beam_nud})

#define BLOCKDIMX (${BLOCKDIMX})
#define BLOCKDIMY (${BLOCKDIMY})
#define BLOCKDIMZ (${BLOCKDIMZ})

template <
    typename T,
    typename Tr=montblanc::kernel_traits<T>,
    typename Po=montblanc::kernel_policies<T> >
__device__ __forceinline__
void bilinear_interpolate(
    typename Tr::ct & sum,
    typename Tr::ft & abs_sum,
    typename Tr::ct * E_beam,
    float gl, float gm, float gchan,
    const float ld, const float md, const float chd)
{
    #define POL (threadIdx.x & 0x3)

    float l = floorf(gl) + ld;
    float m = floorf(gm) + md;
    float ch = floorf(gchan) + chd;

    // If this coordinate is outside the cube, do nothing
    if(l < 0 || l >= BEAM_LW ||
        m < 0 || m >= BEAM_MH ||
        ch < 0 || ch >= BEAM_NUD)
        { return; }

    // The bilinear weighting is constructed by multiplying
    // absolute differences. Note that we don't have
    // to divide by the product of each dimension's grid distance
    // since they are all 1.0.
    T weight = fabsf(l-gl)*fabsf(m-gm)*fabsf(ch-gchan);
    int i = ((int(l)*BEAM_MH + int(m))*BEAM_NUD + int(ch))*NPOL + POL;

    // Perhaps unnecessary as long as BLOCKDIMX is 32
    typename Tr::ct pol = cub::ThreadLoad<cub::LOAD_LDG>(E_beam + i);
    sum.x += weight*pol.x;
    sum.y += weight*pol.y;
    abs_sum += weight*Po::abs(pol);

    #undef POL
}

template <typename T> class EBeamTraits {};

template <> class EBeamTraits<float>
{
public:
    typedef float2 LMType;
    typedef float2 PointErrorType;
    typedef float2 AntennaScaleType;
};

template <> class EBeamTraits<double>
{
public:
    typedef double2 LMType;
    typedef double2 PointErrorType;
    typedef double2 AntennaScaleType;
};


template <
    typename T,
    typename Tr=montblanc::kernel_traits<T>,
    typename Po=montblanc::kernel_policies<T> >
__device__
void rime_jones_E_beam_impl(
    typename EBeamTraits<T>::LMType * lm,
    typename EBeamTraits<T>::PointErrorType * point_errors,
    typename EBeamTraits<T>::AntennaScaleType * antenna_scaling,
    typename Tr::ct * E_beam,
    typename Tr::ct * jones,
    T parallactic_angle,
    T beam_ll, T beam_lm,
    T beam_ul, T beam_um)
{
    int POLCHAN = blockIdx.x*blockDim.x + threadIdx.x;
    int ANT = blockIdx.y*blockDim.y + threadIdx.y;
    int SRC = blockIdx.z*blockDim.z + threadIdx.z;
    #define POL (threadIdx.x & 0x3)
    #define BLOCKCHANS (BLOCKDIMX >> 2)

    if(SRC >= NSRC || ANT >= NA || POLCHAN >= NPOLCHAN)
        return;

    __shared__ typename EBeamTraits<T>::LMType s_lm0[BLOCKDIMZ];
    __shared__ typename EBeamTraits<T>::PointErrorType s_lmd[BLOCKDIMY][BLOCKCHANS];
    __shared__ typename EBeamTraits<T>::AntennaScaleType s_ab[BLOCKDIMY][BLOCKCHANS];

    int i;

    // LM coordinates vary by source only,
    // not antenna or polarised channel
    if(threadIdx.y == 0 && threadIdx.x == 0)
    {
        i = SRC;   s_lm0[threadIdx.z] = lm[i];
    }

    // Antenna scaling factors vary by antenna and channel,
    // but not source or timestep
    if(threadIdx.z == 0 && (threadIdx.x & 0x3) == 0)
    {
        int blockchan = threadIdx.x >> 2;
        i = ANT*NCHAN + (POLCHAN >> 2);
        s_ab[threadIdx.y][blockchan] = antenna_scaling[i];
    }

    __syncthreads();

    for(int TIME=0; TIME < NTIME; ++TIME)
    {
        // Pointing errors vary by time, antenna and channel,
        // but not source
        if(threadIdx.z == 0 && (threadIdx.x & 0x3) == 0)
        {
            int blockchan = threadIdx.x >> 2;
            i = (TIME*NA + ANT)*NCHAN + (POLCHAN >> 2);
            s_lmd[threadIdx.y][blockchan] = point_errors[i];
        }

        __syncthreads();

        // Figure out how far the source has
        // rotated within the beam
        T sint, cost;
        Po::sincos(parallactic_angle*TIME, &sint, &cost);

        // Rotate the source
        T l = s_lm0[threadIdx.z].x*cost - s_lm0[threadIdx.z].y*sint;
        T m = s_lm0[threadIdx.z].x*sint + s_lm0[threadIdx.z].y*cost;

        // Add the pointing errors for this antenna.
        int blockchan = threadIdx.x >> 2;
        l += s_lmd[threadIdx.y][blockchan].x;
        m += s_lmd[threadIdx.y][blockchan].y;

        // Multiply by the antenna scaling factors.
        l *= s_ab[threadIdx.y][blockchan].x;
        m *= s_ab[threadIdx.y][blockchan].y;

        float gl = T(BEAM_LW) * (l - beam_ll) / (beam_ul - beam_ll);
        float gm = T(BEAM_MH) * (m - beam_lm) / (beam_um - beam_lm);
        float gchan = T(BEAM_NUD) * float((POLCHAN>>2))/float(NCHAN);

        typename Tr::ct sum = Po::make_ct(0.0, 0.0);
        typename Tr::ft abs_sum = T(0.0);

        // Load in the complex values from the E beam
        // at the supplied coordinate offsets.
        // Save the sum of abs in sum.real
        // and the sum of args in sum.imag
        bilinear_interpolate<T>(sum, abs_sum, E_beam, gl, gm, gchan,
            0.0f, 0.0f, 0.0f);
        bilinear_interpolate<T>(sum, abs_sum, E_beam, gl, gm, gchan,
            1.0f, 0.0f, 0.0f);
        bilinear_interpolate<T>(sum, abs_sum, E_beam, gl, gm, gchan,
            0.0f, 1.0f, 0.0f);
        bilinear_interpolate<T>(sum, abs_sum, E_beam, gl, gm, gchan,
            1.0f, 1.0f, 0.0f);

        bilinear_interpolate<T>(sum, abs_sum, E_beam, gl, gm, gchan,
            0.0f, 0.0f, 1.0f);
        bilinear_interpolate<T>(sum, abs_sum, E_beam, gl, gm, gchan,
            1.0f, 0.0f, 1.0f);
        bilinear_interpolate<T>(sum, abs_sum, E_beam, gl, gm, gchan,
            0.0f, 1.0f, 1.0f);
        bilinear_interpolate<T>(sum, abs_sum, E_beam, gl, gm, gchan,
            1.0f, 1.0f, 1.0f);

        // Determine the normalised angle
        typename Tr::ft angle = Po::arg(sum);

        // Take the complex exponent of the angle
        // and multiply by the sum of abs
        typename Tr::ct value;
        Po::sincos(angle, &value.y, &value.x);
        value.x *= abs_sum;
        value.y *= abs_sum;

        i = ((SRC*NTIME + TIME)*NA + ANT)*NPOLCHAN + POLCHAN;
        jones[i] = value;
        __syncthreads();
    }
}

extern "C" {

#define stamp_jones_E_beam_fn(ft,ct,lm_type,pe_type,as_type) \
__global__ void \
rime_jones_E_beam_ ## ft( \
    lm_type * lm, \
    pe_type * point_errors, \
    as_type * antenna_scaling, \
    ct * E_beam, \
    ct * jones, \
    ft parallactic_angle, \
    ft beam_ll, ft beam_lm, \
    ft beam_ul, ft beam_um) \
{ \
    rime_jones_E_beam_impl<ft>( \
        lm, point_errors, antenna_scaling, E_beam, jones, \
        parallactic_angle, beam_ll, beam_lm, beam_ul, beam_um); \
}

stamp_jones_E_beam_fn(float,float2,float2,float2,float2);
stamp_jones_E_beam_fn(double,double2,double2,double2,double2);

} // extern "C" {
""")

class RimeEBeam(Node):
    def __init__(self):
        super(RimeEBeam, self).__init__()

    def initialise(self, solver, stream=None):
        slvr = solver

        self.polchans = 4*slvr.nchan

        # Get a property dictionary off the solver
        D = slvr.get_properties()
        # Include our kernel parameters
        D.update(FLOAT_PARAMS if slvr.is_float() else DOUBLE_PARAMS)

        # Update kernel parameters to cater for radically
        # smaller problem sizes. Caters for a subtle bug
        # with Kepler shuffles and warp sizes < 32
        if self.polchans < D['BLOCKDIMX']: D['BLOCKDIMX'] = self.polchans
        if slvr.na < D['BLOCKDIMY']: D['BLOCKDIMY'] = slvr.na
        if slvr.nsrc < D['BLOCKDIMZ']: D['BLOCKDIMZ'] = slvr.nsrc

        regs = str(FLOAT_PARAMS['maxregs'] \
                if slvr.is_float() else DOUBLE_PARAMS['maxregs'])

        kname = 'rime_jones_E_beam_float' \
            if slvr.is_float() is True else \
            'rime_jones_E_beam_double'

        kernel_string = KERNEL_TEMPLATE.substitute(**D)

        self.mod = SourceModule(kernel_string,
            options=['-lineinfo','-maxrregcount', regs],
            include_dirs=[montblanc.get_source_path()],
            no_extern_c=True)

        self.kernel = self.mod.get_function(kname)
        self.launch_params = self.get_launch_params(slvr, D)

    def shutdown(self, solver, stream=None):
        pass

    def pre_execution(self, solver, stream=None):
        pass

    def get_launch_params(self, slvr, D):
        polchans_per_block = D['BLOCKDIMX']
        ants_per_block = D['BLOCKDIMY']
        srcs_per_block = D['BLOCKDIMZ']

        polchan_blocks = self.blocks_required(self.polchans, polchans_per_block)
        ant_blocks = self.blocks_required(slvr.na, ants_per_block)
        src_blocks = self.blocks_required(slvr.nsrc, srcs_per_block)

        return {
            'block' : (polchans_per_block, ants_per_block, srcs_per_block),
            'grid'  : (polchan_blocks, ant_blocks, src_blocks),
        }

    def execute(self, solver, stream=None):
        slvr = solver

        self.kernel(slvr.lm_gpu,
            slvr.point_errors_gpu, slvr.antenna_scaling_gpu,
            slvr.E_beam_gpu, slvr.jones_gpu,
            slvr.parallactic_angle,
            slvr.beam_ll, slvr.beam_lm,
            slvr.beam_ul, slvr.beam_um,
            stream=stream, **self.launch_params)

    def post_execution(self, solver, stream=None):
        pass