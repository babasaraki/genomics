NGS-general
===========

General NGS scripts that are used for both ChIP-seq and RNA-seq.

explain_sam_flag.sh
-------------------
Convert a decimal bitwise SAM flag value to binary representation and
interpret each bit.

qc_boxplotter
-------------
Generate a QC boxplot from SOLiD .qual file.

SamStats
--------
Counts how many reads are uniquely mapped onto each chromosome or
contig in a SAM file. To run:

java -classpath <dir_with_SamStats.class> SamStats <sam_file>

or (if using a Jar file):

java -cp /path/to/SamStats.jar SamStats <sam_file>

(To compile into a jar, do "jar cf SamStats.jar SamStats.class")

Output is a text file "SamStats_maponly_<sam_file>.stats"

SolidDataExtractor
------------------
Python modules for extracting data about a SOLiD run from the data in
the run directory.

- SolidDataExtractor.py: classes for data extraction, analysis and
  reporting of a SOLiD run.
  Can also be run as a stand-alone program:

  python SolidDataExtractor.py /path/to/solid/run/directory

- analyse_solid_run.py: use the SolidDataExtractor classes to analyse
  and report the layout, samples etc for a SOLiD run:

  python analyse_solid_run.py /path/to/solid/run/directory

- Spreadsheet.py: utility class to generate basic spreadsheet.