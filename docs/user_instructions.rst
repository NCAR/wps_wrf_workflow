*****************
User Instructions
*****************

Running the Workflow on NSF NCAR HPCs
=====================================

This section walks a new user through the end-to-end steps required to configure
and execute the `WPS WRF Workflow <https://github.com/NCAR/wps_wrf_workflow>`_
on NSF NCAR's Casper or Derecho HPC Systems. This workflow should also work on
any other HPC system that has either a PBS or Slurm queue scheduler.


Prerequisites
-------------

Access and Permissions
^^^^^^^^^^^^^^^^^^^^^^

* Login credentials for Casper or Derecho (e.g., via
  :code:`ssh username@casper.hpc.ucar.edu`)

* Valid PBS project/account codes (e.g., :code:`#PBS -A NWS####`)

* Write permissions on scratch/project directories for workflow outputs
  and downloaded data

Local Tools
^^^^^^^^^^^

* :code:`git` for cloning the repo

* :code:`conda` (or module) to activate a Python 3.11 environment

* PBS commands: :code:`qsub`, :code:`qstat`, :code:`qdel`

Clone the Repository
--------------------

.. code-block::

   git clone git@github.com:NCAR/wps_wrf_workflow.git
   cd wps_wrf_workflow

Configure the Workflow
----------------------

Main YAML Configuration
^^^^^^^^^^^^^^^^^^^^^^^

1. Enter the config directory:

   .. code-block::

      cd config

2. Open the FastEddy New Mexico config:

   .. code-block::

      vim config_fasteddy_nm.yaml

