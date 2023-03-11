#!/usr/bin/env python3
# Parses the output of EQ's "/outputfile inventory filename"  command and provides
# a sorted tally of spells in the character inventory & bank.
# Example:
# python countspells.py input.txt output.csv
# In Google Sheets:
#   File > Import > Upload
#   Replace Current Sheet
#   Separator: Detect Automatically
# See the setup steps in the top level README.
import re
import sys
from collections import Counter

def countspells(args):
    if len(args) != 3:
        print('Usage: python {} inputfile.txt outputfile.csv'.format(args[0]))
        sys.exit(1)
    outfile = open(args[2], "w")
    spells = re.findall(r'Spell: ([^\t]+)', open(args[1]).read())
    for k, v in sorted(Counter(spells).items()):
        print("{},{}".format(k, v), file = outfile)

if __name__ == "__main__":
    countspells(sys.argv)
