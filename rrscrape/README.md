rrscrape
----------------

`rrscrape` is a tool intended for EverQuest guilds that track their raid
attendance using the Guild Launch site, specifically its Rapid Raid feature.

The script retrieves Everquest raid attendance
statistics for your guild from the site.
It will summarize the statistics into a CSV file that can
then be used for deeper analysis. Typically, users will import the CSV file
into a spreadsheet and go from there. 

The script was originally written in 2014 and it depended on the `wget` tool,
but this version doesn't.

## How It Works

- It logs into the site using credentials that you provide. It does 
  not store your credentials.
- It downloads a list of the guild members from the site's member roster page.
- For each character, it checks if their name is found in a local file called
  `alternates.txt`. "Alt" characters are skipped during summary generation.
- Any character that has not attended any raids recently is skipped.
- It downloads the raid and loot statistics for each character.
- It generates a `summary.csv` file containing
  a summary of each character's attendance and loot.
- While generating the summary, it will skip over any loot items that should
  not be considered genuine loot i.e. more common lower value items.
  You can customize these items by adding them (one per line) to `skipped_loot.txt`.
- While generating the summary, it will categorize spells separately to
  normal items. This can be useful when analying the raid data because
  you can use it to determine which characters haven't received their fair
  share of spell upgrades. You can customize which spells the script should
  consider by adding them (one per line) to `spell_tokens.txt`.

The script takes some time to complete because it downloads the data
from the site quite slowly in order to not flood the site with requests.
The script may stop working if the site changes.

## Usage

### Install Required Tools

The script requires `perl`. This is available by default on Linux and MacOS.
On Windows, install Strawberry Perl. 

Install some required perl modules by running this in a terminal (this may
take a few minutes to complete):

```bash
cpan List::MoreUtils HTTP::Cookies HTTP::Request LWP 
```
`cpan` itself is normally included when `perl` is installed.

### Configure Guild Name

Before running the script, you'll need to create a text file in the same folder as the script
called `config.txt`. It must contain a line that specifies your guild's custom hostname
on the Guild Launch site (without the URL scheme) e.g. if you normally log into 
`myguild.guildlaunch.com` put `myguild` in the file.

### Running on Linux/Mac

```bash
rrscrape.sh
```

### Running on Windows

From a terminal window, or via a Windows desktop shortcut, run the script:
```bash
rrscrape.bat
```

### Ongoing Customization

- Edit `alternates.txt` to contain a list of your guild's alternate characters.
- Edit `spell_tokens.txt` to identify any raid items that are spells. These will be 
  categorized separately in the summary report.
- Edit `skipped_loot.txt` to identify any items that have been tracked by your
  raid organizers that you wish to exclude from the summary report.

### Testing

To try the script out on a small number of characters roster, answer 'N' to the question
it asks about performing a full scrape. This will summarize only a few characters.

## Disclaimer

This script is not affiliated with the guildlaunch site or the game Everquest. 
Please use this script responsibly.
Game related materials are copyright of their respective owners.