3. Key fields to update:

   * :code:`template_dir`: Path to :code:`../templates/fasteddy_nm` in a
     local clone, so that the workflow picks up the user's edits to template
     namelists, job submission scripts, etc.

   * :code:`exp_name`: Optional. Add/modify this field if you want to give this
     simulation an experiment name (e.g., if using different IC/LBC models or
     testing different WRF namelist options). (Default: :code:`None`)

   * :code:`exp_wrf_only`: Optional. If :code:`exp_name` is set but you only want the
     experiment name to apply to real/WRF while using the same metgrid output
     (:code:`met_em*` files) for all experiments (e.g., if only WRF namelist options
     are being changed), then set this to :code:`True`. (Default: :code:`False`.)

   * :code:`wps_ins_dir` and :code:`wrf_ins_dir`: Directories where WPS and
     WRF are installed; defaults can remain if they are read-accessible.
     (Default values: :code:`/glade/u/home/jaredlee/programs/WPS-4.6-dmpar`
     and :code:`/glade/u/home/jaredlee/programs/WRF-4.6`, respectively.)

     .. note::
	
       Currently the workflow assumes WPS is compiled for :code:`dmpar` execution,
       not :code:`serial`, in order to speed up the WPS programs (and on NSF NCAR
       HPCs, it should be compiled on Casper, not Derecho, while WRF should
       be compiled on Derecho, not Casper).

   * :code:`wps_run_dir` and :code:`wrf_run_dir`: Scratch or project paths
     that are write-accessible. The workflow will create subdirectories
     automatically. NOTE: These must be updated from the defaults in the repo.

   * :code:`grib_dir`: Location to store downloaded HRRR GRIB2 files. This
     location must be a path that is write-accessible by the user and should be 
     updated from the default value.

   * :code:`sim_hrs`: Total simulation length in hours (e.g., :code:`30`). This
     value drives how most subsequent steps run. (Default value: :code:`24`.)

   * :code:`do_geogrid`: Set to :code:`True` to run geogrid; if
     geogrid outputs are already available (e.g., from a colleague), set to :code:`False`.  
     Ensure :code:`opt_output_from_geogrid_path` in
     :code:`namelist.wps` template(s) points to correct geogrid output location.
     (Default value: :code:`False`.)

   * :code:`ungrib_domain`: :code:`full` ungribs the complete GRIB file domain
     (for HRRR this is CONUS, while for GFS and GEFS this is global). The option
     :code:`subset` is available only for GEFS output currently, to
     geographically subset GEFS output to some smaller domain to enable
     :code:`ungrib.exe` to run faster, which may be helpful in operational
     configurations (this optional setting could be added in the future for
     GFS or other IC/LBC model sources, though). (Default value: :code:`full`.)

   * :code:`icbc_model` and :code:`icbc_source`:

     * :code:`icbc_model`: e.g., :code:`hrrr`: :code:`gfs`: :code:`gfs-fnl`: :code:`gefs`:. 
       The script is tolerant to all-lowercase or all-caps entries here. (Default value:
       :code:`GFS`.)

     * :code:`icbc_source`: :code:`AWS` or :code:`GoogleCloud` to dowload from AWS or
       GoogleCloud HRRR repositories, or :code:`GLADE` to link to local RDA archive
       files (GLADE/RDA respositories are available for :code:`gfs` and :code:`gfs-fnl`
       but not for :code:`hrrr`: or :code:`gefs`:). Also note that :code:`icbc_source`
       can tolerate all-caps or all-lowercase entries for both :code:`AWS` and
       :code:`GoogleCloud`, in addition to camel-case for :code:`GoogleCloud`. (Default
       value: :code:`GLADE`.)

   * :code:`icbc_analysis`: :code:`True` to initialize from the analysis (forecast
     hour 0) files from successive initial condition/lateral boundary condition (IC/LBC) model
     cycles (NOTE: this can only be done retrospectively, and should provide the best-possible
     ICs/LBCs); :code:`False`: to initialize from forecast files from a single IC/LBC model cycle. 
     (Default value: :code:`False`.)

   * :code:`icbc_fc_dt`: Normally set to :code:`0`. If set to some other positive
     integer N, then ICs/LBCs are obtained from an N-hour old cycle of the
     :code:`icbc_model`. (That situation may be useful to stay ahead of the clock
     in operational forecast systems.) (Default value: :code:`0`.)

   * :code:`get_icbc`: :code:`True` to download or create symbolic links to model
     data to use as ICs/LBCs. If the specified files already exist locally where
     expected, then nothing is re-downloaded or re-linked. (Default value: :code:`False`.)

   * :code:`hrrr_native`: :code:`True` to download the HRRR native (hybrid)-level
     files for atmospheric variables and pressure-level files for soil variables
     only (HRRR native-level files have more vertical levels [51] than
     pressure-level files [40] but do not include soil variables). :code:`False`
     to download only the HRRR pressure-level files for both atmospheric and
     soil variables. Has no effect if :code:`icbc_model` is set to something
     other than :code:`hrrr`. (Default value: :code:`True`.)

   * :code:`do_geogrid`, :code:`do_ungrib`, :code:`do_metgrid`, :code:`do_real`,
     :code:`do_wrf`: Control each WPS/WRF step. Geogrid is a one-time domain setup;
     Ungrib/Metgrid/Real need to be run for each WRF forecast cycle (and
     potentially also for different WRF configurations for the same WRF cycle,
     depending on what is different). (Default values: :code:`False` for all.)

   * :code:`do_avg_tsfc`: If :code:`True`, runs a WPS utility (:code:`avg_tsfc.exe`)
     that calculates a 24-hour average surface temperature to better estimate
     lake-surface temps (avoiding interpolation from oceans, which can result in
     wildly inaccurate surface temperatures for inland lakes). This step is run
     after Ungrib but before Metgrid. If the output file (TAVGSFC) has already
     been generated from a previous attempt to run the workflow for this WRF cycle/
     experiment, then set this to :code:`False` to save a few minutes. (Default
     value: :code:`False`.)

   * :code:`use_tavgsfc`: :code:`True` to use the output from the :code:`avg_tsfc.exe`
     utility (a file called TAVGSFC) in Metgrid. This will add the appropriate line
     to the :code:`&metgrid` section of :code:`namelist.wps` if it does not already
     exist. (Default value: :code:`False`.)

   * :code:`archive`: When :code:`True`, the workflow automatically moves all output
     (namelists, wrfout*, logs) into an archival directory (set :code:`arc_dir` to a
     write accessible directory) for easy retrieval. (Default value: :code:`False`.)

   * :code:`realtime`: When :code:`True` while :code:`run_wrf = True`, the workflow
     will hold after submitting WRF and monitor the progress of the WRF job, and not
     move on to the next step of the workflow or the next model cycle until WRF completes
     successfully. If :code:`realtime = False` while :code:`run_wrf = True`, then the
     workflow will move to the next step or model cycle immediately after submitting WRF
     to the queue, without waiting to monitor its status, progress, or success. If
     :code:`run_wrf = False`, then :code:`realtime` has no effect. (Default value: :code:`False`.)

