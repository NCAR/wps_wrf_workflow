#!/usr/bin/env python3

"""
setup_wps_wrf.py

Written by: Jared A. Lee (jaredlee@ucar.edu)
Written on: 31 Mar 2023
Other contributors: Bill Petzke, Paddy McCarthy

This script links to (and downloads, if necessary) all the files needed to run WPS/WRF on Casper/Derecho.
Each program in the WPS/WRF workflow can be optionally executed.
WRF output files can also be optionally moved to an archival directory (arc_dir).
"""

import os
import sys
import argparse
import pathlib
import datetime as dt
import pandas as pd
import logging
import yaml
import subprocess
import glob
import socket
from argparse import RawTextHelpFormatter

from pandas.io.common import file_path_to_url

from proc_util import exec_command

this_file = os.path.basename(__file__)
logging.basicConfig(format=f'{this_file}: %(asctime)s - %(message)s',
                    level=logging.DEBUG, datefmt='%Y-%m-%dT%H:%M:%S')
log = logging.getLogger(__name__)

def parse_args():
    yaml_config_help = {
     'cycle_int_h': 'integer number of hours between forecast cycles, if cycle_beg_dt and cycle_end_dt are different (default: 24)',
     'sim_hrs': 'integer number of hours for WRF simulation (default: 24)',
     'icbc_fc_dt': 'integer number of hours prior to WRF cycle time for IC/LBC model cycle (default: 0)',
     'exp_name': 'experiment name (e.g., exp01, mem01, etc.) (default: None)',
     'exp_wrf_only': 'if setting exp_name, should that apply only to real/wrf and use a single common WPS setup? (default: False)',
     'realtime': 'flag when running in real-time to keep this script running until WRF is done',
     'archive': 'flag to archive wrfout, wrfinput, wrfbdy, and namelist files to another location',
     'icbc_model': 'string specifying the model to be used for ICs/LBCs (default: GEFS)',
     'icbc_source': 'string specifying the repository from which to obtain ICs/LBCs (GLADE, AWS, GoogleCloud, NOMADS) (default: GLADE)',
     'icbc_analysis': 'flag to use analysis [f00] files for ICs/LBCs instead of forecasts from a single cycle (default: False)',
     'hrrr_native': 'flag to download HRRR native-grid atmospheric data for ICs/LBCs (default: True)',
     'grib_dir': 'string or Path object specifying the parent directory for where grib/grib2 input data (e.g., GEFS, GFS, etc.) is downloaded for use by ungrib (default: /glade/derecho/scratch/jaredlee/data)',
     'geos5_int_dir': 'string or Path object specifying the parent directory for where GEOS-5 aerosol data in WPS Intermediate Format is stored (default: None)',
     'use_geos5_aer_fcst': 'flag to use time-varying aerosol data from GEOS-5 forecasts (default: False)',
     'use_geos5_aer_anal': 'flag to use time-varying aerosol data from GEOS-5 analyses (default: False)',
     'ungrib_domain': 'string (either "full" or "subset") indicating whether to run ungrib on full-domain or geographically-subsetted grib/grib2 files (default: full)',
     'wps_ins_dir': 'string or Path object specifying the WPS installation directory (default: /glade/u/home/jaredlee/programs/WPS-4.6-dmpar)',
     'wrf_ins_dir': 'string or Path object specifying the WRF installation directory (default: /glade/u/home/jaredlee/programs/WRF-4.6)',
     'wps_run_dir': 'string or Path object specifying the parent WPS run directory (default: /glade/derecho/scratch/jaredlee/workflow/wps)',
     'wrf_run_dir': 'string or Path object specifying the parent WRF run directory (default: /glade/derecho/scratch/jaredlee/workflow/wrf)',
     'template_dir': 'string or Path object specifying the directory containing templates for sbatch submission scripts and WPS/WRF namelists (default: /glade/work/jaredlee/workflow/templates)',
     'arc_dir': 'string or Path object specifying the parent directory where WRF output should be archived (default: /glade/work/jaredlee/workflow)',
     'upp_yaml': 'string or Path object specifying the config file for the "run_upp" task.',
     'upp_domains': 'list of wrfout domain indices to process with UPP (default: [empty list | 0] to process all wrfout files)',
     'upp_working_dir': 'string or Path object that hosts subdirectories where each of the individual UPP processes is run (default: /tmp/upp)',
     'get_icbc':    'flag to download/link to IC/BC grib data',
     'do_geogrid':  'flag to run geogrid for this case',
     'do_ungrib':   'flag to run ungrib for this case',
     'do_avg_tsfc': 'flag to run avg_tsfc for this case (for improved lake SSTs)',
     'use_tavgsfc': 'flag to use an already-existing TAVGSFC file for this case (for improved lake SSTs)',
     'do_metgrid':  'flag to run metgrid for this case',
     'do_real':     'flag to run real for this case',
     'do_wrf':      'flag to submit wrf for this case',
     'do_upp':      'flag to perform UPP post-processing to grib2 for this case',
     #Add new parameters here
    }

    ## Parse the command-line arguments
    parser = argparse.ArgumentParser(formatter_class=RawTextHelpFormatter)
    parser.add_argument('-b', '--cycle_dt_beg', required=True, help='beginning date/time of first WRF simulation [YYYYMMDD_HH] (default: 20220801_00)')
    parser.add_argument('-e', '--cycle_dt_end', required=False, default=None, help='beginning date/time of last WRF simulation [YYYYMMDD_HH], if wanting to run a series of WRF simulations (default: None)')
    parser.add_argument('-c', '--config', required=True, help=f"yaml configuration file\n{yaml.dump(yaml_config_help, default_flow_style=False)}")
    
    args = parser.parse_args()
    cycle_dt_beg = args.cycle_dt_beg
    cycle_dt_end = args.cycle_dt_end

    if len(cycle_dt_beg) != 11 or cycle_dt_beg[8] != '_':
        log.error('ERROR! Incorrect format for argument cycle_dt_beg. Exiting!')
        parser.print_help()
        sys.exit(1)

    if cycle_dt_end != None:
        if len(cycle_dt_end) != 11 or cycle_dt_end[8] != '_':
            log.error('ERROR! Incorrect length for argument cycle_dt_end. Exiting!')
            parser.print_help()
            sys.exit(1)
    else:
        cycle_dt_end = cycle_dt_beg

    # Get the hostname. If an NCAR HPC machine (derecho or casper), then we can link to IC/LBC data on GLADE.
    # As derecho and casper allow cross-submitting jobs, then the appropriate PBS job script can be selected,
    # which would allow users to seamlessly run this workflow on either derecho or casper.
    hostname = socket.gethostname()
    # Simplify the hostnames for derecho & casper, which have a single numeral as the final character.
    # If other hostnames in the future need to be simplified similarly, add another elif branch here.
    if hostname[0:-1] == 'derecho':
        hostname = 'derecho'
    elif hostname[0:-1] == 'casper-login':
        hostname = 'casper'

    with open(args.config) as yaml_f:
        params = yaml.safe_load(yaml_f)
    log.info(f"yaml params: {params}")
    params.setdefault('cycle_int_h',24)
    params.setdefault('sim_hrs', 24)
    params.setdefault('icbc_fc_dt',0)
    params.setdefault('exp_name', None)
    params.setdefault('exp_wrf_only', False)
    params.setdefault('realtime', False)
    params.setdefault('archive', False)
    params.setdefault('ungrib_domain', 'full')
    params.setdefault('icbc_model', 'GFS')
    params.setdefault('icbc_source', 'GLADE')
    params.setdefault('icbc_analysis', False)
    params.setdefault('hrrr_native', True)
    params.setdefault('grib_dir', '/glade/derecho/scratch/jaredlee/data')
    params.setdefault('wps_ins_dir', '/glade/u/home/jaredlee/programs/WPS-4.6-dmpar')
    params.setdefault('wrf_ins_dir', '/glade/u/home/jaredlee/programs/WRF-4.6')
    params.setdefault('wps_run_dir', '/glade/derecho/scratch/jaredlee/workflow/wps')
    params.setdefault('wrf_run_dir', '/glade/derecho/scratch/jaredlee/workflow/wrf')
    params.setdefault('template_dir', '/glade/work/jaredlee/workflow/templates')
    params.setdefault('arc_dir', '/glade/work/jaredlee/workflow')
    params.setdefault('upp_working_dir', '/tmp/upp')
    params.setdefault('upp_yaml', './config/run_upp.yaml')
    params.setdefault('upp_domains', ['0'])

    params.setdefault('get_icbc', False)
    params.setdefault('do_geogrid', False)
    params.setdefault('do_ungrib', False)
    params.setdefault('do_avg_tsfc', False)
    params.setdefault('use_tavgsfc', False)
    params.setdefault('do_metgrid', False)
    params.setdefault('do_real', False)
    params.setdefault('do_wrf', False)
    params.setdefault('do_upp', False)

    params.setdefault('geos5_int_dir', None)
    params.setdefault('use_geos5_aer_fcst', False)
    params.setdefault('use_geos5_aer_anal', False)

    params['hostname'] = hostname
    params['grib_dir_parent'] = pathlib.Path(params['grib_dir'])
    del params['grib_dir']
    params['icbc_source'] = params['icbc_source']
    params['icbc_model'] = params['icbc_model']
    params['icbc_fc_dt'] = params['icbc_fc_dt']
    params['icbc_analysis'] = params['icbc_analysis']
    params['ungrib_domain'] = params['ungrib_domain']
    params['wps_ins_dir'] = pathlib.Path(params['wps_ins_dir'])
    params['wrf_ins_dir'] = pathlib.Path(params['wrf_ins_dir'])
    params['wps_run_dir_parent'] = pathlib.Path(params['wps_run_dir'])
    del params['wps_run_dir']
    params['wrf_run_dir_parent'] = pathlib.Path(params['wrf_run_dir'])
    del params['wrf_run_dir']
    params['template_dir'] = pathlib.Path(params['template_dir'])
    params['arc_dir_parent'] = pathlib.Path(params['arc_dir'])
    del params['arc_dir']
    params['upp_working_dir'] = pathlib.Path(params['upp_working_dir'])
    params['upp_yaml'] = pathlib.Path(params['upp_yaml'])
    params['archive'] = params['archive']
    if params['geos5_int_dir'] is not None:
        params['geos5_int_dir_parent'] = pathlib.Path(params['geos5_int_dir'])
    else:
        params['geos5_int_dir_parent'] = None
    del params['geos5_int_dir']

    # Check upp_domains and convert to int if possible.
    for idx, domain in enumerate(params['upp_domains']):
        try:
            params['upp_domains'][idx] = int(domain)
        except ValueError:
            print(f'ERROR! Specify integers for upp_domains, or leave this param empty to process all domains. Got: {domain}')
            parser.print_help()
            sys.exit(1)

    params['cycle_dt_str_beg'] = cycle_dt_beg
    params['cycle_dt_str_end'] = cycle_dt_end

    return params

