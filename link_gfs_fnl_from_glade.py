#!/usr/bin/env python3

"""
link_gfs_fnl_from_glade.py

Created by: Jared A. Lee (jaredlee@ucar.edu)
Created on: 4 Feb 2025

This script links to GFS FNL 0.25-deg output files stored on GLADE at NSF NCAR for the requested times for ICs/LBCs.
For every 6-hourly GFS cycle, GFS FNL files are stored every 3 hours for 0–9 hour lead times.
"""

import os
import sys
import argparse
import pathlib
import datetime as dt
import numpy as np
import pandas as pd
import logging
from proc_util import exec_command

this_file = os.path.basename(__file__)
logging.basicConfig(format=f'{this_file}: %(asctime)s - %(message)s', level=logging.DEBUG, datefmt='%Y-%m-%dT%H:%M:%S')
log = logging.getLogger(__name__)

long_time = 5
long_long_time = 15
short_time = 3
curr_dir=os.path.dirname(os.path.abspath(__file__))

def parse_args():
    ## Parse the command-line arguments
    parser = argparse.ArgumentParser()
    parser.add_argument('-b', '--cycle_dt', default='20220801_00',
                        help='WRF cycle start date/time [YYYYMMDD_HH] (default: 20220801_00)')
    parser.add_argument('-s', '--sim_hrs', default=48, type=int,
                        help='integer number of forecast hours to download (default: 48)')
    parser.add_argument('-o', '--out_dir_parent', default=None,
                        help='string or pathlib.Path object of the local parent directory where all downloaded GFS FNL data should be stored')
    parser.add_argument('-i', '--int_h', default=6, type=int,
                        help='integer number of hours between GFS FNL files to download (default: 6)')

    args = parser.parse_args()
    cycle_dt = args.cycle_dt
    sim_hrs = args.sim_hrs
    out_dir_parent = args.out_dir_parent
    int_h = args.int_h

    if len(cycle_dt) != 11:
        log.error('ERROR! Incorrect length for positional argument cycle_dt. Exiting!')
        parser.print_help()
        sys.exit(1)
    elif cycle_dt[8] != '_':
        log.error('ERROR! Incorrect format for positional argument cycle_dt. Exiting!')
        parser.print_help()
        sys.exit(1)

    if out_dir_parent is None:
        log.error('ERROR: out_dir_parent not specified. Exiting!')
        sys.exit(1)
    else:
        out_dir_parent = pathlib.Path(out_dir_parent)

    return cycle_dt, sim_hrs, out_dir_parent, int_h