All other fields can remain at their default values unless specialized
cases arise.


Using Time-Varying (GEOS-5) or Climatological Aerosols with mp_phys=28
----------------------------------------------------------------------
This section provides some brief instructions for users who wish to use the Thompson-Eidhammer
aerosol-aware microphysics scheme in WRF (:code:`mp_phys=28`), whether with climatological
aerosols or with time-varying aerosols from GEOS-5. These instructions presume the user is
using WRF 4.4+, which is when the GEOS-5 and black carbon aerosol capabilities were added.
These instructions are intended to complement helpful information already posted at
https://www2.mmm.ucar.edu/wrf/users/physics/mp28_updated_new.html and at
https://github.com/wrf-model/WRF/pull/1616.

**1. Thompson-Eidhammer climatological aerosol**

The workflow does not require any special variables to be set in the config yaml file.
The only settings to choose this option would come in the template WPS & WRF namelists.

* In :code:`namelist.wps`, set this in the template namelist (assuming Derecho/Casper):

::

   &metgrid
     constants_name = '/glade/work/wrfhelp/WPS_files/QNWFA_QNIFA_QNBCA_SIGMA_MONTHLY.dat',

* In :code:`namelist.input`, ensure you have these settings in the template namelist:

::

   &time_control
     [any options for auxinput15 or auxinput17 should be commented or removed]

   &domains
     wif_input_opt     = 2,
     num_wif_levels    = 30,

   &physics
     mp_physics        = 28, 28, 28,
     aer_opt           = 3,
     use_aero_icbc     = .true.,
     use_rap_aero_icbc = .false.,
     wif_fire_emit     = .false.,
     qna_update        = 0,

**2. GEOS-5 time-varying aerosols**

Using this option presumes that the :code:`geos2wrf` software has already been utilized to
process GEOS-5 global files (which are in NetCDF from NASA) into regional files in WPS
Intermediate Format, with the variables that are expected to be found by Metgrid, Real, and WRF,
as detailed in: https://github.com/wrf-model/WRF/pull/1616. A link to the :code:`geos2wrf`
Github repository will be posted here after that repo becomes publicly available.

There are some settings in the config yaml file that are required, but first, these are the
settings in the template WPS & WRF namelists that should be set prior to running the workflow:

* In :code:`namelist.wps`, set something like this in the template namelist:

::

   &metgrid
     fg_name = '/glade/derecho/scratch/jaredlee/ipc/wps/20170301_00/ungrib/GFS_FNL',’/glade/derecho/scratch/jaredlee/ipc/wps/20170301_00/ungrib/GEOS',


Note the user should **not** supply :code:`QNWFA_QNIFA_QNBCA_SIGMA_MONTHLY.dat` in
:code:`constants_name` when using GEOS-5 aerosols, as that file is for the aerosol climatology.

* In :code:`namelist.input`, ensure you have these settings in the template namelist:

::

   &time_control
     [any options for auxinput15 commented or deleted]
     auxinput17_inname     = "wrfqnainp_d0*",
     auxinput17_interval_m = 180, 180, 180,
     io_form_auxinput17    = 2,

   &domains
     wif_input_opt     = 2,
     num_wif_levels    = 72,

   &physics
     mp_physics        = 28, 28, 28,
     aer_opt           = 3,
     use_aero_icbc     = .false.,
     use_rap_aero_icbc = .true.,
     wif_fire_emit     = .true.,
     qna_update        = 1,


