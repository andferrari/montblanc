import collections
import copy
import threading
import types

import pyrap.tables as pt
import numpy as np
import hypercube as hc
import tensorflow as tf

class RimeDataFeeder(object):
    pass
    
class NumpyRimeDataFeeder(RimeDataFeeder):
    def __init__(self, arrays):
        pass

# Map MS column string types to numpy types
MS_TO_NP_TYPE_MAP = {
    'int' : np.int32,
    'float' : np.float32,
    'double' : np.float64,
    'boolean' : np.bool,
    'complex' : np.complex64,
    'dcomplex' : np.complex128
}

# Key names for main and taql selected tables
MAIN_TABLE = 'MAIN'
ORDERED_MAIN_TABLE = 'ORDERED_MAIN'
ORDERED_UVW_TABLE = 'ORDERED_UVW'

# Measurement Set sub-table name string constants
ANTENNA_TABLE = 'ANTENNA'
SPECTRAL_WINDOW_TABLE = 'SPECTRAL_WINDOW'
DATA_DESCRIPTION_TABLE = 'DATA_DESCRIPTION'
POLARIZATION_TABLE = 'POLARIZATION'

SUBTABLE_KEYS = (ANTENNA_TABLE,
    SPECTRAL_WINDOW_TABLE,
    DATA_DESCRIPTION_TABLE,
    POLARIZATION_TABLE)

# String constants for column names
TIME = 'TIME'
ANTENNA1 = 'ANTENNA1'
ANTENNA2 = 'ANTENNA2'
UVW = 'UVW'
DATA = 'DATA'
FLAG = 'FLAG'
WEIGHT = 'WEIGHT'

# Columns used in select statement
SELECTED = [TIME, ANTENNA1, ANTENNA2, UVW, DATA, FLAG, WEIGHT]

# Named tuple defining a mapping from MS row to dimension
OrderbyMap = collections.namedtuple("OrderbyMap", "dimension orderby")

# Mappings for time, baseline and band
TIME_MAP = OrderbyMap("ntime", "TIME")
BASELINE_MAP = OrderbyMap("nbl", "ANTENNA1, ANTENNA2")
BAND_MAP = OrderbyMap("nbands", "[SELECT SPECTRAL_WINDOW_ID "
        "FROM ::DATA_DESCRIPTION][DATA_DESC_ID]")

# Place mapping in a list
MS_ROW_MAPPINGS = [
    TIME_MAP,
    BASELINE_MAP,
    BAND_MAP
]

# Main measurement set ordering dimensions
MS_DIM_ORDER = ('ntime', 'nbl', 'nbands')
# UVW measurement set ordering dimensions
UVW_DIM_ORDER = ('ntime', 'nbl')
DUMMY_CACHE_VALUE = (-1, None)

def orderby_clause(*dimensions, **kwargs):
    columns = ", ".join(m.orderby for m
        in MS_ROW_MAPPINGS if m.dimension in dimensions)
    
    clause = ("ORDERBY",
        "UNIQUE" if kwargs.get('unique', False) else "",
        columns)

    return " ".join(clause)

def subtable_name(msname, subtable=None):
    return '::'.join((msname, subtable)) if subtable else msname

def open_table(msname, subtable=None):
    return pt.table(subtable_name(msname, subtable), ack=False)