def main(cycle_dt_str_beg, cycle_dt_str_end, cycle_int_h, sim_hrs, icbc_fc_dt, exp_name, exp_wrf_only, realtime, archive, hostname,
         icbc_model, icbc_source, icbc_analysis, ungrib_domain, grib_dir_parent, wps_ins_dir, wrf_ins_dir, hrrr_native,
         wps_run_dir_parent, wrf_run_dir_parent, template_dir, arc_dir_parent,
         geos5_int_dir_parent, use_geos5_aer_fcst, use_geos5_aer_anal,
         upp_working_dir, upp_yaml, upp_domains,
         get_icbc, do_geogrid, do_ungrib, do_avg_tsfc, use_tavgsfc, do_metgrid, do_real, do_wrf, do_upp):

    ## String format statements
    fmt_int_fmt_date        = '%Y-%m-%d_%H'
    fmt_yyyymmdd       = '%Y%m%d'
    fmt_yyyymmddhh     = '%Y%m%d%H'
    fmt_yyyymmdd_hh    = '%Y%m%d_%H'
    fmt_yyyymmdd_hhmm  = '%Y%m%d_%H%M'

    variants_aws = ['AWS', 'aws']
    variants_glade = ['GLADE', 'glade']
    variants_gc = ['GoogleCloud', 'googlecloud', 'Google_Cloud', 'google_cloud', 'GC', 'gc', 'GCloud', 'gcloud']

    variants_gfs = ['GFS', 'gfs']
    variants_gfs_fnl = ['GFS_FNL', 'gfs_fnl']
    variants_gefs = ['GEFS', 'gefs']
    variants_hrrr = ['HRRR', 'hrrr']

    ## Date/time manipulation
    cycle_dt_beg = pd.to_datetime(cycle_dt_str_beg, format=fmt_yyyymmdd_hh)
    cycle_dt_end = pd.to_datetime(cycle_dt_str_end, format=fmt_yyyymmdd_hh)
    cycle_dt_all = pd.date_range(start=cycle_dt_beg, end=cycle_dt_end, freq=str(cycle_int_h)+'h')
    n_cycles = len(cycle_dt_all)

    if icbc_analysis and icbc_fc_dt != 0:
        log.error('ERROR: icbc_analysis = True and icbc_fc_dt = ' + str(icbc_fc_dt) + '. Incompatible options.')
        log.error('If icbc_analysis = True is desired, then set icbc_fc_dt = 0 and re-run the workflow.')
        log.error('Exiting!')
        sys.exit(1)

    ## Check if this cluster uses slurm or pbs
    test = subprocess.run(['which','sbatch'], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    code = test.returncode
    if code == 0:
        scheduler = 'slurm'
    else:
        test = subprocess.run(['which','qsub'], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        code = test.returncode
        if code == 0:
            scheduler = 'pbs'
        else:
            ## No jobs can get submitted if we get here
            log.error('ERROR: Neither sbatch nor qsub executables found.')
            log.error('       Modify scripts to handle a different batch job scheduler. Exiting!')
            sys.exit(1)
    log.info('Using the '+scheduler+' scheduler for batch job submission')

    ## Loop over forecast cycles
    for cc in range(n_cycles):
        cycle_dt = cycle_dt_all[cc]
        cycle_yr = cycle_dt.strftime('%Y')
        cycle_mo = cycle_dt.strftime('%m')
        cycle_dy = cycle_dt.strftime('%d')
        cycle_hr = cycle_dt.strftime('%H')
        cycle_yyyymmdd    = cycle_dt.strftime(fmt_yyyymmdd)
        cycle_yyyymmdd_hh = cycle_dt.strftime(fmt_yyyymmdd_hh)
        cycle_str = cycle_yyyymmdd_hh

        ## Directories for WPS & WRF where everything should be linked & run
        geo_run_dir = wps_run_dir_parent.joinpath('geogrid')
        if exp_name is None:
            wps_run_dir = wps_run_dir_parent.joinpath(cycle_yyyymmdd_hh)
            wrf_run_dir = wrf_run_dir_parent.joinpath(cycle_yyyymmdd_hh)
            ## Directory for archival
            arc_dir = arc_dir_parent.joinpath(cycle_yyyymmdd_hh)
        else:
            if exp_wrf_only:
                wps_run_dir = wps_run_dir_parent.joinpath(cycle_yyyymmdd_hh)
            else:
                wps_run_dir = wps_run_dir_parent.joinpath(cycle_yyyymmdd_hh,exp_name)
            wrf_run_dir = wrf_run_dir_parent.joinpath(cycle_yyyymmdd_hh,exp_name)
            ## Directory for archival
            arc_dir = arc_dir_parent.joinpath(cycle_yyyymmdd_hh, exp_name)
        ## Directories for containing ungrib & metgrid output
        ungrib_dir  = wps_run_dir.joinpath('ungrib')
        metgrid_dir = wps_run_dir.joinpath('metgrid')
        ## WPS & WRF namelist templates
        wps_nml_tmp = f'namelist.wps.{icbc_model.lower()}'
        if exp_name is None:
            wrf_nml_tmp = 'namelist.input.' + icbc_model.lower()
            if icbc_model in variants_hrrr:
                # If using HRRR, check if namelist.input.hrrr.hybr or namelist.input.hrrr.pres exists.
                # If not, then use namelist.input.hrrr if that exists, to not require users have separate templates.
                # If using native-grid files, num_metgrid_levels = 51.
                # If using pressure-level files, num_metgrid_levels = 41 and ptop_requested = 5000 or larger.
                # It is the responsibility of the user to configure their namelist templates properly, as there are
                # so many user-configured settings that can easily go awry and cause errors at various stages.
                # Checking for all of them would make this set of scripts much more complex and vulnerable to version
                # changes in WPS or WRF as some namelist options are added or removed with version changes.
                if hrrr_native:
                    wrf_nml_tmp_hrrr = 'namelist.input.hrrr.hybr'
                else:
                    wrf_nml_tmp_hrrr = 'namelist.input.hrrr.pres'
                if template_dir.joinpath(wrf_nml_tmp_hrrr).exists():
                    wrf_nml_tmp = wrf_nml_tmp_hrrr
        else:
            # If creating ensemble members or experiments, assume the user is creating namelist templates properly.
            # Don't bother looking for .hybr or .pres suffixes or anything like that.
            # If using experiments driven by different models for ICs/LBCs, name templates carefully (e.g.,
            # namelist.input.hrrr.mem01, namelist.input.gfs.mem02, etc.) & run workflow separately for each icbc_model.
            wrf_nml_tmp = f'namelist.input.{icbc_model.lower()}.{exp_name}'

            # As above, handle use of HRRR (hybr or pres) when using an exp_name
            if icbc_model in variants_hrrr:
                if hrrr_native:
                    wrf_nml_tmp_hrrr = f'namelist.input.hrrr.hybr.{exp_name}'
                else:
                    wrf_nml_tmp_hrrr = f'namelist.input.hrrr.pres.{exp_name}'
                if template_dir.joinpath(wrf_nml_tmp_hrrr).exists():
                    wrf_nml_tmp = wrf_nml_tmp_hrrr

            # Set the WPS namelist template file to look for an experiment-specific one if needed for WPS
            if not exp_wrf_only:
                wps_nml_tmp = f'{wps_nml_tmp}.{exp_name}'

        # Add some error-checking for the existence of the expected WPS & WRF namelist templates
        if not template_dir.joinpath(wps_nml_tmp).exists():
            log.error('ERROR: Expected WPS namelist template file ' + str(
                template_dir.joinpath(wps_nml_tmp)) + ' does not exist.')
            log.error('Exiting!')
            sys.exit(1)
        else:
            log.info(f'Using WPS namelist template file: {template_dir.joinpath(wps_nml_tmp)}')

        if not template_dir.joinpath(wrf_nml_tmp).exists():
            log.error('ERROR: Expected WRF namelist template file ' + str(
                template_dir.joinpath(wrf_nml_tmp)) + ' does not exist.')
            log.error('Exiting!')
            sys.exit(1)
        else:
            log.info(f'Using WRF namelist template file: {template_dir.joinpath(wrf_nml_tmp)}')

        ## Get the icbc model cycle
        ## In real-time applications there may need to be an offset to stay ahead of the clock
        icbc_cycle_dt = cycle_dt - dt.timedelta(hours=icbc_fc_dt)
        icbc_cycle_yr = icbc_cycle_dt.strftime('%Y')
        icbc_cycle_mo = icbc_cycle_dt.strftime('%m')
        icbc_cycle_dy = icbc_cycle_dt.strftime('%d')
        icbc_cycle_hr = icbc_cycle_dt.strftime('%H')
        icbc_cycle_yyyymmdd    = icbc_cycle_dt.strftime(fmt_yyyymmdd)
        icbc_cycle_yyyymmdd_hh = icbc_cycle_dt.strftime(fmt_yyyymmdd_hh)
        icbc_cycle_str = icbc_cycle_yyyymmdd_hh

        ## Local directory where ICs/LBC grib2 files should be downloaded
        # Model directory structure & naming conventions to mimic AWS, rather than GLADE or GoogleCloud
        if icbc_model in variants_gefs:
            # Full-domain grib directory
            grib_dir_full = grib_dir_parent.joinpath(f'gefs.{icbc_cycle_yyyymmdd}',icbc_cycle_hr,'atmos')
            # Use subset GEFS
            grib_dir_subset = grib_dir_parent.joinpath(f'gefs.{icbc_cycle_yyyymmdd}.subset',icbc_cycle_hr,'atmos')
        elif icbc_model in variants_gfs:
            # Full-domain grib directory
            grib_dir_full = grib_dir_parent.joinpath(f'gfs.{icbc_cycle_yyyymmdd}',icbc_cycle_hr,'atmos')
            # Subsetted-domain grib directory
            grib_dir_subset = grib_dir_parent.joinpath(f'gfs.{icbc_cycle_yyyymmdd}.subset',icbc_cycle_hr,'atmos')
        elif icbc_model in variants_gfs_fnl:
            # Full-domain grib directory
            grib_dir_full = grib_dir_parent.joinpath(f'gfs_fnl.{icbc_cycle_yyyymmdd}', icbc_cycle_hr)
            # Subsetted-domain grib directory
            grib_dir_subset = grib_dir_parent.joinpath(f'gfs_fnl.{icbc_cycle_yyyymmdd}.subset', icbc_cycle_hr)
        elif icbc_model in variants_hrrr:
            # Full-domain grib directory
            grib_dir_full = grib_dir_parent.joinpath(f'hrrr.{icbc_cycle_yyyymmdd}', icbc_cycle_hr)
            # Subsetted-domain grib directory
            grib_dir_subset = grib_dir_parent.joinpath(f'hrrr.{icbc_cycle_yyyymmdd}.subset', icbc_cycle_hr)
        else:
            log.error('ERROR: Unknown option chosen for icbc_model in the yaml file.')
            log.error('       Current options are GEFS|GFS|GFS_FNL|HRRR.')
            log.error('       Add code to handle other IC/LBC model data.')
            log.error('Exiting!')
            sys.exit(1)

        if ungrib_domain == 'full':
            grib_dir = grib_dir_full
        elif ungrib_domain == 'subset':
            grib_dir = grib_dir_subset
        else:
            log.error('ERROR: Set ungrib_domain to either full or subset in the yaml file.')
            log.error('Exiting!')
            sys.exit(1)

        ## Get the start and end times of this simulation
        beg_dt = cycle_dt
        end_dt = beg_dt + dt.timedelta(hours=sim_hrs)

        beg_yr = beg_dt.strftime('%Y')
        beg_mo = beg_dt.strftime('%m')
        beg_dy = beg_dt.strftime('%d')
        beg_hr = beg_dt.strftime('%H')
        end_yr = end_dt.strftime('%Y')
        end_mo = end_dt.strftime('%m')
        end_dy = end_dt.strftime('%d')
        end_hr = end_dt.strftime('%H')

        ## ***********
        ## WPS Section
        ## ***********

        ## Read the template namelist.wps to get interval_seconds, and convert to int_hrs
        nml_tmp = template_dir.joinpath(wps_nml_tmp)
        log.info(f'Opening {nml_tmp}')
        with open(nml_tmp) as nml:
            for line in nml:
                if line.strip()[0:16] == 'interval_seconds':
                    int_sec = int(line.split('=')[1].strip().split(',')[0])
                    int_hrs = int_sec // 3600
                    break

        # Build the array of valid times for this simulation (most needed for icbc_analysis=True)
        valid_dt_all = pd.date_range(start=beg_dt, end=end_dt, freq=str(int_hrs) + 'h')
        n_valid = len(valid_dt_all)

        if icbc_model in variants_gefs:
            if exp_name is None:
                log.error('ERROR! exp_name is None, so a GEFS member number cannot be extracted. Exiting!')
            ## Make an assumption about which GEFS member to download or linked to based on exp_name
            ## Assume it starts with memNN or expNN, and set NN to the GEFS member to get or link to
            if exp_name[0:3] in ['mem', 'exp']:
                mem_id = exp_name[3:5]
                ## If this number exceeds the GEFS members, then base it only on the last number to get member 01-10
                if int(mem_id) > 20:
                    mem_id = exp_name[4]
                    if mem_id == '0':
                        mem_id = '10'
                    else:
                        mem_id = '0'+mem_id
            else:
                log.error('ERROR! Unable to obtain a GEFS member number from exp_name. Exiting!')
                sys.exit(1)
        else:
            mem_id = None

        if get_icbc:
            # If an ICBC dataset is locally available on GLADE, use that instead of downloading from an external repo
            if icbc_model in variants_gfs:
                if icbc_analysis:
                    log.error('ERROR: icbc_analysis = True with icbc_model = GFS is currently not supported.')
                    log.error('Use icbc_model = GFS_FNL instead if analysis ICs/LBCs are desired with GFS.')
                    log.error('Exiting!')
                    sys.exit(1)

                if icbc_source in variants_glade:
                    script_name = 'link_gfs_from_glade.py'
                elif icbc_source in variants_aws:
                    script_name = 'download_gfs_from_aws.py'
                else:
                    log.error('ERROR: No option yet to download GFS data from icbc_source=' + icbc_source + ' in setup_wps_wrf.py.')
                    log.error('Exiting!')
                    sys.exit(1)
                cmd_list = ['python', script_name, '-b', icbc_cycle_str, '-s', str(sim_hrs), '-i', str(int_hrs),
                            '-o', grib_dir_full]
            elif icbc_model in variants_gfs_fnl:
                if icbc_source in variants_glade:
                    cmd_list = ['python', 'link_gfs_fnl_from_glade.py', '-b', icbc_cycle_str, '-s', str(sim_hrs),
                         '-i', str(int_hrs), '-o', grib_dir_parent]
                else:
                    log.error('ERROR: No option yet to download GFS_FNL data from icbc_source=' + icbc_source +' in setup_wps_wrf.py.')
                    log.error('Exiting!')
                    sys.exit(1)
            elif icbc_model in variants_gefs:
                if icbc_analysis:
                    log.error('ERROR: icbc_analysis = True with icbc_model = GEFS is currently not supported.')
                    log.error('Exiting!')
                    sys.exit(1)
                if icbc_source in variants_glade:
                    log.error('ERROR: There is no known dataset containing GEFS files on GLADE. Change icbc_source.')
                    log.error('Exiting!')
                    sys.exit(1)
                elif icbc_source in variants_aws:
                    cmd_list = ['python', 'download_gefs_from_aws.py', '-b', icbc_cycle_str, '-s', str(sim_hrs),
                         '-i', str(int_hrs), '-m', mem_id, '-o', grib_dir_full, '-f', str(icbc_fc_dt)]
                else:
                    log.error('ERROR: No option yet to download or link to GEFS data from icbc_source=' + icbc_source + ' in setup_wps_wrf.py.')
                    log.error('Exiting!')
                    sys.exit(1)
            elif icbc_model in variants_hrrr:
                if icbc_source in variants_glade:
                    log.error('ERROR: There is no known dataset containing HRRR files on GLADE. Change icbc_source.')
                    log.error('Exiting!')
                    sys.exit(1)
                elif icbc_source in variants_gc or icbc_source in variants_aws:
                    cmd_list = ['python', 'download_hrrr_from_aws_or_gc.py', '-b', icbc_cycle_str, '-s', str(sim_hrs),
                            '-i', str(int_hrs), '-o', grib_dir_parent, '-f', str(icbc_fc_dt), '-c', icbc_source]
                    if hrrr_native:
                        cmd_list.append('-n')
                    if icbc_analysis:
                        cmd_list.append('-a')
                else:
                    log.error('ERROR: No option yet to download or link to HRRR data from icbc_source=' + icbc_source + ' in setup_wps_wrf.py.')
                    log.error('Exiting!')
                    sys.exit(1)
            else:
                log.error('ERROR: Unknown option for icbc_model in the get_icbc branch of setup_wps_wrf.py.')
                log.error('Exiting!')
                sys.exit(1)

            # Execute the command to get ICs/LBCs
            ret, output = exec_command(cmd_list, log)

        if do_geogrid:
            cmd_list = ['python', 'run_geogrid.py', '-w', wps_ins_dir, '-r', geo_run_dir, '-t', template_dir,
                 '-n', wps_nml_tmp, '-q', scheduler, '-a', hostname]
            ret, output = exec_command(cmd_list, log)

        if do_ungrib:
            cmd_list = ['python', 'run_ungrib.py', '-b', cycle_str, '-s', str(sim_hrs), '-w', wps_ins_dir,
                        '-r', wps_run_dir, '-o', ungrib_dir, '-t', template_dir, '-m', icbc_model, '-n', wps_nml_tmp,
                        '-i', str(int_hrs), '-q', scheduler, '-f', str(icbc_fc_dt), '-a', hostname, '-c', icbc_source]

            # For some IC/LBC models the gribfiles are stored in date directories, not cycle hour directories
            # So pass in grib_dir_parent instead. run_ungrib.py handles grib_dir for these models differently.
            if icbc_model in variants_gfs_fnl or icbc_model in variants_hrrr:
                cmd_list.append('-g')
                cmd_list.append(grib_dir_parent)
            else:
                cmd_list.append('-g')
                cmd_list.append(grib_dir)

            if icbc_model in variants_hrrr and icbc_analysis:
                cmd_list.append('-l')
            if hrrr_native:
                cmd_list.append('-v')
            if mem_id is not None:
                cmd_list.append('-d')
                cmd_list.append(mem_id)
            ret, output = exec_command(cmd_list, log)

        if do_avg_tsfc:
            cmd_list = ['python', 'run_avg_tsfc.py', '-b', cycle_str, '-s', str(sim_hrs), '-w', wps_ins_dir,
                        '-r', wps_run_dir, '-u', ungrib_dir, '-t', template_dir, '-m', icbc_model, '-n', wps_nml_tmp]
            if hrrr_native:
                cmd_list.append('-v')
            ret, output = exec_command(cmd_list, log)
            # If we just ran avg_tsfc.exe, then we'll want to use TAVGSFC when running metgrid
            use_tavgsfc = True

        # If using GEOS-5 time-varying aerosols, set the actual directory here where the WPS Int. Fmt. data is
        if use_geos5_aer_fcst or use_geos5_aer_anal:
            # First, make sure a parent directory has been specified
            if geos5_int_dir_parent is None:
                log.error('ERROR: geos5_int_dir is not defined in the config yaml file. \n'
                          'Please specify the parent directory where the GEOS-5 time-varying aerosols in '
                          'WPS Intermediate Format are stored (the output of geos2wrf). \nExiting!')
                sys.exit(1)

            # Create a directory in which there will be symlinks to each of the requested GEOS-5 Int. Fmt. files
            # To avoid unnecessary clutter in non-scratch storage, put it in the wps/ungrib run directory
            # It should already exist, but make sure it does just in case
            ungrib_dir.mkdir(parents=True, exist_ok=True)

            # If using GEOS-5 forecasts (not analyses)...
            if use_geos5_aer_fcst:
                # Assume for now that we're using data from the most recent 00 or 12 UTC time
                # GEOS-5 has two main cycles daily, 00 UTC out to 10 days, 12 UTC out to 5 days
                # Also check for simulation length to ensure GEOS-5 forecasts are able to be used before we get going
                if sim_hrs > 240:
                    log.error('ERROR: Requested sim_hrs > 240 and use_geos5_aer_fcst = True. \n'
                              'These are incompatible options, as the longest GEOS-5 forecast goes out 240 h. Exiting!')
                    sys.exit(1)
                elif sim_hrs > 120:
                    # First, the easy case
                    # Use icbc_cycle_dt as the reference, assuming we don't want newer GEOS-5 than atmospheric data
                    if icbc_cycle_hr == '00':
                        geos5_cycle_dt = cycle_dt
                    else:
                        # If it's any other time, then just go back to the last 00 UTC
                        geos5_cycle_dt = cycle_dt - dt.timedelta(hours=int(icbc_cycle_hr))
                else:
                    if icbc_cycle_hr == '00' or icbc_cycle_hr == '12':
                        geos5_cycle_dt = cycle_dt
                    else:
                        # If it's any other time, then just go back to the last 00 or 12 UTC
                        if int(icbc_cycle_hr) < 12:
                            geos5_cycle_dt = cycle_dt - dt.timedelta(hours=int(icbc_cycle_hr))
                        else:
                            geos5_cycle_dt = cycle_dt - dt.timedelta(hours=int(icbc_cycle_hr) + 12)

                geos5_cycle_dt_str = geos5_cycle_dt.strftime(fmt_yyyymmdd_hh)
                geos5_cycle_yr = geos5_cycle_dt.strftime('%Y')
                geos5_cycle_mo = geos5_cycle_dt.strftime('%m')
                geos5_cycle_dy = geos5_cycle_dt.strftime('%d')
                geos5_cycle_hr = geos5_cycle_dt.strftime('%H')
                log.info(f'Linking to GEOS-5 forecast cycle {geos5_cycle_dt_str} for time-varying aerosols '
                         f'in {ungrib_dir}')

                # Assume the GEOS-5 data is stored in a directory structure that mimics that of NASA
                geos5_int_dir = geos5_int_dir_parent.joinpath(f'Y{geos5_cycle_yr}', f'M{geos5_cycle_mo}',
                                                              f'D{geos5_cycle_dy}', f'H{geos5_cycle_hr}')

                # Use glob to find the matching file name patterns
                for geos5_int_file in sorted(geos5_int_dir.glob(f'GEOS:*')):
                    # Symlink path
                    geos5_symlink = ungrib_dir.joinpath(geos5_int_file.name)
                    # Create the symlink, deleting an existing file if necessary
                    if geos5_symlink.exists(): geos5_symlink.unlink()
                    geos5_symlink.symlink_to(geos5_int_file)

            # If using GEOS-5 analyses (not forecasts)...
            if use_geos5_aer_anal:
                # Now symlink to each requested GEOS-5 Intermediate Format file
                # Start with the simplest cases, assuming a cycle_hr of 00, 03, 06, 09, 12, 15, 18, or 21
                # NOTE: This all assumes model cycle times starting at 00 minutes, rather than a non-top-of-hour time
                if cycle_hr in ['00', '03', '06', '09', '12', '15', '18', '21']:
                    # Go an extra 3 hours in case of, say, an 8-h simulation, to ensure aerosols are available
                    geos5_dt = pd.date_range(start=cycle_dt, end=cycle_dt + dt.timedelta(hours=sim_hrs + 3), freq='3h')

                # Now do 1 hour after a 3-hourly time
                elif cycle_hr in ['01', '04', '07', '10', '13', '16', '19', '22']:
                    # Ensure there are GEOS-5 files bookending the simulation times
                    geos5_dt = pd.date_range(start=cycle_dt - dt.timedelta(hours=1),
                                             end=cycle_dt + dt.timedelta(hours=sim_hrs + 2), freq='3h')

                # What's left is [02, 05, 08, 11, 14, 17, 20, 23]
                else:
                    # Ensure there are GEOS-5 files bookending the simulation times
                    geos5_dt = pd.date_range(start=cycle_dt - dt.timedelta(hours=2),
                                             end=cycle_dt + dt.timedelta(hours= sim_hrs + 1), freq='3h')

                # Now make symlinks to all the required GEOS-5 intermediate format files
                log.info(f'Linking to GEOS-5 analysis intermediate format files for time-varying aerosols '
                         f'in {ungrib_dir}')
                for tt in range(len(geos5_dt)):
                    this_geos5_date_str = geos5_dt[tt].strftime(fmt_int_fmt_date)
                    this_geos5_yr = geos5_dt[tt].strftime('%Y')
                    this_geos5_mo = geos5_dt[tt].strftime('%m')
                    this_geos5_dy = geos5_dt[tt].strftime('%d')
                    this_geos5_int_dir = geos5_int_dir_parent.joinpath(f'Y{this_geos5_yr}', f'M{this_geos5_mo}',
                                                                       f'D{this_geos5_dy}')
                    # Target path
                    geos5_file = this_geos5_int_dir.joinpath(f'GEOS:{this_geos5_date_str}')
                    # Symlink path
                    geos5_symlink = ungrib_dir.joinpath(f'GEOS:{this_geos5_date_str}')
                    # Now create the symlink, deleting an existing symlink if necessary
                    if geos5_symlink.exists(): geos5_symlink.unlink()
                    geos5_symlink.symlink_to(geos5_file)

        if do_metgrid:
            cmd_list = ['python', 'run_metgrid.py', '-b', cycle_str, '-s', str(sim_hrs), '-w', wps_ins_dir,
                        '-r', wps_run_dir, '-o', metgrid_dir, '-u', ungrib_dir, '-t', template_dir, '-m', icbc_model,
                        '-q', scheduler, '-a', hostname, '-n', wps_nml_tmp]
            if hrrr_native:
                cmd_list.append('-v')
            if use_tavgsfc:
                cmd_list.append('-g')
            if use_geos5_aer_fcst or use_geos5_aer_anal:
                cmd_list.append('-f')
                cmd_list.append('-d')
                cmd_list.append(ungrib_dir)
            ret, output = exec_command(cmd_list, log)

        if do_real:
            cmd_list = ['python', 'run_real.py', '-b', cycle_str, '-s', str(sim_hrs), '-w', wrf_ins_dir,
                     '-r', wrf_run_dir, '-m', metgrid_dir, '-t', template_dir, '-i', icbc_model, '-n', wrf_nml_tmp,
                     '-q', scheduler, '-a', hostname]
            if exp_name is not None:
                cmd_list.append('-x')
                cmd_list.append(exp_name)
            ret, output = exec_command(cmd_list, log)

        if do_wrf:
            cmd_list = ['python', 'run_wrf.py', '-b', cycle_str, '-s', str(sim_hrs), '-w', wrf_ins_dir,
                        '-r', wrf_run_dir, '-t', template_dir, '-i', icbc_model, '-n', wrf_nml_tmp,
                        '-q', scheduler, '-a', hostname]
            if exp_name is not None:
                cmd_list.append('-x')
                cmd_list.append(exp_name)
            if do_upp or archive or realtime:
                cmd_list.append('-m')
            ret, output = exec_command(cmd_list, log)

        if do_upp:
            cmd_list = ['python', 'run_upp.py', '-b', cycle_str, '-r', wrf_run_dir, '-c', upp_yaml, '-N']
            if exp_name is not None:
                cmd_list.append('-x')
                cmd_list.append(exp_name)
            if upp_domains and len(upp_domains) > 0 and upp_domains[0] > 0:
                domains_str = str(upp_domains).strip().replace('[', '').replace(']', '').replace(' ', '')
                log.info(f'Sending domains_str to run_upp: {domains_str}')
                cmd_list.append('-d')
                cmd_list.append(str(domains_str))
            ret, output = exec_command(cmd_list, log)

            # # TODO: Take this out after testing
            # if not upp_yaml.exists():
            #     log.warning(f'WARNING: Yaml config {upp_yaml} does not exist. Using ./test/run_upp.yaml instead.')
            #     upp_yaml = './test/run_upp.yaml'
            #
            # # Get a full path to ./run_upp.py
            # run_upp = pathlib.Path(os.path.abspath('./run_upp.py'))
            # submit_upp_tmpl = pathlib.Path(os.path.abspath('./config/submit_upp.tmpl'))
            # if not run_upp.is_file():
            #     log.error('ERROR! No "./run_upp.py" present to drive UPP post-processing. Exiting!')
            #     sys.exit(1)
            #
            # # Create submit_upp.bash script(s)
            # submitfile_paths = create_submit_upp_files_from_tmpl(submit_upp_tmpl, cycle_str, run_upp, wrf_run_dir, exp_name, upp_yaml, upp_domains)
            #
            # for upp_submitfile in submitfile_paths:
            #     ret, output = exec_command(['sbatch', upp_submitfile], log)
            #     jobid = output.split('job ')[1].split('\\n')[0]
            #     log.info(f'Submitted UPP batch job for "sbatch {upp_submitfile}": ' + jobid)

        if archive:
            arc_dir.joinpath('config').mkdir(exist_ok=True, parents=True)
            arc_dir.joinpath('wrfout').mkdir(exist_ok=True, parents=True)
            os.chdir(wps_run_dir)
            # subprocess.run cannot handle wildcards, so we need to iterate over matching files in calls to exec_command
            log.info('Copying namelist.wps to ' + str(arc_dir.joinpath('config')))
            ret,output = exec_command(['cp', 'namelist.wps', str(arc_dir.joinpath('config'))], log)
            os.chdir(wrf_run_dir)
            log.info('Copying namelist.input to '+str(arc_dir.joinpath('config')))
            ret,output = exec_command(['cp','namelist.input',str(arc_dir.joinpath('config'))],log)
            log.info('Copying wrfinput* and wrfbdy* files to ' + str(arc_dir.joinpath('config')))
            files = glob.glob('wrfinput_d0*')
            for file in files:
                ret,output = exec_command(['cp',file,str(arc_dir.joinpath('config'))],log)
            files = glob.glob('wrfbdy_d*')
            for file in files:
                ret,output = exec_command(['mv',file,str(arc_dir.joinpath('config'))],log)
            log.info('Moving wrfout* and wrfxtrm* files to '+str(arc_dir.joinpath('wrfout')))
            files = glob.glob('wrfout*')
            for file in files:
                ret,output = exec_command(['mv',file,str(arc_dir.joinpath('wrfout'))],log)
            files = glob.glob('wrfxtrm*')
            for file in files:
                ret,output = exec_command(['mv', file, str(arc_dir.joinpath('wrfout'))], log)


if __name__ == '__main__':
    now_time_beg = dt.datetime.now(dt.UTC)
    params = parse_args()
    # params['now_time_beg'] = now_time_beg
    main(**params)
    now_time_end = dt.datetime.now(dt.UTC)
    run_time_tot = now_time_end - now_time_beg
    now_time_beg_str = now_time_beg.strftime('%Y-%m-%d %H:%M:%S')
    now_time_end_str = now_time_end.strftime('%Y-%m-%d %H:%M:%S')
    log.info('')
    log.info(this_file + ' completed.')
    log.info('   Beg time: '+now_time_beg_str)
    log.info('   End time: '+now_time_end_str)
    log.info('   Run time: '+str(run_time_tot)+'\n')