* In addition, these options in the config yaml file need to be considered:

  *  :code:`use_geos5_aero_fcst`: :code:`True` to use time-varying aerosol data from
     GEOS-5 forecasts in Metgrid, for use with the Thompson-Eidhammer aerosol-aware
     microphysics scheme in WRF v4.4+ (:code:`mp_phys=28`). These GEOS-5 data files
     must already be in WPS Intermediate Format. This option will add the appropriate
     line/entry to the :code:`&metgrid` section of :code:`namelist.wps` if it does not
     already exist. (Default value: :code:`False`.)

  *  :code:`use_geos5_aero_anal`: :code:`True` to use time-varying aerosol data from
     GEOS-5 analyses in Metgrid, for use with the Thompson-Eidhammer aerosol-aware
     microphysics scheme in WRF v4.4+ (:code:`mp_phys=28`). These GEOS-5 data files
     must already be in WPS Intermediate Format. This option will add the appropriate
     line/entry to the :code:`&metgrid` section of :code:`namelist.wps` if it does not
     already exist. (Default value: :code:`False`.)

  *  :code:`geos5_int_dir`: String specifying the path of the parent directory where
     the GEOS-5 time-varying aerosol data in WPS Intermediate Format are stored. This
     option is only used if :code:`use_geos5_aero_fcst` or :code:`use_geos5_aero_anal`
     are set to :code:`True`. (Default value: :code:`None`.)


Edit Template Files
-------------------

1. Move into the FastEddy template directory:

   .. code-block::

      cd ../templates/fasteddy_nm

2. Update Account in Submit Scripts:

   * Open each PBS script (e.g., :code:`submit_geogrid.bash.casper`, :code:`submit_ungrib.bash.casper`,
     etc.) and specify the desired user account to charge for core hours:
   
   .. code-block::

      #PBS -A <user_account_code>

   * The user may also wish to adjust the number of nodes and cores per node requested in some of these submit scripts
     based on runtime, core hour charges, etc.:

   .. code-block::

      #PBS -l select=<# of nodes>:ncpus=<# of CPUs per node>:mpiprocs=<# of MPI processes per node>
      [snip]
      mpiexec -n <# of nodes * CPUs per node> ./wrf.exe

3. Modify :code:`namelist.wps.hrrr`:
 
   * :code:`opt_output_from_geogrid_path`:

   .. code-block::

      opt_output_from_geogrid_path = "/path/to/geogrid_output"

   * :code:`&ungrib` section:

   .. code-block::

      prefix = "/path/to/ungrib_output/<CYCLE>/ungrib/HRRR"

   * Note: Workflow will create :code:`.../ungrib_output/<CYCLE>/hybrid` and
     :code:`.../<CYCLE>/soil` subdirectories automatically if needed.

   * :code:`&metgrid` section:

     .. code-block::

	fg_name = "/path/to/ungrib_output/<CYCLE>/ungrib/HRRR_hybr", "/path/to/ungrib_output/CYCLE/ungrib/HRRR_soil",
	opt_output_from_metgrid_path = "/path/to/metgrid_output/<CYCLE>/metgrid"

   * If using your own WPS installation, then the user should also update these variables:

     .. code-block::

        opt_geogrid_tbl_path = '/path/to/WPS_install/geogrid',
        opt_metgrid_tbl_path = '/path/to/WPS_install/metgrid',

Directories specified above need write access; the control script will :code:`mkdir -p` as
needed and update :code:`<CYCLE>` in these namelist variables automatically.
	
Python Environment Setup
------------------------

1. Activate Python 3.11:

   .. code-block::

      conda activate /glade/work/jaredlee/conda-envs/my-npl-202403