class MSRimeDataFeeder(RimeDataFeeder):
    def __init__(self, msname):
        super(MSRimeDataFeeder, self).__init__()

        self._msname = msname
        # Create dictionary of tables
        self._tables = { k: open_table(msname, k) for k in SUBTABLE_KEYS }
        self._cube = cube = hc.HyperCube()

        # Open the main measurement set
        ms = open_table(msname)

        # Access individual tables
        ant, spec, ddesc, pol = (self._tables[k] for k in SUBTABLE_KEYS)

        # Sanity check the polarizations
        if pol.nrows() > 1:
            raise ValueError("Multiple polarization configurations!")

        npol = pol.getcol('NUM_CORR')

        if npol != 4:
            raise ValueError('Expected four polarizations')

        # Number of channels per band
        chan_per_band = spec.getcol('NUM_CHAN')

        # Require the same number of channels per band
        if not all(chan_per_band[0] == cpb for cpb in chan_per_band):
            raise ValueError('Channels per band {cpb} are not equal!'
                .format(cpb=chan_per_band))

        if ddesc.nrows() != spec.nrows():
            raise ValueError("DATA_DESCRIPTOR.nrows() "
                "!= SPECTRAL_WINDOW.nrows()")

        # Hard code auto-correlations and field_id 0
        auto_correlations = True
        field_id = 0

        # Create a view over the MS, ordered by
        # (1) time (TIME)
        # (2) baseline (ANTENNA1, ANTENNA2)
        # (3) band (SPECTRAL_WINDOW_ID via DATA_DESC_ID)
        ordering_query = " ".join((
            "SELECT {r} FROM $ms".format(r=", ".join(SELECTED)),
            "WHERE FIELD_ID={fid}".format(fid=field_id),
            "" if auto_correlations else "AND ANTENNA1 != ANTENNA2",
            orderby_clause(*MS_DIM_ORDER)
        ))

        # Ordered Measurement Set
        oms = pt.taql(ordering_query)
        # Measurement Set ordered by unique time and baseline
        otblms = pt.taql("SELECT FROM $oms {c}".format(
            c=orderby_clause(*UVW_DIM_ORDER, unique=True)))

        # Store the main table
        self._tables[MAIN_TABLE] = ms
        self._tables[ORDERED_MAIN_TABLE] = oms
        self._tables[ORDERED_UVW_TABLE] = otblms

        # Count distinct timesteps in the MS
        t_orderby = orderby_clause('ntime', unique=True)
        t_query = "SELECT FROM $otblms {c}".format(c=t_orderby)
        ntime = pt.taql(t_query).nrows()
        
        # Count number of baselines in the MS
        bl_orderby = orderby_clause('nbl', unique=True)
        bl_query = "SELECT FROM $otblms {c}".format(c=bl_orderby)
        nbl = pt.taql(bl_query).nrows()

        # Register dimensions on the cube
        cube.register_dimension('npol', npol,
            description='Polarisations')
        cube.register_dimension('nbands', len(chan_per_band),
            description='Bands')
        cube.register_dimension('nchan', sum(chan_per_band),
            description='Channels')
        cube.register_dimension('nchanperband', chan_per_band[0],
            description='Channels-per-band')
        cube.register_dimension('nrows', ms.nrows(),
            description='Main MS rows')
        cube.register_dimension('nuvwrows', otblms.nrows(),
            description='UVW sub-MS rows')
        cube.register_dimension('na', ant.nrows(),
            description='Antenna')
        cube.register_dimension('ntime', ntime,
            description='Timesteps')
        cube.register_dimension('nbl', nbl,
            description='Baselines')

        def _cube_row_update_function(self):
            # Update main measurement set rows
            shape = self.dim_global_size(*MS_DIM_ORDER)
            lower = self.dim_lower_extent(*MS_DIM_ORDER)
            upper = tuple(u-1 for u in self.dim_upper_extent(*MS_DIM_ORDER))

            self.update_dimension(name='nrows',
                lower_extent=np.ravel_multi_index(lower, shape),
                upper_extent=np.ravel_multi_index(upper, shape)+1)

            shape = self.dim_global_size(*UVW_DIM_ORDER)
            lower = self.dim_lower_extent(*UVW_DIM_ORDER)
            upper = tuple(u-1 for u in self.dim_upper_extent(*UVW_DIM_ORDER))

            self.update_dimension(name='nuvwrows',
                lower_extent=np.ravel_multi_index(lower, shape),
                upper_extent=np.ravel_multi_index(upper, shape)+1)

        self._cube.update_row_dimensions = types.MethodType(
            _cube_row_update_function, self._cube)

        # Temporary, need to get these arrays from elsewhere
        cube.register_array('uvw', ('ntime', 'na', 3), np.float64)
        cube.register_array('antenna1', ('ntime', 'nbl'), np.int32)
        cube.register_array('antenna2', ('ntime', 'nbl'), np.int32)
        cube.register_array('observed_vis', ('ntime', 'nbl', 'nchan', 'npol'), np.complex64)
        cube.register_array('weight', ('ntime', 'nbl', 'nchan', 'npol'), np.float32)
        cube.register_array('flag', ('ntime', 'nbl', 'nchan', 'npol'), np.bool)

        self._cache = {}

    @property
    def mscube(self):
        return self._cube
    
    def uvw(self, cube, array_descriptor):
        lrow = cube.dim_lower_extent('nuvwrows')

        # Attempt to return a cached value if possible
        cached_uvw = self._cache.get(UVW, DUMMY_CACHE_VALUE)
        if cached_uvw[0] == lrow:
            return cached_uvw[1]

        urow = cube.dim_upper_extent('nuvwrows')
        ntime, nbl, na = cube.dim_extent_size(
            'ntime', 'nbl', 'na')

        bl_uvw = self._tables[ORDERED_UVW_TABLE].getcol(UVW,
            startrow=lrow, nrow=urow-lrow).reshape(ntime, nbl, 3)

        ant_uvw = np.empty(shape=(ntime, na, 3),dtype=bl_uvw.dtype)
        ant_uvw[:,1:na,:] = bl_uvw[:,:na-1,:]
        ant_uvw[:,0,:] = 0

        self._cache[UVW] = (lrow, ant_uvw)
        
        return ant_uvw

    def antenna1(self, cube, array_descriptor):
        lrow = cube.dim_lower_extent('nuvwrows')

        cached_ant1 = self._cache.get(ANTENNA1, DUMMY_CACHE_VALUE)
        if cached_ant1[0] == lrow:
            return cached_ant1[1]

        urow = cube.dim_upper_extent('nuvwrows')
        antenna1 = self._tables[ORDERED_MAIN_TABLE].getcol(
            ANTENNA1, startrow=lrow, nrow=urow-lrow)

        self._cache[ANTENNA1] = (lrow, antenna1)
        return antenna1.reshape(array_descriptor.shape)

    def antenna2(self, cube, array_descriptor):
        lrow = cube.dim_lower_extent('nuvwrows')

        cached_ant2 = self._cache.get(ANTENNA2, DUMMY_CACHE_VALUE)
        if cached_ant2[0] == lrow:
            return cached_ant2[1]

        urow = cube.dim_upper_extent('nuvwrows')
        antenna2 = self._tables[ORDERED_MAIN_TABLE].getcol(
            ANTENNA2, startrow=lrow, nrow=urow-lrow)

        self._cache[ANTENNA2] = (lrow, antenna2)
        return antenna2.reshape(array_descriptor.shape)

    def observed_vis(self, cube, array_descriptor):
        lrow = cube.dim_lower_extent('nrows')
        urow = cube.dim_upper_extent('nrows')

        data = self._tables[ORDERED_MAIN_TABLE].getcol(
            DATA, startrow=lrow, nrow=urow-lrow)

        return data.reshape(array_descriptor.shape)

    def flag(self, cube, array_descriptor):
        lrow = cube.dim_lower_extent('nrows')
        urow = cube.dim_upper_extent('nrows')

        flag = self._tables[ORDERED_MAIN_TABLE].getcol(
            FLAG, startrow=lrow, nrow=urow-lrow)

        return flag.reshape(array_descriptor.shape)

    def weight(self, cube, array_descriptor):
        lrow = cube.dim_lower_extent('nrows')
        urow = cube.dim_upper_extent('nrows')
        nchan = cube.dim_extent_size('nchanperband')

        weight = self._tables[ORDERED_MAIN_TABLE].getcol(
            WEIGHT, startrow=lrow, nrow=urow-lrow)

        # WEIGHT is applied across all channels
        weight = np.repeat(weight, nchan, 0)
        return weight.reshape(array_descriptor.shape)

    def close(self):
        for table in self._tables.itervalues():
            table.close()

    def __enter__(self):
        return self

    def __exit__(self, etype, evalue, etraceback):
        self.close()

import argparse

parser = argparse.ArgumentParser()
parser.add_argument('msfile')
args = parser.parse_args()

feeder = MSRimeDataFeeder(args.msfile)
cube = copy.deepcopy(feeder.mscube)

row_iter_sizes = [10] + cube.dim_global_size('nbl', 'nbands')
dim_iter_args = zip(MS_DIM_ORDER, row_iter_sizes)

for dims in cube.dim_iter(*dim_iter_args, update_local_size=True):
    cube.update_dimensions(dims)
    cube.update_row_dimensions()
    arrays = cube.arrays(reify=True)

    # Passing in the arrays should be automated...
    ant1 = feeder.antenna1(cube, arrays['antenna1'])
    ant2 = feeder.antenna2(cube, arrays['antenna2'])
    uvw = feeder.uvw(cube, arrays['uvw'])
    observed_vis = feeder.observed_vis(cube, arrays['observed_vis'])
    flag = feeder.flag(cube, arrays['flag'])
    weight = feeder.weight(cube, arrays['weight'])

    print ant1.nbytes, ant2.nbytes, uvw.nbytes, observed_vis.nbytes, flag.nbytes, weight.nbytes