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

# List of source types and the variable names
# referring to the number of sources for that type
POINT_TYPE = 'point'
POINT_NR_VAR = 'npsrc'

GAUSSIAN_TYPE = 'gaussian'
GAUSSIAN_NR_VAR = 'ngsrc'

SERSIC_TYPE = 'sersic'
SERSIC_NR_VAR = 'nssrc'

# Type to numbering variable mapping
SOURCE_VAR_TYPES = {
    POINT_TYPE : POINT_NR_VAR,
    GAUSSIAN_TYPE : GAUSSIAN_NR_VAR,
    SERSIC_TYPE : SERSIC_NR_VAR
}