2. Verify dependencies:

   .. code-block::

      pip install -r environment.yml
      # or ensure 'yaml', 'netCDF4', 'numpy', 'pandas', etc., import without errors

3. Dependencies are declared in `environment.yml <https://github.com/NCAR/wps_wrf_workflow/blob/main/environment.yml>`_,
   which is based on NSF NCAR's NPL 2024a stack plus extras.

Running the Workflow
--------------------

From the repository root:

.. code-block::

   # Display usage/help
   python setup_wps_wrf.py -h

   # Execute workflow for one cycle
   python setup_wps_wrf.py \
   -b 20250324_00 \
   -c config/config_fasteddy_nm.yaml

* :code:`-b YYYYMMDD_HH`: Start cycle (e.g., :code:`20250324_00`)
      
* :code:`-c`: Workflow config YAML path (can be a relative path from :code:`setup_wps_wrf.py`)

**Automatic Directory Creation**: The Python scripts will create all parent directories for
:code:`geogrid`, :code:`ungrib`, :code:`metgrid`, etc., based on the configured paths.
      
Workflow Execution Details
--------------------------

For running :code:`geogrid.exe`, :code:`ungrib.exe`, :code:`metgrid.exe`, :code:`real.exe`,
and :code:`wrf.exe`, batch job submission scripts are needed to submit them to the HPC queue.
If running on a non-NSF NCAR HPC system, users will need the following submission script
files in :code:`template_dir`:

* :code:`submit_geogrid.bash`
* :code:`submit_ungrib.bash`
* :code:`submit_metgrid.bash`
* :code:`submit_real.bash`
* :code:`submit_wrf.bash`

However, if users are running on NSF NCAR HPCs (Casper and/or Derecho), WPS needs to be
compiled on Casper (whose queue allows for single-core jobs without reserving an entire node),
while WRF needs to be compiled on Derecho (whose queues require reserving an entire
128-core node even if only 1 core is used). Set :code:`wps_ins_dir` and :code:`wrf_ins_dir`
to point to those installation directories. Both Derecho and Casper allow peer scheduling
to queues on either machine from either machine (see:
`Peer Scheduling scheduling between systems <Peer Scheduling scheduling between systems>`_
for more information). To enable  transparent-to-the-user execution  of the entire workflow
from a login node on either Casper or Derecho, two sets of files are needed. If executing the
workflow on Casper, these files need to be in :code:`template_dir`, with the
:code:`submit_real` and :code:`submit_wrf` scripts including the required syntax to submit
to a queue on Derecho from Casper:

* :code:`submit_geogrid.bash.casper`
* :code:`submit_ungrib.bash.casper`
* :code:`submit_metgrid.bash.casper`
* :code:`submit_real.bash.casper`
* :code:`submit_wrf.bash.casper`

If executing the workflow on Derecho, then these files need to be in :code:`template_dir`,
with the :code:`submit_geogrid`, :code:`submit_ungrib`, and :code:`submit_metgrid` scripts
including the required syntax to submit to a queue on Casper from Derecho: 

* :code:`submit_geogrid.bash.derecho`
* :code:`submit_ungrib.bash.derecho`
* :code:`submit_metgrid.bash.derecho`
* :code:`submit_real.bash.derecho`
* :code:`submit_wrf.bash.derecho`

The workflow will automatically copy the appropriate submission script template to the run
directories and strip the :code:`.casper` or :code:`.derecho` file name suffix if they exist.

Additionally, note that in :code:`template_dir` the namelist templates must have suffixes
corresponding to :code:`icbc_model`, to enable WRF experiments that can utilize different
models for the ICs/LBCs. This is done because there are typically different numbers of soil
or atmospheric levels in each model’s output, which requires different values for certain
namelist settings, and to not over-complicate the workflow scripts with lots of
if/then loops to handle model-specific changes to namelist variables that might be further
complicated with future updates to those external models, the number of output levels, or
other key parameters. For example, if a user wants to be able to run WRF driven by 
GFS, GFS-FNL, or HRRR output, the user would need these files in :code:`template_dir`:

