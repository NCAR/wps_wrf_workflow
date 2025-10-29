#!/usr/bin/env python3

'''
run_ungrib.py

Created by: Jared A. Lee (jaredlee@ucar.edu)
Created on: 31 Mar 2023

This script is designed to run ungrib.exe in embarrassingly parallel fashion.
Each file to be ungribbed will be submitted as a separate 1-core batch job to the queue.
'''

import os
import sys
import shutil
import argparse
import pathlib
import glob
import time
import datetime as dt
import pandas as pd
import logging

from proc_util import exec_command
from wps_wrf_util import search_file

this_file = os.path.basename(__file__)
logging.basicConfig(format=f'{this_file}: %(asctime)s - %(message)s',
                    level=logging.DEBUG, datefmt='%Y-%m-%dT%H:%M:%S')
log = logging.getLogger(__name__)

long_time = 5
long_long_time = 15
short_time = 3
curr_dir=os.path.dirname(os.path.abspath(__file__))

def parse_args():
    ## Parse the command-line arguments
    parser = argparse.ArgumentParser()
    parser.add_argument('-b', '--cycle_dt_beg', default='20220801_00', help='beginning date/time of the WRF model cycle [YYYYMMDD_HH] (default: 20220801_00)')
    parser.add_argument('-s', '--sim_hrs', default=192, type=int, help='integer number of hours for the WRF simulation (default: 192)')
    parser.add_argument('-w', '--wps_dir', default=None, help='string or pathlib.Path object of the WPS install directory')
    parser.add_argument('-r', '--run_dir', default=None, help='string or pathlib.Path object of the run directory where files should be linked and run')
    parser.add_argument('-o', '--out_dir', default=None, help='string or pathlib.Path object of the ungrib output directory (default: run_dir/ungrib)')
    parser.add_argument('-g', '--grib_dir', default=None, help='string or pathlib.Path object that hosts the grib/grib2 data to be ungribbed')
    parser.add_argument('-t', '--temp_dir', default=None, help='string or pathlib.Path object that hosts namelist & queue submission script templates')
    parser.add_argument('-c', '--icbc_source', default='GLADE', help='string specifying the repository from which to obtain ICs/LBCs (GLADE [default], AWS, GoogleCloud, NOMADS)')
    parser.add_argument('-m', '--icbc_model', default='GEFS', help='string specifying the IC/LBC model (default: GEFS)')
    parser.add_argument('-f', '--icbc_fc_dt', default=0, type=int, help='integer number of hours prior to WRF cycle time for IC/LBC model cycle (default: 0)')
    parser.add_argument('-i', '--int_hrs', default=3, type=int, help='integer number of hours between IC/LBC files (default: 3)')
    parser.add_argument('-q', '--scheduler', default='pbs', help='string specifying the cluster job scheduler (default: pbs)')
    parser.add_argument('-d', '--mem_id', default=None, help='string specifying the numeric id (with any necessary leading zeros) of the GEFS or other ensemble member so that ./link_grib.csh can link to the correct file (default: None)')
    parser.add_argument('-a', '--hostname', default='derecho', help='string specifying the hostname (default: derecho')
    parser.add_argument('-v', '--hrrr_native', action='store_true',
                        help='If flag present, then ungrib HRRR native-grid data for atmospheric variables and pressure-level data for soil variables, otherwise only ungrib HRRR pressure-level data for all variables')
    parser.add_argument('-l', '--icbc_analysis', action='store_true',
                        help='If flag present, use analysis [f00] files for ICs/LBCs')
    parser.add_argument('-n', '--nml_tmp', default=None,
                        help='string for filename of namelist template (default: namelist.wps.[icbc_model])')

    args = parser.parse_args()
    cycle_dt_beg = args.cycle_dt_beg
    sim_hrs = args.sim_hrs
    wps_dir = args.wps_dir
    run_dir = args.run_dir
    out_dir = args.out_dir
    grib_dir = args.grib_dir
    temp_dir = args.temp_dir
    icbc_source = args.icbc_source
    icbc_model = args.icbc_model
    icbc_fc_dt = args.icbc_fc_dt
    icbc_analysis = args.icbc_analysis
    int_hrs = args.int_hrs
    scheduler = args.scheduler
    mem_id = args.mem_id
    hostname = args.hostname
    hrrr_native = args.hrrr_native
    nml_tmp = args.nml_tmp

    if len(cycle_dt_beg) != 11 or cycle_dt_beg[8] != '_':
        log.error('ERROR! Incorrect format for argument cycle_dt_beg in call to run_metgrid.py. Exiting!')
        parser.print_help()
        sys.exit(1)

    if wps_dir is not None:
        wps_dir = pathlib.Path(wps_dir)
    else:
        log.error('ERROR! wps_dir not specified as an argument in call to run_ungrib.py. Exiting!')
        sys.exit(1)

    if run_dir is not None:
        run_dir = pathlib.Path(run_dir)
    else:
        log.error('ERROR! run_dir not specified as an argument in call to run_ungrib.py. Exiting!')
        sys.exit(1)

    if out_dir is not None:
        out_dir = pathlib.Path(out_dir)
    else:
        ## Make a default assumption to stick the output in run_dir/ungrib
        out_dir = run_dir.joinpath('ungrib')

    if grib_dir is not None:
        grib_dir = pathlib.Path(grib_dir)
    else:
        log.error('ERROR! grib_dir not specified as an argument in call to run_ungrib.py. Exiting!')
        sys.exit(1)

    if temp_dir is not None:
        temp_dir = pathlib.Path(temp_dir)
    else:
        log.error('ERROR! temp_dir is not specified as an argument in call to run_ungrib.py. Exiting!')
        sys.exit(1)

    return (cycle_dt_beg, sim_hrs, wps_dir, run_dir, out_dir, grib_dir, temp_dir, icbc_source, icbc_model, int_hrs,
            icbc_fc_dt, scheduler, mem_id, hostname, hrrr_native, icbc_analysis, nml_tmp)


