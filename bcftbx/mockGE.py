#     mockGE.py: mock Grid Engine functionality for testing
#     Copyright (C) University of Manchester 2018 Peter Briggs
#
#######################################################################

"""
Utility class for simulating Grid Engine (GE) functionality

Provides a single class `MockGE`, which implements methods for
simulating the functionality provided by the Grid Engine command
line utilities, and a function `setup_mock_GE`, which creates
mock versions of those utilities ('qsub', 'qstat' and 'qacct').
"""

#######################################################################
# Imports
#######################################################################

import os
import sys
import sqlite3
import argparse
import subprocess
import getpass
import time
import datetime
import logging

#######################################################################
# Classes
#######################################################################

class MockGE(object):
    """
    Class implementing qsub, qstat and qacct-like functionality

    Job data is stored in an SQLite3 database in the 'database
    directory' (defaults to '$HOME/.mockGE'); scripts and job
    exit status files are also written to this directory.
    """
    def __init__(self,max_jobs=4,qacct_delay=15,shell='/bin/bash',
                 database_dir=None,debug=False):
        """
        Create a new MockGE instance

        Arguments:
          max_jobs (int): maximum number of jobs to run at
            once; additional jobs will be queued
          qacct_delay (int): number of seconds that must elapse
            from job finishing to providing 'qacct' info
          shell (str): shell to run internal scripts using
          database_dir (str): path to directory used for
            managing the mockGE functionality (defaults to
            '$HOME/.mockGE')
          debug (bool): if True then turn on debugging output
        """
        if database_dir is None:
            database_dir = os.path.join(self._user_home(),
                                        ".mockGE")
        self._database_dir = os.path.abspath(database_dir)
        self._db_file = os.path.join(self._database_dir,
                                     "mockGE.sqlite")
        if not os.path.exists(self._database_dir):
            os.mkdir(self._database_dir)
        init_db = False
        if not os.path.exists(self._db_file):
            init_db = True
        try:
            logging.debug("Connecting to DB")
            self._cx = sqlite3.connect(self._db_file)
        except Exception as ex:
            print "Exception connecting to DB: %s" % ex
            raise ex
        if init_db:
            logging.debug("Setting up DB")
            self._init_db()
        self._shell = shell
        self._max_jobs = max_jobs
        self._qacct_delay = qacct_delay
        if debug:
            logging.getLogger().setLevel(logging.DEBUG)

    def _init_db(self):
        """
        Set up the persistent database
        """
        sql = """
        CREATE TABLE jobs (
          id          INTEGER PRIMARY KEY,
          user        CHAR,
          state       CHAR,
          name        VARCHAR,
          command     VARCHAR,
          working_dir VARCHAR,
          output_name VARCHAR,
          queue       VARCHAR,
          join_output CHAR,
          pid         INTEGER,
          qsub_time   FLOAT,
          start_time  FLOAT,
          end_time    FLOAT,
          exit_code   INTEGER
        )
        """
        try:
            cu = self._cx.cursor()
            cu.execute(sql)
            self._cx.commit()
        except sqlite3.Error as ex:
            print "Failed to set up database: %s" % ex
            raise ex

    def _init_job(self,name,command,working_dir,queue,output_name,join_output):
        """
        Create a new job id
        """
        cmd = []
        for arg in command:
            try:
                arg.index(' ')
                arg = '"%s"' % arg
            except ValueError:
                pass
            cmd.append(arg)
        command = ' '.join(cmd)
        logging.debug("_init_job: cmd: %s" % cmd)
        sql = """
        INSERT INTO jobs (user,state,qsub_time,name,command,working_dir,queue,output_name,join_output)
        VALUES ('%s','%s',%f,'%s','%s','%s','%s','%s','%s')
        """ % (self._user(),'qw',time.time(),name,command,working_dir,
               queue,output_name,join_output)
        cu = self._cx.cursor()
        cu.execute(sql)
        self._cx.commit()
        return cu.lastrowid

    def _start_job(self,job_id):
        """
        Start a job running
        """
        # Get job info
        sql = """
        SELECT name,command,working_dir,output_name,join_output
        FROM jobs WHERE id==%d
        """ % job_id
        cu = self._cx.cursor()
        cu.execute(sql)
        job = cu.fetchone()
        name = job[0]
        command = job[1]
        working_dir = job[2]
        output_name = job[3]
        join_output = job[4]
        # Output file basename
        if output_name:
            out = os.path.abspath(output_name)
            if os.path.isdir(out):
                out = os.path.join(out,name)
            elif not os.path.isabs(out):
                out = os.path.join(working_dir,out)
        else:
            out = os.path.join(working_dir,name)
        logging.debug("Output basename: %s" % out)
        # Set up stdout and stderr targets
        stdout_file = "%s.o%s" % (out,job_id)
        stdout = open(stdout_file,'w')
        logging.debug("Stdout: %s" % stdout_file)
        if join_output == 'y':
            stderr = subprocess.STDOUT
        else:
            stderr_file = "%s.e%s" % (out,job_id)
            stderr = open(stderr_file,'w')
            logging.debug("Stderr: %s" % stderr_file)
        # Build a script to run the command
        script_file = os.path.join(self._database_dir,
                                   "__job%d.sh" % job_id)
        with open(script_file,'w') as fp:
            fp.write("""#!%s
%s
exit_code=$?
echo "$exit_code" > %s/__exit_code.%d
""" % (self._shell,command,self._database_dir,job_id))
        os.chmod(script_file,0775)
        # Run the command
        p = subprocess.Popen(script_file,
                             cwd=working_dir,
                             stdout=stdout,
                             stderr=stderr)
        # Capture the job id from the output
        pid = str(p.pid)
        # Update the database
        sql = """
        UPDATE jobs SET pid=%s,state='r',start_time=%f
        WHERE id=%s
        """ % (pid,time.time(),job_id)
        cu = self._cx.cursor()
        cu.execute(sql)
        self._cx.commit()

    def _update_jobs(self):
        """
        Update all job info
        """
        # Get jobs that have finished running
        cu = self._cx.cursor()
        sql = """
        SELECT id,pid FROM jobs WHERE state=='r'
        """
        cu.execute(sql)
        jobs = cu.fetchall()
        finished_jobs = []
        for job in jobs:
            job_id = job[0]
            pid = job[1]
            try:
                # See https://stackoverflow.com/a/7647264/579925
                logging.debug("Checking job=%d pid=%d" % (job_id,pid))
                os.kill(pid,0)
            except Exception as ex:
                logging.debug("Exception: %s" % ex)
                finished_jobs.append(job_id)
        logging.debug("Finished jobs: %s" % finished_jobs)
        for job_id in finished_jobs:
            # Clean up
            script_file = os.path.join(self._database_dir,
                                       "__job%d.sh" % job_id)
            if os.path.exists(script_file):
                os.remove(script_file)
            # Exit code
            exit_code_file = os.path.join(self._database_dir,
                                          "__exit_code.%d" % job_id)
            if os.path.exists(exit_code_file):
                end_time = os.path.getctime(exit_code_file)
                with open(exit_code_file,'r') as fp:
                    exit_code = int(fp.read())
                os.remove(exit_code_file)
            else:
                logging.error("Missing __exit_code file for job %s"
                            % job_id)
                end_time = time.time()
                exit_code = 1
            # Update database
            sql = """
            UPDATE jobs SET state='c',exit_code=%d,end_time=%f
            WHERE id==%d
            """ % (exit_code,end_time,job_id)
            logging.debug("SQL: %s" % sql)
            cu.execute(sql)
        if finished_jobs:
            self._cx.commit()
        # Get jobs that are waiting
        sql = """
        SELECT id FROM jobs WHERE state == 'qw'
        """
        cu.execute(sql)
        jobs = cu.fetchall()
        waiting_jobs = [job[0] for job in jobs]
        for job_id in waiting_jobs:
            sql = """
            SELECT id,pid FROM jobs WHERE state=='r'
            """
            cu.execute(sql)
            nrunning = len(cu.fetchall())
            if nrunning < self._max_jobs:
                self._start_job(job_id)
            else:
                break
        
    def _list_jobs(self,user,state=None):
        """
        Get list of the jobs
        """
        sql = """
        SELECT id,name,user,state,qsub_time,start_time,queue FROM jobs WHERE state != 'c'
        """
        if user != "\*" and user != "*":
            sql += "AND user == '%s'" % user
        cu = self._cx.cursor()
        cu.execute(sql)
        return cu.fetchall()

    def _job_info(self,job_id):
        """
        Return info on a job
        """
        sql = """
        SELECT id,name,user,exit_code,qsub_time,start_time,end_time,queue
        FROM jobs WHERE id==%d AND state=='c'
        """ % (job_id)
        cu = self._cx.cursor()
        cu.execute(sql)
        return cu.fetchone()

    def _user(self):
        """
        Get the current user name
        """
        return getpass.getuser()

    def _user_home(self):
        """
        Get the current user home directory
        """
        return os.path.expanduser("~%s" % self._user())

    def qsub(self,argv):
        """
        Implement qsub-like functionality
        """
        # Process supplied arguments
        p = argparse.ArgumentParser()
        p.add_argument("-b",action="store")
        p.add_argument("-V",action="store_true")
        p.add_argument("-N",action="store")
        p.add_argument("-cwd",action="store_true")
        p.add_argument("-wd",action="store")
        p.add_argument("-pe",action="store",nargs=2)
        p.add_argument("-j",action="store")
        p.add_argument("-o",action="store")
        p.add_argument("-e",action="store")
        args,cmd = p.parse_known_args(argv)
        # Command
        logging.debug("qsub: cmd: %s" % cmd)
        if len(cmd) == 1:
            cmd = cmd[0].split(' ')
        # Job name
        if args.N is not None:
            name = str(args.N)
        else:
            name = cmd[0].split(' ')[0]
        logging.debug("Name: %s" % name)
        # Working directory
        if args.wd:
            working_dir = os.path.abspath(args.wd)
        else:
            working_dir = os.getcwd()
        logging.debug("Working dir: %s" % working_dir)
        # Queue
        queue = "mock.q"
        # Output options
        if args.o:
            output_name = args.o
        else:
            output_name = ''
        if args.j == 'y':
            join_output = 'y'
        else:
            join_output = 'n'
        # Create an initial entry in job table
        job_id = self._init_job(name,cmd,working_dir,queue,
                                output_name,join_output)
        logging.debug("Created job %s" % job_id)
        # Report the job id
        print "Your job %s (\"%s\") has been submitted" % (job_id,
                                                           name)
        self._update_jobs()

    def qstat(self,argv):
        """
        Implement qstat-like functionality
        """
        # Example qstat output
        # job-ID  prior   name       user         state submit/start at     queue                          slots ja-task-ID 
        #-----------------------------------------------------------------------------------------------------------------
        # 1119861 0.39868 myawesomej user1        r     07/09/2018 16:53:03 serial.q@node001               48
        # ...
        #
        # Update the db
        self._update_jobs()
        # Process supplied arguments
        p = argparse.ArgumentParser()
        p.add_argument("-u",action="store")
        args = p.parse_args(argv)
        # User
        user = args.u
        if user is None:
            user = self._user()
        # Get jobs
        jobs = self._list_jobs(user=user)
        if not jobs:
            return
        # Print job info
        print """job-ID  prior   name       user         state submit/start at     queue                          slots ja-task-ID
-----------------------------------------------------------------------------------------------------------------"""
        for job in jobs:
            job_id = str(job[0])
            name = str(job[1])
            user = str(job[2])
            state = str(job[3])
            start_time = job[5]
            queue = job[6]
            if start_time is None:
                start_time = job[4]
            start_time = datetime.datetime.fromtimestamp(start_time).strftime("%m/%d/%Y %H:%M:%S")
            line = []
            line.append("%s%s" % (job_id[:7],' '*(7-len(job_id))))
            line.append("0.00001")
            line.append("%s%s" % (name[:10],' '*(10-len(name))))
            line.append("%s%s" % (user[:12],' '*(12-len(user))))
            line.append("%s%s" % (state[:5],' '*(5-len(state))))
            line.append("%s" % start_time)
            line.append("%s%s" % (queue[:30],' '*(30-len(queue))))
            line.append("1")
            print ' '.join(line)

    def qacct(self,argv):
        """
        Implement qacct-like functionality
        """
        # Example qacct output
        # ==============================================================
        # qname        mock.q  
        # hostname     node001
        # group        mygroup               
        # owner        user1            
        # project      NONE                
        # department   defaultdepartment   
        # jobname      echo                
        # jobnumber    1162479             
        # taskid       undefined
        # account      sge                 
        # priority     0                   
        # qsub_time    Mon Jul 16 15:56:45 2018
        # start_time   Mon Jul 16 15:56:46 2018
        # end_time     Mon Jul 16 15:56:47 2018
        # granted_pe   NONE                
        # slots        1                   
        # failed       0    
        # exit_status  0
        # ....
        #
        logging.debug("qacct: invoked")
        # Update the db
        self._update_jobs()
        # Process supplied arguments
        p = argparse.ArgumentParser()
        p.add_argument("-j",action="store")
        args = p.parse_args(argv)
        # Job id
        job_id = int(args.j)
        # Get job info
        job_info = self._job_info(job_id)
        if job_info is None:
            logging.debug("qacct: no info returned for job %s" %
                          job_id)
            sys.stderr.write("error: job id %s not found\n" % job_id)
            return
        # Check delay time
        elapsed_since_job_end = time.time() - job_info[6]
        logging.debug("qacct: elapsed time: %s" % elapsed_since_job_end)
        if elapsed_since_job_end < self._qacct_delay:
            return
        # Print info
        job_id = job_info[0]
        name = job_info[1]
        user = job_info[2]
        exit_code = job_info[3]
        qsub_time = datetime.datetime.fromtimestamp(job_info[4]).strftime("%c")
        start_time = datetime.datetime.fromtimestamp(job_info[5]).strftime("%c")
        end_time = datetime.datetime.fromtimestamp(job_info[6]).strftime("%c")
        queue = job_info[7]
        print """==============================================================
qname        %s  
hostname     node001
group        mygroup               
owner        %s            
project      NONE                
department   defaultdepartment   
jobname      %s                
jobnumber    %s             
taskid       undefined
account      sge                 
priority     0                   
qsub_time    %s
start_time   %s
end_time     %s
granted_pe   NONE                
slots        1                   
failed       0    
exit_status  %s""" % (queue,user,name,job_id,
                      qsub_time,start_time,end_time,
                      exit_code)

#######################################################################
# Classes
#######################################################################

def setup_mock_GE(bindir=None):
    """
    Creates mock 'qsub', 'qstat' and 'qacct' exes
    """
    # Bin directory
    if bindir is None:
        bindir = os.getcwd()
    # qsub
    qsub = os.path.join(bindir,"qsub")
    with open(qsub,'w') as fp:
        fp.write("""#!/usr/bin/env python
import sys
from bcftbx.mockGE import MockGE
sys.exit(MockGE().qsub(sys.argv[1:]))
""")
    os.chmod(qsub,0775)
    # qstat
    qstat = os.path.join(bindir,"qstat")
    with open(qstat,'w') as fp:
        fp.write("""#!/usr/bin/env python
import sys
from bcftbx.mockGE import MockGE
sys.exit(MockGE().qstat(sys.argv[1:]))
""")
    os.chmod(qstat,0775)
    # qacct
    qacct = os.path.join(bindir,"qacct")
    with open(qacct,'w') as fp:
        fp.write("""#!/usr/bin/env python
import sys
from bcftbx.mockGE import MockGE
sys.exit(MockGE().qacct(sys.argv[1:]))
""")
    os.chmod(qacct,0775)