def main(cycle_dt_str, sim_hrs, out_dir_parent, now_time_beg, interval):
    log.info(f'Running link_gfs_from_glade.py from directory: {curr_dir}')

    # Calculate the desired lead hours for this cycle, accounting for the possible icbc_fc_dt offset.
    # Build array of forecast lead times to download. GFS output on GLADE is 3-hourly.
    # leads = np.arange(icbc_fc_dt, sim_hrs + icbc_fc_dt + 1, interval)
    # n_leads = len(leads)

    fmt_yyyy = '%Y'
    fmt_mm = '%m'
    fmt_hh = '%H'
    fmt_yyyymm = '%Y%m'
    fmt_yyyymmdd = '%Y%m%d'
    fmt_yyyymmddhh = '%Y%m%d%H'
    fmt_yyyymmdd_hh = '%Y%m%d_%H'

    cycle_dt = pd.to_datetime(cycle_dt_str, format=fmt_yyyymmdd_hh)
    cycle_date = cycle_dt.strftime(fmt_yyyymmdd)
    cycle_year = cycle_dt.strftime(fmt_yyyy)
    cycle_month = cycle_dt.strftime(fmt_mm)
    cycle_hour = cycle_dt.strftime(fmt_hh)

    # Do some basic error checking for GFS FNL
    # Handle this differently in the future if desired to allow initializing from off-synoptic times
    if cycle_hour not in ['00', '06', '12', '18']:
        log.error('ERROR: When initializing from GFS FNL, please choose a WRF cycle time that starts from 00, 06, 12, or 18 UTC.')
        log.error('Exiting!')
        sys.exit(1)

    if interval not in [3, 6]:
        log.error('ERROR: Please choose either 3 or 6 for the interval when using GFS FNL, not ' + str(interval) + '.')
        log.error('Exiting!')
        sys.exit(1)

    cycle_dt_end = cycle_dt + dt.timedelta(hours=sim_hrs)
    valid_dt = pd.date_range(start=cycle_dt, end=cycle_dt_end, freq=str(interval) + 'h')
    n_valid = len(valid_dt)

    glade_dir_parent = pathlib.Path('/', 'glade', 'campaign', 'collections', 'rda', 'data', 'd083003')
    # glade_dir = glade_dir_parent.joinpath(cycle_year, cycle_date)

    # Loop over valid times
    for vv in range(n_valid):
        this_valid = valid_dt[vv]
        this_date = this_valid.strftime(fmt_yyyymmdd)
        this_hh = this_valid.strftime(fmt_hh)

        # Download GFS FNL files into date-specific directories
        out_dir = out_dir_parent.joinpath('gfs_fnl.' + this_date)
        out_dir.mkdir(parents=True, exist_ok=True)
        os.chdir(out_dir)

        # Always grab either the f00 or f03 files for GFS FNL
        if this_hh in ['00', '06', '12', '18']:
            this_lead = '00'
            this_cycle = this_valid
        elif this_hh in ['03', '09', '15', '21']:
            this_lead = '03'
            this_cycle = this_valid - dt.timedelta(hours=3)
        else:
            log.error('ERROR: this_hh = ' + this_hh + ', which is not a valid value for GFS FNL files.')
            log.error('Exiting!')
            sys.exit(1)

        this_cycle_datehh = this_cycle.strftime(fmt_yyyymmddhh)
        this_cycle_year = this_cycle.strftime(fmt_yyyy)
        this_cycle_yearmo = this_cycle.strftime(fmt_yyyymm)

        # Set the directory
        glade_dir = glade_dir_parent.joinpath(this_cycle_year, this_cycle_yearmo)

        # Set the GFS FNL filename on GLADE (likely different in other data repos)
        glade_fname = 'gdas1.fnl0p25.' + this_cycle_datehh + '.f' + this_lead + '.grib2'
        glade_file = glade_dir.joinpath(glade_fname)

        # First, check for the file's existence on GLADE
        if not glade_file.is_file():
            log.info('WARNING: File ' + str(glade_file) + ' does not exist. Looping to the next expected IC/LBC time.')
            continue

        # Second, check for the existence of the link/file where ungrib will expect to find it
        if not out_dir.joinpath(glade_fname).is_file():
            log.info('Linking to ' + str(glade_file) + ' in ' + str(out_dir))
            ret,output = exec_command(['ln', '-sf', str(glade_dir.joinpath(glade_fname)), '.'], log)
        else:
            log.info('   File ' + glade_fname + ' already exists locally. No need to re-link to it on GLADE.')



if __name__ == '__main__':
    now_time_beg = dt.datetime.now(dt.UTC)
    cycle_dt, sim_hrs, out_dir_parent, int_h = parse_args()
    main(cycle_dt, sim_hrs, out_dir_parent, now_time_beg, int_h)
    now_time_end = dt.datetime.now(dt.UTC)
    run_time_tot = now_time_end - now_time_beg
    now_time_beg_str = now_time_beg.strftime('%Y-%m-%d %H:%M:%S')
    now_time_end_str = now_time_end.strftime('%Y-%m-%d %H:%M:%S')
    log.info('')
    log.info(this_file + ' completed successfully.')
    log.info('   Beg time: ' + now_time_beg_str)
    log.info('   End time: ' + now_time_end_str)
    log.info('   Run time: ' + str(run_time_tot) + '\n')