def check_wps_nml_templates(template_dir: pathlib.Path, nml_list: list):
    """Function to check if any potential options for the WPS template namelist for ungrib exist.
    If one exists, it returns the file name of the one that does exist."""
    nml_found = False
    for nml in nml_list:
        if nml is None: continue
        if template_dir.joinpath(nml).exists():
            wps_nml_tmp = temp_dir.joinpath(nml)
            log.info(f'Using {wps_nml_tmp} as the template namelist for ungrib')
            nml_found = True
            break

    if not nml_found:
        log.error('ERROR: None of these template namelist files that were checked were found:')
        for nml in nml_list:
            if nml is None: continue
            log.error(f'       {temp_dir.joinpath(nml)}')
        log.error('Exiting!')
        sys.exit(1)

    return wps_nml_tmp


def main(cycle_dt_str, sim_hrs, wps_dir, run_dir, out_dir, grib_dir, temp_dir, icbc_source, icbc_model, int_hrs,
         icbc_fc_dt, scheduler, mem_id, hostname, hrrr_native, icbc_analysis, nml_tmp):

    log.info(f'Running run_ungrib.py from directory: {curr_dir}')

    fmt_hh = '%H'
    fmt_yyyymmdd = '%Y%m%d'
    fmt_yyyymmddhh = '%Y%m%d%H'
    fmt_yyyymmdd_hh = '%Y%m%d_%H'
    fmt_yyyymmdd_hhmm = '%Y%m%d_%H%M'
    fmt_wrf_dt = '%Y-%m-%d_%H:%M:%S'
    fmt_wrf_date_hh = '%Y-%m-%d_%H'

    variants_glade = ['GLADE', 'glade']
    variants_gfs = ['GFS', 'gfs']
    variants_gfs_fnl = ['GFS_FNL', 'gfs_fnl']
    variants_gefs = ['GEFS', 'gfs']
    variants_hrrr = ['HRRR', 'hrrr']

    if icbc_model in variants_hrrr or icbc_model in variants_gfs_fnl:
        grib_dir_parent = grib_dir

    # Any custom grib Vtables (i.e., not part of the WPS distribution) should be stored as part of this repo
    vtable_dir = pathlib.Path(curr_dir).joinpath('custom_vtables')

    cycle_dt = pd.to_datetime(cycle_dt_str, format=fmt_yyyymmdd_hh)
    beg_dt = cycle_dt
    end_dt = beg_dt + dt.timedelta(hours=sim_hrs)
    all_dt = pd.date_range(start=beg_dt, end=end_dt, freq=str(int_hrs)+'h')
    n_times = len(all_dt)

    ## Get the icbc model cycle (in real-time applications there may need to be an offset to stay ahead of the clock)
    icbc_cycle_dt = cycle_dt - dt.timedelta(hours=icbc_fc_dt)
    icbc_cycle_date = icbc_cycle_dt.strftime(fmt_yyyymmdd)
    icbc_cycle_datehh = icbc_cycle_dt.strftime(fmt_yyyymmddhh)
    icbc_cycle_hr = icbc_cycle_dt.strftime('%H')

    ## Create the run directory if it doesn't already exist
    run_dir.mkdir(parents=True, exist_ok=True)

    ## Create the ungrib output directory if it doesn't already exist
    out_dir.mkdir(parents=True, exist_ok=True)

    # Create the ungrib output directory if it doesn't already exist (and if it does, delete it first)
    if out_dir.is_dir():
        shutil.rmtree(out_dir)
        out_dir.mkdir(parents=True, exist_ok=True)

    # Create empty jobid list to be filled in later to allow tracking of each ungrib job
    jobid_list = [''] * n_times

    ## Loop over times
    for tt in range(n_times):
        this_dt = all_dt[tt]
        this_dt_hh = this_dt.strftime(fmt_hh)
        this_dt_wrf_str = this_dt.strftime(fmt_wrf_dt)
        this_dt_yyyymmdd = this_dt.strftime(fmt_yyyymmdd)
        this_dt_yyyymmddhh = this_dt.strftime(fmt_yyyymmddhh)
        this_dt_wrf_date_hh = this_dt.strftime(fmt_wrf_date_hh)
        this_dt_yyyymmdd_hh = this_dt.strftime(fmt_yyyymmdd_hh)
        this_dt_yyyymmdd_hhmm = this_dt.strftime(fmt_yyyymmdd_hhmm)
        log.info('Processing date '+this_dt_yyyymmdd_hh)

        # For some IC/LBC models, gribfiles are stored in directories by cycle date rather than cycle hour
        if icbc_model in variants_gfs_fnl:
            grib_dir = grib_dir_parent.joinpath('gfs_fnl.' + this_dt_yyyymmdd)
        elif icbc_model in variants_hrrr:
            # Assume conus for now, but maybe someday allow for selection of other HRRR domains if the need arises
            if icbc_analysis:
                # All icbc files come from different HRRR model cycles (f00 each cycle) 
                grib_dir = grib_dir_parent.joinpath('hrrr.' + this_dt_yyyymmdd, 'conus')
            else:
                # All icbc files come from a single HRRR model cycle
                grib_dir = grib_dir_parent.joinpath('hrrr.' + icbc_cycle_date, 'conus')

        ## Calculate the lead hour for this cycle, accounting for the possible icbc_fc_dt offset
        lead_h = int((this_dt - cycle_dt).total_seconds() // 3600) + icbc_fc_dt
        lead_h_str3 = str(lead_h).zfill(3)
        lead_h_str2 = str(lead_h).zfill(2)

        os.chdir(run_dir)
        ## We want to ungrib everything as quickly as possible, one file per parallel job
        ## GEFS requires ungribbing two sets of files (a and b), so requires two directories
        ## HRRR optionally requires ungribbing two sets of files if native sigma level input is desired above-surface
        ## GFS only requires ungribbing one set of files
        if icbc_model in variants_gefs:
            ungrib_dir = run_dir.joinpath('ungrib_'+this_dt_yyyymmdd_hh+'_b')
        elif icbc_model in variants_hrrr:
            if hrrr_native:
                # Need to differentiate between hybrid-level HRRR output and pressure-level HRRR output for soil vars
                ungrib_dir = run_dir.joinpath('ungrib_' + this_dt_yyyymmdd_hh + '_hybr')
            else:
                # Only a single round of ungribbing will need to be done on pressure-level HRRR output for atmos & soil
                ungrib_dir = run_dir.joinpath('ungrib_' + this_dt_yyyymmdd_hh + '_pres')
        else:
            ungrib_dir = run_dir.joinpath('ungrib_'+this_dt_yyyymmdd_hh)
        ungrib_dir.mkdir(parents=True, exist_ok=True)
        os.chdir(ungrib_dir)

        ## Link to ungrib-related executables & scripts
        if pathlib.Path('ungrib.exe').is_symlink():
            pathlib.Path('ungrib.exe').unlink()
        if pathlib.Path('link_grib.csh').is_symlink():
            pathlib.Path('link_grib.csh').unlink()
        pathlib.Path('ungrib.exe').symlink_to(wps_dir.joinpath('ungrib.exe'))
        pathlib.Path('link_grib.csh').symlink_to(wps_dir.joinpath('link_grib.csh'))

        ## Copy over the ungrib batch script
        # Add special handling for derecho & casper, since peer scheduling is possible
        if hostname == 'derecho':
            shutil.copy(temp_dir.joinpath('submit_ungrib.bash.derecho'), 'submit_ungrib.bash')
        elif hostname == 'casper':
            shutil.copy(temp_dir.joinpath('submit_ungrib.bash.casper'), 'submit_ungrib.bash')
        else:
            shutil.copy(temp_dir.joinpath('submit_ungrib.bash'), 'submit_ungrib.bash')

        ## Link to the correct Vtable, grib/grib2 files, and copy in a namelist template
        ## (Add other elif options here as needed)
        if pathlib.Path('Vtable').is_symlink():
            pathlib.Path('Vtable').unlink()
        if pathlib.Path('namelist.wps').is_file():
            pathlib.Path('namelist.wps').unlink()

        ## To speed up ungrib, link only to the specific file for the time being processed, not all gribfiles
        if icbc_model in variants_gfs:
            pathlib.Path('Vtable').symlink_to(wps_dir.joinpath('ungrib','Variable_Tables','Vtable.GFS'))
            if icbc_source == 'GLADE' or icbc_source == 'glade':
                file_pattern = str(grib_dir) + '/gfs.0p25.' + icbc_cycle_datehh + '.f' + lead_h_str3 + '.grib2'
            elif icbc_source == 'AWS' or icbc_source == 'aws':
                file_pattern = str(grib_dir) + '/gfs.t' + icbc_cycle_hr + 'z.pgrb2.0p25.f' + lead_h_str3
            else:
                log.error('ERROR: No option yet for icbc_source=' + icbc_source + ' for GFS in run_ungrib.py.')
                log.error('Exiting!')
                sys.exit(1)
            nml_list = [nml_tmp, 'namelist.wps.gfs']
            wps_nml_tmp = check_wps_nml_templates(temp_dir, nml_list)
            shutil.copy(wps_nml_tmp, 'namelist.wps.template')
        elif icbc_model in variants_gfs_fnl:
            pathlib.Path('Vtable').symlink_to(wps_dir.joinpath('ungrib', 'Variable_Tables', 'Vtable.GFS'))
            if icbc_source in variants_glade:
                # Leverage the fact that GFS FNL files on GLADE are 3-hourly, with new cycles every 6 h
                # Always grab either the f00 or f03 files for GFS FNL
                if this_dt_hh in ['00', '06', '12', '18']:
                    this_lead = '00'
                    this_cycle = this_dt
                elif this_dt_hh in ['03', '09', '15', '21']:
                    this_lead = '03'
                    this_cycle = this_dt - dt.timedelta(hours=3)
                else:
                    log.error('ERROR: this_dt_yyyymmddhh = ' + str(this_dt_yyyymmddhh))
                    log.error('This is invalid with icbc_model = GFS_FNL.')
                    log.error('Exiting!')
                    sys.exit(1)
                gfs_fnl_cycle = this_cycle.strftime(fmt_yyyymmddhh)
                file_pattern = str(grib_dir) + '/gdas1.fnl0p25.' + gfs_fnl_cycle + '.f' +this_lead + '.grib2'
            else:
                log.error('ERROR: No option yet for icbc_source=' + icbc_source + ' for GFS_FNL in run_ungrib.py.')
                log.error('Exiting!')
                sys.exit(1)
            nml_list = [nml_tmp, 'namelist.wps.gfs_fnl']
            wps_nml_tmp = check_wps_nml_templates(temp_dir, nml_list)
            shutil.copy(wps_nml_tmp, 'namelist.wps.template')
        elif icbc_model in variants_gefs:
            pathlib.Path('Vtable').symlink_to(wps_dir.joinpath('ungrib','Variable_Tables','Vtable.GFSENS'))
            file_pattern = str(grib_dir) + '/pgrb2bp5/gep' + mem_id + '.t' + icbc_cycle_hr + 'z.pgrb2b.0p50.f' + lead_h_str3
            nml_list = [nml_tmp, 'namelist.wps.gefs_b']
            wps_nml_tmp = check_wps_nml_templates(temp_dir, nml_list)
            shutil.copy(wps_nml_tmp, 'namelist.wps.template')
        elif icbc_model in variants_hrrr:
            if hrrr_native:
                # Process native-grid HRRR output first, for atmospheric variables only (wrfnat files don't have soil)
                if icbc_analysis:
                    file_pattern = str(grib_dir) + '/hrrr.t' + this_dt_hh + 'z.wrfnatf00.grib2'
                else:
                    file_pattern = str(grib_dir) + '/hrrr.t' + icbc_cycle_hr + 'z.wrfnatf' + lead_h_str2 + '.grib2'
                pathlib.Path('Vtable').symlink_to(vtable_dir.joinpath('Vtable.raphrrr.hybr'))
                nml_list = [nml_tmp, 'namelist.wps.hrrr_hybr', 'namelist.wps.hrrr']
                wps_nml_tmp = check_wps_nml_templates(temp_dir, nml_list)
            else:
                # Process pressure-grid HRRR output only, for both atmospheric & soil variables
                if icbc_analysis:
                    file_pattern = str(grib_dir) + '/hrrr.t' + this_dt_hh + 'z.wrfprsf00.grib2'
                else:
                    file_pattern = str(grib_dir) + '/hrrr.t' + icbc_cycle_hr + 'z.wrfprsf' + lead_h_str2 + '.grib2'
                pathlib.Path('Vtable').symlink_to(vtable_dir.joinpath('Vtable.raphrrr.pres'))
                nml_list = [nml_tmp, 'namelist.wps.hrrr_pres', 'namelist.wps.hrrr']
                wps_nml_tmp = check_wps_nml_templates(temp_dir, nml_list)
            shutil.copy(wps_nml_tmp, 'namelist.wps.template')
        else:
            log.error('ERROR: Unrecognized icbc_model in run_ungrib.py.')
            log.error('Exiting!')
            sys.exit(1)

        # Run link_grib
        ret,output = exec_command(['./link_grib.csh', file_pattern], log)

        ## Modify the namelist for this date, running ungrib separately on each grib file
        with open('namelist.wps.template', 'r') as in_file, open('namelist.wps', 'w') as out_file:
            for line in in_file:
                if line.strip()[0:10] == 'start_date':
                    out_file.write(" start_date = '"+this_dt_wrf_str+"',\n")
                elif line.strip()[0:8] == 'end_date':
                    out_file.write(" end_date   = '"+this_dt_wrf_str+"',\n")
                elif line.strip()[0:6] == 'prefix':
                    # To run ungrib separately for each time and avoid having ungrib's clean-up deletion of all PFILE
                    # files in the folder where prefix points (which can cause other still-running instances of ungrib
                    # to crash with file not found errors), set prefix to use ungrib_dir rather than out_dir.
                    if icbc_model in variants_gfs:
                        out_file.write(" prefix = '"+str(ungrib_dir)+"/GFS',\n")
                    elif icbc_model in variants_gfs_fnl:
                        out_file.write(" prefix = '" + str(ungrib_dir) + "/GFS_FNL',\n")
                    elif icbc_model in variants_gefs:
                        out_file.write(" prefix = '"+str(ungrib_dir)+"/GEFS_B',\n")
                    elif icbc_model in variants_hrrr:
                        if hrrr_native:
                            out_file.write(" prefix = '"+str(ungrib_dir)+"/HRRR_hybr',\n")
                        else:
                            out_file.write(" prefix = '"+str(ungrib_dir)+"/HRRR_pres',\n")
                    else:
                        out_file.write(" prefix = '"+str(ungrib_dir)+"/FILE',\n")
                else:
                    out_file.write(line)

        ## If the expected output file exists in its temporary location (ungrib_dir), delete it first
        ## This enables checking for its existence later as proof of successful completion
        if icbc_model in variants_gfs:
            ungribbed_file = ungrib_dir.joinpath('GFS:' + this_dt_wrf_date_hh)
        elif icbc_model in variants_gfs_fnl:
            ungribbed_file = ungrib_dir.joinpath('GFS_FNL:' + this_dt_wrf_date_hh)
        elif icbc_model in variants_gefs:
            ungribbed_file = ungrib_dir.joinpath('GEFS_B:' + this_dt_wrf_date_hh)
        elif icbc_model in variants_hrrr:
            if hrrr_native:
                ungribbed_file = ungrib_dir.joinpath('HRRR_hybr:' + this_dt_wrf_date_hh)
            else:
                ungribbed_file = ungrib_dir.joinpath('HRRR_pres:' + this_dt_wrf_date_hh)
        else:
            ungribbed_file = ungrib_dir.joinpath('FILE:' + this_dt_wrf_date_hh)
        if ungribbed_file.is_file():
            ungribbed_file.unlink()

        ## Delete old log files
        ret,output = exec_command(['rm', 'ungrib.log'], log, exit_on_fail=False, verbose=False)
        files = glob.glob('ungrib.o[0-9]*')
        for file in files:
            ret,output = exec_command(['rm', file], log, exit_on_fail=False, verbose=False)
        files = glob.glob('ungrib.e[0-9]*')
        for file in files:
            ret, output = exec_command(['rm', file], log, exit_on_fail=False, verbose=False)
        files = glob.glob('log_ungrib.o[0-9]*')
        for file in files:
            ret,output = exec_command(['rm', file], log, exit_on_fail=False, verbose=False)
        files = glob.glob('log_ungrib.e[0-9]*')
        for file in files:
            ret, output = exec_command(['rm', file], log, exit_on_fail=False, verbose=False)

        # Submit ungrib and get the job ID as a string in case it's useful
        # Set wait=True to force subprocess.run to wait for stdout echoed from the job scheduler
        if scheduler == 'slurm':
            ret,output = exec_command(['sbatch','submit_ungrib.bash'], log, wait=True)
            jobid = output.split('job ')[1].split('\\n')[0]
            log.info('Submitted batch job '+jobid)
            jobid_list[tt] = jobid
        elif scheduler == 'pbs':
            ret,output = exec_command(['qsub', 'submit_ungrib.bash'], log, wait=True)
            jobid = output.split('.')[0]
            queue = output.split('.')[1]
            log.info('Submitted batch job '+jobid+' to queue '+queue)
            jobid_list[tt] = jobid
        time.sleep(short_time)

    ## Loop back through the run directories, verifying that each ungrib job finished successfully
    for tt in range(n_times):
        this_dt = all_dt[tt]
        this_dt_yyyymmdd_hh = this_dt.strftime(fmt_yyyymmdd_hh)
        this_dt_wrf_date_hh = this_dt.strftime(fmt_wrf_date_hh)

        if icbc_model in variants_gefs:
            ungrib_dir = run_dir.joinpath('ungrib_'+this_dt_yyyymmdd_hh+'_b')
        elif icbc_model in variants_hrrr:
            if hrrr_native:
                ungrib_dir = run_dir.joinpath('ungrib_' + this_dt_yyyymmdd_hh + '_hybr')
            else:
                ungrib_dir = run_dir.joinpath('ungrib_' + this_dt_yyyymmdd_hh + '_pres')
        else:
            ungrib_dir = run_dir.joinpath('ungrib_'+this_dt_yyyymmdd_hh)
        os.chdir(ungrib_dir)

        time.sleep(short_time)

        if scheduler == 'slurm':
            ret,output = exec_command([f'{curr_dir}/check_job_status.sh', jobid_list[tt]], log)
        elif scheduler == 'pbs':
            log.info('WARNING: check_job_status.sh needs to be modified to handle PBS calls')

        ## First, ensure the job is running/did run and created a log file
        status = False
        while not status:
            if not pathlib.Path('ungrib.log').is_file():
                time.sleep(long_time)
            else:
                status = True
        ## Second, look for success/error messages in the log file
        status = False
        while not status:
            if search_file('ungrib.log', 'Successful completion of program ungrib.exe'):
                status = True
            else:
                # May need to add more error message patterns to search for
                fnames = ['ungrib.log', 'ungrib.e' + jobid_list[tt], 'ungrib.o' + jobid_list[tt],
                          'log_ungrib.e' + jobid_list[tt], 'log_ungrib.o' + jobid_list[tt]]
                patterns = ['FATAL', 'Fatal', 'ERROR', 'Error', 'BAD TERMINATION', 'forrtl:', 'unrecognized option']
                for fname in fnames:
                    if ungrib_dir.joinpath(fname).is_file():
                        for pattern in patterns:
                            if search_file(str(ungrib_dir) + '/' + fname, pattern):
                                log.error('ERROR: ungrib.exe failed.')
                                log.error('Consult ' + str(ungrib_dir) + '/' + fname + ' for potential error messages.')
                                log.error('Exiting!')
                                sys.exit(1)

                time.sleep(long_time)

        # Now move each ungribbed file to the main ungrib directory, where metgrid will expect to find them all
        if icbc_model in variants_gfs:
            ret,output = exec_command(['mv', 'GFS:' + this_dt_wrf_date_hh, str(out_dir)], log)
        elif icbc_model in variants_gfs_fnl:
            ret,output = exec_command(['mv', 'GFS_FNL:' + this_dt_wrf_date_hh, str(out_dir)], log)
        elif icbc_model in variants_gefs:
            ret,output = exec_command(['mv', 'GEFS_B:' + this_dt_wrf_date_hh, str(out_dir)], log)
        elif icbc_model in variants_hrrr:
            if hrrr_native:
                ret, output = exec_command(['mv', 'HRRR_hybr:' + this_dt_wrf_date_hh, str(out_dir)], log)
            else:
                ret, output = exec_command(['mv', 'HRRR_pres:' + this_dt_wrf_date_hh, str(out_dir)], log)
        else:
            ret,output = exec_command(['mv', 'FILE:' + this_dt_wrf_date_hh, str(out_dir)], log)

    ## If GEFS, run ungrib for the a files, too
    # Or if HRRR and using native-grid output for atmospheric vars, run ungrib on pressure-level output for soil vars
    ## Could potentially merge this back in with loop above to get through all ungrib processes a bit faster,
    ## but keeping them as two separate code blocks is a little bit cleaner/easier to read. Maybe could do
    ## the same thing by making much of this code into a function.
    if icbc_model in variants_gefs or (icbc_model in variants_hrrr and hrrr_native):

        # Re-initialize empty jobid list to be filled in later to allow tracking of each ungrib job
        jobid_list = [''] * n_times

        ## Loop over times
        for tt in range(n_times):
            this_dt = all_dt[tt]
            this_hh = this_dt.strftime(fmt_hh)
            this_dt_yyyymmdd = this_dt.strftime(fmt_yyyymmdd)
            this_dt_wrf_str = this_dt.strftime(fmt_wrf_dt)
            this_dt_wrf_date_hh = this_dt.strftime(fmt_wrf_date_hh)
            this_dt_yyyymmdd_hh = this_dt.strftime(fmt_yyyymmdd_hh)
            this_dt_yyyymmdd_hhmm = this_dt.strftime(fmt_yyyymmdd_hhmm)
            log.info('Processing date '+this_dt_yyyymmdd_hh)

            # For some IC/LBC models, gribfiles are stored in directories by date rather than cycle hour
            if icbc_model in variants_hrrr:
                if icbc_analysis:
                    # All icbc files come from different HRRR model cycles (f00 each cycle)
                    grib_dir = grib_dir_parent.joinpath('hrrr.' + this_dt_yyyymmdd, 'conus')
                else:
                    # All icbc files come from a single HRRR model cycle
                    grib_dir = grib_dir_parent.joinpath('hrrr.' + icbc_cycle_date, 'conus')

            ## Calculate the lead hour for this cycle, accounting for the possible icbc_fc_dt offset
            lead_h = int((this_dt - cycle_dt).total_seconds() // 3600) + icbc_fc_dt
            lead_h_str3 = str(lead_h).zfill(3)
            lead_h_str2 = str(lead_h).zfill(2)

            if icbc_model in variants_gefs:
                ungrib_dir = run_dir.joinpath('ungrib_' + this_dt_yyyymmdd_hh + '_a')
            elif icbc_model in variants_hrrr:
                ungrib_dir = run_dir.joinpath('ungrib_' + this_dt_yyyymmdd_hh + '_soil')
            else:
                log.error('ERROR: Unknown icbc_model option in the second ungrib loop in run_ungrib.py.')
                log.error('Exiting!')
                sys.exit(1)
            ungrib_dir.mkdir(parents=True, exist_ok=True)
            os.chdir(ungrib_dir)

            ## Link to ungrib-related executables & scripts
            if pathlib.Path('ungrib.exe').is_symlink():
                pathlib.Path('ungrib.exe').unlink()
            if pathlib.Path('link_grib.csh').is_symlink():
                pathlib.Path('link_grib.csh').unlink()
            pathlib.Path('ungrib.exe').symlink_to(wps_dir.joinpath('ungrib.exe'))
            pathlib.Path('link_grib.csh').symlink_to(wps_dir.joinpath('link_grib.csh'))

            ## Copy over the ungrib submission script
            # Add special handling for derecho & casper, since peer scheduling is possible
            if hostname == 'derecho':
                shutil.copy(temp_dir.joinpath('submit_ungrib.bash.derecho'), 'submit_ungrib.bash')
            elif hostname == 'casper':
                shutil.copy(temp_dir.joinpath('submit_ungrib.bash.casper'), 'submit_ungrib.bash')
            else:
                shutil.copy(temp_dir.joinpath('submit_ungrib.bash'), 'submit_ungrib.bash')

            ## Link to the correct Vtable, grib/grib2 files, and copy in a namelist template
            if pathlib.Path('Vtable').is_symlink():
                pathlib.Path('Vtable').unlink()
            if pathlib.Path('namelist.wps').is_file():
                pathlib.Path('namelist.wps').unlink()

            # To speed up ungrib, link only to the specific file for the time being processed, not all gribfiles
            if icbc_model in variants_gefs:
                pathlib.Path('Vtable').symlink_to(wps_dir.joinpath('ungrib','Variable_Tables','Vtable.GFSENS'))
                file_pattern = 'pgrb2ap5/gep' + mem_id + '.t' + icbc_cycle_hr + 'z.pgrb2a.0p50.f' + lead_h_str3
                nml_list = [nml_tmp, 'namelist.wps.gefs_a']
                wps_nml_tmp = check_wps_nml_templates(temp_dir, nml_list)
                shutil.copy(wps_nml_tmp, 'namelist.wps.template')
            elif icbc_model in variants_hrrr:
                vtable_soil = vtable_dir.joinpath('Vtable.raphrrr.soil_only')
                if not vtable_soil.is_file():
                    log.error('ERROR: File ' + str(vtable_soil) + ' not found.')
                    log.error('Please ensure there is a Vtable by this name available to process only soil variables.')
                    log.error('Exiting!')
                    sys.exit(1)
                pathlib.Path('Vtable').symlink_to(vtable_soil)
                if icbc_analysis:
                    file_pattern = 'hrrr.t' + this_hh + 'z.wrfprsf00.grib2'
                else:
                    file_pattern = 'hrrr.t' + icbc_cycle_hr + 'z.wrfprsf' + lead_h_str2 + '.grib2'
                nml_list = [nml_tmp, 'namelist.wps.hrrr.pres', 'namelist.wps.hrrr']
                wps_nml_tmp = check_wps_nml_templates(temp_dir, nml_list)
                shutil.copy(wps_nml_tmp, 'namelist.wps.template')
            else:
                log.error('ERROR: Unknown icbc_model option in the second ungrib loop in run_ungrib.py.')
                log.error('Exiting!')
                sys.exit(1)

            # Now run link_grib.csh
            ret, output = exec_command(['./link_grib.csh', str(grib_dir) + '/' + file_pattern], log)

            ## Modify the namelist for this date, running ungrib separately on each grib file
            with open('namelist.wps.template', 'r') as in_file, open('namelist.wps', 'w') as out_file:
                for line in in_file:
                    if line.strip()[0:10] == 'start_date':
                        out_file.write(" start_date = '"+this_dt_wrf_str+"',\n")
                    elif line.strip()[0:8] == 'end_date':
                        out_file.write(" end_date   = '"+this_dt_wrf_str+"',\n")
                    elif line.strip()[0:6] == 'prefix':
                        if icbc_model in variants_gefs:
                            out_file.write(" prefix = '"+str(ungrib_dir)+"/GEFS_A',\n")
                        elif icbc_model in variants_hrrr:
                            out_file.write(" prefix = '"+str(ungrib_dir)+"/HRRR_soil',\n")
                    else:
                        out_file.write(line)

            ## If the expected output file already exists, delete it first
            if icbc_model in variants_gefs:
                ungribbed_file = ungrib_dir.joinpath('GEFS_A:' + this_dt_wrf_date_hh)
            elif icbc_model in variants_hrrr:
                ungribbed_file = ungrib_dir.joinpath('HRRR_soil' + this_dt_wrf_date_hh)
            else:
                log.error('ERROR: Unknown icbc_model option in the second ungrib loop in run_ungrib.py.')
                log.error('Exiting!')
                sys.exit(1)
            if ungribbed_file.is_file():
                ungribbed_file.unlink()

            ## Delete old log files
            ret,output = exec_command(['rm', 'ungrib.log'], log, False, False)
            files = glob.glob('ungrib.o[0-9]*')
            for file in files:
                ret,output = exec_command(['rm', file], log, False, False)
            files = glob.glob('ungrib.e[0-9]*')
            for file in files:
                ret,output = exec_command(['rm', file], log, False, False)
            files = glob.glob('log_ungrib.o[0-9]*')
            for file in files:
                ret, output = exec_command(['rm', file], log, False, False)
            files = glob.glob('log_ungrib.e[0-9]*')
            for file in files:
                ret, output = exec_command(['rm', file], log, False, False)

            # Submit ungrib and get the job ID as a string in case it's useful
            # Set wait=True to force subprocess.run to wait for stdout echoed from the job scheduler
            if scheduler == 'slurm':
                ret,output = exec_command(['sbatch', 'submit_ungrib.bash'], log, wait=True)
                jobid = output.split('job ')[1].split('\\n')[0].strip()
                log.info('Submitted batch job '+jobid)
                jobid_list[tt] = jobid
            elif scheduler == 'pbs':
                ret,output = exec_command(['qsub', 'submit_ungrib.bash'], log, wait=True)
                jobid = output.split('.')[0]
                queue = output.split('.')[1]
                log.info('Submitted batch job '+jobid+' to queue '+queue)
                jobid_list[tt] = jobid
            time.sleep(short_time)

        ## Loop back through the run directories, verifying that each ungrib job finished successfully
        for tt in range(n_times):
            this_dt = all_dt[tt]
            this_dt_yyyymmdd_hh = this_dt.strftime(fmt_yyyymmdd_hh)
            this_dt_wrf_date_hh = this_dt.strftime(fmt_wrf_date_hh)

            if icbc_model in variants_gefs:
                ungrib_dir = run_dir.joinpath('ungrib_'+this_dt_yyyymmdd_hh+'_a')
            elif icbc_model in variants_hrrr:
                ungrib_dir = run_dir.joinpath('ungrib_'+this_dt_yyyymmdd_hh+'_soil')
            else:
                print('ERROR: Unknown icbc_model option in the second ungrib loop in run_ungrib.py.')
                print('Exiting!')
                sys.exit(1)
            os.chdir(ungrib_dir)

            ## First, ensure the job is running/did run and created a log file
            time.sleep(short_time)

            if scheduler == 'slurm':
                ret,output = exec_command([f'{curr_dir}/check_job_status.sh',jobid], log)
            elif scheduler == 'pbs':
                log.info('WARNING: check_job_status.sh needs to be modified to handle PBS calls')

            status = False
            while not status:
                if not pathlib.Path('ungrib.log').is_file():
                    time.sleep(long_time)
                else:
                    status = True
            ## Second, look for success/error messages in the log file
            status = False
            while not status:
                if search_file('ungrib.log', '*** Successful completion of program ungrib.exe ***'):
                    status = True
                else:
                    # Add other error message patterns to search for if needed
                    fnames = ['ungrib.log', 'ungrib.e' + jobid_list[tt], 'ungrib.o' + jobid_list[tt],
                              'log_ungrib.e' + jobid_list[tt], 'log_ungrib.o' + jobid_list[tt]]
                    patterns = ['FATAL', 'Fatal', 'ERROR', 'Error', 'BAD TERMINATION', 'forrtl:', 'unrecognized option']
                    for fname in fnames:
                        if ungrib_dir.joinpath(fname).is_file():
                            for pattern in patterns:
                                if search_file(str(ungrib_dir) + '/' + fname, pattern):
                                    log.error('ERROR: ungrib.exe failed.')
                                    log.error('Consult ' + str(ungrib_dir) + '/' + fname + ' for potential error messages.')
                                    log.error('Exiting!')
                                    sys.exit(1)

                    time.sleep(long_time)

            # Now move each ungribbed file to the main ungrib directory, where metgrid will expect to find them all
            if icbc_model in variants_gefs:
                ret, output = exec_command(['mv', 'GEFS_A:' + this_dt_wrf_date_hh, str(out_dir)], log)
            elif icbc_model in variants_hrrr:
                ret, output = exec_command(['mv', 'HRRR_soil:' + this_dt_wrf_date_hh, str(out_dir)], log)

    log.info('SUCCESS! All ungrib jobs completed successfully.')


if __name__ == '__main__':
    now_time_beg = dt.datetime.now(dt.UTC)
    (cycle_dt, sim_hrs, wps_dir, run_dir, out_dir, grib_dir, temp_dir, icbc_source, icbc_model, int_hrs, icbc_fc_dt,
     scheduler, mem_id, hostname, hrrr_native, icbc_analysis, nml_tmp) = parse_args()
    main(cycle_dt, sim_hrs, wps_dir, run_dir, out_dir, grib_dir, temp_dir, icbc_source, icbc_model, int_hrs, icbc_fc_dt,
         scheduler, mem_id, hostname, hrrr_native, icbc_analysis, nml_tmp)
    now_time_end = dt.datetime.now(dt.UTC)
    run_time_tot = now_time_end - now_time_beg
    now_time_beg_str = now_time_beg.strftime('%Y-%m-%d %H:%M:%S')
    now_time_end_str = now_time_end.strftime('%Y-%m-%d %H:%M:%S')
    log.info('')
    log.info(this_file + ' completed successfully.')
    log.info('Beg time: '+now_time_beg_str)
    log.info('End time: '+now_time_end_str)
    log.info('Run time: '+str(run_time_tot)+'\n')
