#!/usr/bin/env python3

'''
run_geogrid.py

Created by: Jared A. Lee (jaredlee@ucar.edu)
Created on: 26 Apr 2023

This script is designed to run geogrid.exe as a batch job and wait for its completion.
'''

import os
import sys
import argparse
import pathlib
import glob
import time
import shutil
import datetime as dt
import logging
from proc_util import exec_command

this_file = os.path.basename(__file__)
logging.basicConfig(format=f'{this_file}: %(asctime)s - %(message)s',
                    level=logging.DEBUG, datefmt='%Y-%m-%dT%H:%M:%S')
log = logging.getLogger(__name__)

long_time = 5
short_time = 3
curr_dir=os.path.dirname(os.path.abspath(__file__))

def parse_args():
	## Parse the command-line arguments
	parser = argparse.ArgumentParser()
	parser.add_argument('-w', '--wps_dir', default=None, help='string or pathlib.Path object of the WPS install directory')
	parser.add_argument('-r', '--run_dir', default=None, help='string or pathlib.Path object of the run directory where files should be linked and run')
	parser.add_argument('-t', '--tmp_dir', default=None, help='string or pathlib.Path object that hosts namelist & queue submission script templates')
	parser.add_argument('-n', '--nml_tmp', default=None, help='string for filename of namelist template (default: namelist.wps)')
	parser.add_argument('-q', '--scheduler', default='pbs', help='string specifying the cluster job scheduler (default: pbs)')
	parser.add_argument('-a', '--hostname', default='derecho', help='string specifying the hostname (default: derecho')

	args = parser.parse_args()
	wps_dir = args.wps_dir
	run_dir = args.run_dir
	tmp_dir = args.tmp_dir
	nml_tmp = args.nml_tmp
	scheduler = args.scheduler
	hostname = args.hostname

	if wps_dir is not None:
		wps_dir = pathlib.Path(wps_dir)
	else:
		log.error('ERROR! wps_dir not specified as an argument in call to run_geogrid.py. Exiting!')
		sys.exit(1)

	if run_dir is not None:
		run_dir = pathlib.Path(run_dir)
	else:
		log.error('ERROR! run_dir not specified as an argument in call to run_geogrid.py. Exiting!')
		sys.exit(1)

	if tmp_dir is not None:
		tmp_dir = pathlib.Path(tmp_dir)
	else:
		log.error('ERROR! tmp_dir is not specified as an argument in call to run_geogrid.py. Exiting!')
		sys.exit(1)

	if nml_tmp is None:
		## Make a default assumption about what namelist template we want to use
		nml_tmp = 'namelist.wps'

	return wps_dir, run_dir, tmp_dir, nml_tmp, scheduler, hostname

def main(wps_dir, run_dir, tmp_dir, nml_tmp, scheduler, hostname):

	## Create the run directory if it doesn't already exist
	run_dir.mkdir(parents=True, exist_ok=True)

	## Go to the run directory
	os.chdir(run_dir)

	## Link to geogrid.exe
	if pathlib.Path('geogrid.exe').is_symlink():
		pathlib.Path('geogrid.exe').unlink()
	pathlib.Path('geogrid.exe').symlink_to(wps_dir.joinpath('geogrid.exe'))

	## Copy over the geogrid batch script
	# Add special handling for derecho & casper, since peer scheduling is possible
	if hostname == 'derecho':
		shutil.copy(tmp_dir.joinpath('submit_geogrid.bash.derecho'), 'submit_geogrid.bash')
	elif hostname == 'casper':
		shutil.copy(tmp_dir.joinpath('submit_geogrid.bash.casper'), 'submit_geogrid.bash')
	else:
		shutil.copy(tmp_dir.joinpath('submit_geogrid.bash'), 'submit_geogrid.bash')


	## Copy over the default namelist
	shutil.copy(tmp_dir.joinpath(nml_tmp), 'namelist.wps')

	## Clean up old geogrid log files
	files = glob.glob('geogrid.log*')
	for file in files:
		ret,output = exec_command(['rm',file], log, False, False)
	files = glob.glob('log_geogrid.*')
	for file in files:
		ret,output = exec_command(['rm',file], log, False, False)
	files = glob.glob('geogrid.o*')
	for file in files:
		ret,output = exec_command(['rm',file], log, False, False)

	## Submit geogrid and get the job ID as a string
	if scheduler == 'slurm':
		ret,output = exec_command(['sbatch','submit_geogrid.bash'], log, False)
		jobid = output.split('job ')[1].split('\\n')[0].strip()
		log.info('Submitted batch job '+jobid)
	elif scheduler == 'pbs':
		ret,output = exec_command(['qsub','submit_geogrid.bash'], log, False)
		jobid = output.split('.')[0]
		queue = output.split('.')[1]
		log.info('Submitted batch job '+jobid+' to queue '+queue)
	time.sleep(long_time)	# give the file system a moment

	## Monitor the progress of geogrid
	status = False
	while not status:
		if not pathlib.Path('geogrid.log.0000').is_file() and not pathlib.Path('log_geogrid.o'+jobid).is_file():
			time.sleep(long_time)
		else:
			log.info('geogrid is now running on the cluster . . .')
			status = True
	status = False
	while not status:
		if '*** Successful completion of program geogrid.exe ***' in open('geogrid.log.0000').read():
			log.info('   SUCCESS! geogrid completed successfully.')
			time.sleep(short_time)  # brief pause to let the file system gather itself
			status = True
		else:
			## May need to add other error keywords to search for...
			if 'FATAL' in open('geogrid.log.0000').read() or 'Fatal' in open('geogrid.log.0000').read() or 'ERROR' in open('geogrid.log.0000').read():
				log.error('   ERROR: geogrid.exe failed.')
				log.error('   Consult '+str(run_dir)+'/geogrid.log.0000 for potential error messages.')
				log.error('   Exiting!')
				sys.exit(1)
			elif 'BAD TERMINATION' in open('log_geogrid.o'+jobid).read() or 'ERROR' in open('log_geogrid.o'+jobid).read():
				log.error('   ERROR: geogrid.exe failed.')
				log.error('   Consult '+str(run_dir)+'/log_geogrid.o'+jobid+' for potential error messages.')
				log.error('   Exiting!')
				sys.exit(1)
			time.sleep(long_time)


if __name__ == '__main__':
	now_time_beg = dt.datetime.now(dt.UTC)
	wps_dir, run_dir, tmp_dir, nml_tmp, scheduler, hostname = parse_args()
	main(wps_dir, run_dir, tmp_dir, nml_tmp, scheduler, hostname)
	now_time_end = dt.datetime.now(dt.UTC)
	run_time_tot = now_time_end - now_time_beg
	now_time_beg_str = now_time_beg.strftime('%Y-%m-%d %H:%M:%S')
	now_time_end_str = now_time_end.strftime('%Y-%m-%d %H:%M:%S')
	log.info('\nrun_geogrid.py completed.')
	log.info('   Beg time: '+now_time_beg_str)
	log.info('   End time: '+now_time_end_str)
	log.info('   Run time: '+str(run_time_tot)+'\n')