* :code:`namelist.input.gfs`
* :code:`namelist.input.gfs-fnl`
* :code:`namelist.input.hrrr`
* :code:`namelist.wps.gfs`
* :code:`namelist.wps.gfs-fnl`
* :code:`namelist.wps.hrrr`

Note that users only need to have the template files corresponding to the desired :code:`icbc_model`
variants that they would like to be available to use.

If users use HRRR model output as ICs/LBCs for WRF, note that the number of vertical levels
is different in the native (hybrid)-level output (51) than in the pressure-level output
(40). Therefore, if users want the flexibility to run with either native/hybrid or
pressure-level HRRR output, then two different template WRF namelists in :code:`template_dir`
are needed:

* :code:`namelist.input.hrrr.hybr`
* :code:`namelist.input.hrrr.pres`

If users do not have either of these files, the workflow defaults to using :code:`namelist.input.hrrr`,
which then may cause an error when :code:`real.exe` is run if the wrong value for
:code:`num_metgrid_levels` is specified in :code:`namelist.input.hrrr` for the type of HRRR output.
  
Note that if the user only intends to run with ONLY hybrid-level or ONLY pressure-level HRRR output,
then the user will only need to have :code:`namelist.input.hrrr` present; just ensure that the correct
value for :code:`num_metgrid_levels` is set in :code:`namelist.input.hrrr`.

Also note that for the WPS and WRF namelists, this workflow does NOT generate grid/domain information
from scratch or from any user inputs. The user is required to specify the grid/domain details in
advance in these namelist template files. If the expected template namelist files do not exist prior
to running the workflow, then the workflow will fail. Other tools already exist for setting grid/domain
configurations for WPS and WRF namelists, such as
`WRF Domain Wizard <https://jiririchter.github.io/WRFDomainWizard/>`_. Future updates to the workflow
may add the capability to specify domain configuration details in a YAML file to automatically update 
the WPS and WRF namelists.

One final note: If the user desires to control which variables are written out to history streams,
then there should also be a file (or multiple file names separated by commas, which could be the
same or unique for each domain) set by the user in the :code:`&time_control` section of
:code:`namelist.input.{icbc_model}`, such as:

.. code-block::

   iofields_filename = “vars_io.txt”,

Any files listed on that line should be stored in :code:`template_dir`. If any requested files are
not found in :code:`template_dir`, the workflow will log a warning, and WRF will still run, but
then the default output variables for the specified stream(s) in the file will be written out
for that domain. For more information on this file and its required syntax, see the
`WRF Model README.io_config <https://github.com/wrf-model/WRF/blob/master/doc/README.io_config>`_
file.

1. **ICBC Download/Link**:

   * Downloads IC/LBC files from a web server or links to them in a local repository. For example, if 
     :code:`icbc_model = hrrr` and :code:`hrrr_native = True`, then :code:`download_hrrr_from_aws.py`  
     downloads HRRR native-grid (:code:`hrrr.YYYYMMDD/CONUS/hrrr.tHHz.wrfnatf00.grib2`) then pressure-grid 
     (:code:`wrfprs`) files for each hour in the requested simulation.

   * Skips download/linking if files already exist locally (useful for repeated runs).

2. **Ungrib**:

   * Ungrib is inherently serial; the workflow subdivides it per hour and runs 2×N jobs (hybrid and
     soil, if using HRRR native-grid files) or N jobs (for all other IC/LBC models) to make it 
     embarrassingly parallel. Ungrib is run separately as a 1-core job for each :code:`icbc_model` 
     file in its own directory to avoid :code:`ungrib.exe` cleanup processes that delete all files matching 
     a starting pattern, which often causes “file not found” errors when running multiple instances 
     of :code:`ungrib.exe` simultaneously within the same directory.

   * Includes a short :code:`sleep` (1–3 s) between :code:`qsub` calls to avoid
     overloading the PBS queue.

   * WPS intermediate format files (:code:`YYYYMMDD_HH/ungrib/HRRR_hybrid*`, :code:`*HRRR_soil*`)
     move into a combined :code:`ungrib/` directory once complete.

