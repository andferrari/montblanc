# Montblanc

A PyCUDA implementation of the Radio Interferometry Measurement Equation, and a foothill of Mount Exaflop.

## License

Montblanc is licensed under the GNU GPL v2.0 License.

## Requirements

- PyCUDA 2013.1
- A Kepler NVIDIA GPU (probably)

## Installation

Pre-requisites must be installed and dependent C libraries built.

### Pre-requisites

You'll also need to install the [pyrap][pyrap] library, which is dependent on [casacore][casacore]. It may be easier to add the [SKA PPA][ska-ppa]  and get the binaries from there.

### Building the package

Run

    # python setup.py build

to build the package. The following:

    # python setup.py install

should install the package.

## Running Tests

Once the libraries have been compiled you should be able to run the

    # cd tests
    # python -c 'import montblanc; montblanc.test()'
    # python -m unittest test_biro_v2.TestBiroV2.test_biro_v2

which will run the current test suite or only the particular test case specified. The reported times are for the entire test case with numpy code, and not just the CUDA kernels.

If you're running on an ubuntu laptop with optimus technology, you may have to install bumblebee and run

    # optirun python -c 'import montblanc; montblanc.test()'

## Playing with a Measurement Set

You could also try run

    # cd examples
    # python MS_example.py /home/user/data/WSRT.MS -np 10 -ng 10 -c 100

which sets up things based on the supplied Measurement Set, with 10 point and 10 gaussian sources. It performs 100 iterations of the pipeline.

[pycuda]:http://mathema.tician.de/software/pycuda/
[pytools]:https://pypi.python.org/pypi/pytools
[moderngpu]:https://github.com/nvlabs/moderngpu
[cub]:https://github.com/nvlabs/cub
[pyrap]:https://code.google.com/p/pyrap/
[casacore]:https://code.google.com/p/casacore/
[ska-ppa]:https://launchpad.net/~ska-sa/+archive/main