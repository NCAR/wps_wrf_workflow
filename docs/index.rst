====================AA
WPS and WRF Workflow
====================

This Python-based modular workflow is for configuring and running the
Weather Research and Forecasting Model (WRF) and the WRF Pre-Processing
System (WPS), and optionally, for post-processing programs like the
Unified Post Processor (UPP). Because of its modular nature, scripts to
do additional steps can easily be added if desired.

Before running this Python-based workflow, users need to complete the
following steps:

  * Have compiled versions of WRF and WPS available. Currently, WPS
    should be compiled with DMPar (Distributed-memory Parallelism),
    which means MPI will be used in the build.  Later updates may make this
    workflow compatible with serial-compiled WPS.
  * Create a template namelist.wps for WPS for the simulation domain(s).
  * Create a template namelist.input for WRF for the simulation.
  * Create template job submission scripts, one for each WPS/WRF executable.
  * Modify config/wps_wrf_config.yaml (or create one) with configuration
    options. If an experiment name is desired, add a line "exp_name: exp01"
    or similar. Some of the options include whether to run the various
    WPS/WRF executables, where the WPS/WRF installation and run directories
    are, and more.

The typical way to run the workflow is to execute this command:

.. code::

   ./setup_wps_wrf.py -b [cycle start date in YYYYMMDD_HH format] -c [/relative/path/to/wps_wrf_config.yaml]


Based on the cycle start date provided with the -b flag, combined with the
simulation duration settings provided in the YAML config file with the -c flag,
the workflow will automatically update the simulation start/end dates in the
WPS/WRF namelists.

A full usage statement with additional options can be seen by executing:

.. code::

   ./setup_wps_wrf.py -h

Keep in mind that any default settings for many of these parameters are overridden
if provided in the YAML config file that is passed to setup_wps_wrf.py.


.. toctree::
   :hidden:

   user_instructions.rst