3. **Geogrid**:

   * Domain setup; runs once per domain. Subsequent simulations using the same domain can skip by setting
     :code:`do_geogrid: False`.

4. **avg_tsfc**:

   * Calculates a 24-h average surface temperature field to improve lake-surface
     temps in land masks. Ignores times outside whole 24-h periods by default.

5. **Metgrid**:

   * Uses :code:`ungrib` (and optionally :code:`avg_tsfc`) outputs to produce
     NetCDF files on the WRF horizontal grid but on the vertical levels from the
     ungribbed WPS intermediate format file.

6. **Real**:

   * Takes output from metgrid (:code:`met_em_d0*` files) and puts it onto the full 
     3D WRF grid to generate initial-time (:code:`wrfinput_d0*`), lateral boundary 
     condition (:code:`wrfbdy_d01`), and (optionally) lower boundary condition 
     (:code:`wrflowinp_d0*`) files that span the requested simulation time.

   * Submits via :code:`qsub submit_real.bash`; monitors job status.

   * Logs for every processor executing real.exe will appear in :code:`rsl.out.*` and 
     :code:`rsl.error.*` files. Note that WRF writes logs to the same file names, 
     so these will be overwritten unless moved elsewhere.

7. **WRF**:

   * Submits WRF model via :code:`qsub submit_wrf.bash`; monitors job status.

   * If a user types :code:`CTRL+C`, WRF continues running on the compute
     nodes; logs and :code:`wrfout*` files appear in the :code:`wrf/`
     subdirectory. Otherwise, the workflow will monitor the WRF simulation's
     progress, and only exit upon finding an error or success message in the
     log files. A future update will clarify how to move on to the next WPS/WRF
     cycle after submitting WRF, without waiting to monitor the WRF job.
      
Monitoring and Troubleshooting
------------------------------

* **Log Locations**: Each step (:code:`geogrid/`, :code:`ungrib/`,
  :code:`metgrid/`, :code:`real/`, :code:`wrf/`) has its own :code:`*.log` files
  (or :code:`rsl.*` files for :code:`real.exe` and :code:`wrf.exe`). Currently, the 
  workflow scripts only look for key phrases to indicate success or failure of the job, 
  and does not analyze the error messages to provide hints about what might be wrong. 
  Future enhancements to the workflow could include such helpful hints, though. The
  `WRF & MPAS-A Forum <https://forum.mmm.ucar.edu/>`_ is a useful resource to consult 
  for WPS & WRF troubleshooting issues.

* **Inspecting Jobs**:

  .. code-block::

     qstat -u $USER       # List running PBS jobs
     tail -f wrf/logs/metgrid.log  # Follow metgrid progress

* **Common Errors**:

  * **Error in ext_pkg_open_for_write_begin**: Write-permission error on
    output path - verify :code:`wps_run_dir` and template prefixes.

  * **Missing Python modules**: Ensure the Python 3.11 environment with
    required packages has been activated.

  * **Slurm vs PBS scripts**: A warning :code:`check_job_status.sh` references
    Slurm; it can be ignored or updated for PBS compatibility.

Reviewing Output
----------------

* **Data Directory**: For example for HRRR, :code:`data/hrrr/hrrr.YYYYMMDD/conus/` for raw GRIB2 files for ICs/LBCs.

* **Workflow Directory**:

  * :code:`ungrib/`, :code:`geogrid/`, :code:`metgrid/` subfolders within :code:`wps_run_dir/YYYYMMDD_HH/`

  * Log files, :code:`wrfinput*`, :code:`wrfbdy`, and :code:`wrfout*` files within `wrf_run_dir/YYYYMMDD_HH/`

* **Archive**: If :code:`archive: True`, all run artifacts move to
  :code:`arc_dir/YYYYMMDD_HH/` upon completion.
