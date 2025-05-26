countspells
----------------

`countspells` is a tool intended for people who play early releases of EverQuest
such as [Project 1999](https://www.project1999.com).
It's aimed at players who manage a large _guild spell bank_
for their guild, potentially using multiple _spell mules_. 
As early releases of the game had limited inventory management features, 
keeping track of which spells are in the bank can be time consuming.

## Setup

As `countspells` is a `python` script, it requires a version of python to be present on your system.

The script sets that up for you automatically. Behind the scenes, it uses a tool called [uv](https://docs.astral.sh/uv/)
to manage the python environment. If you have any other python based apps on your device, this won't
interfere with those. You are welcome to install alternative distributions of python though, e.g.
miniconda.

## Usage

- In the game run the command `/outputfile inventory filename`
- Copy `filename` from your EverQuest directory into the directory where this script is.
- Run the script
```
./countspells inputfile.txt outputfile.csv
```
- Copy the CSV into your favourite spreadsheet.
- Repeat for additional characters.

## Disclaimer

This script is not affiliated with the game Everquest. 
Game related materials are copyright of their respective owners.
