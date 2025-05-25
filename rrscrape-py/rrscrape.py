#!/usr/bin/env python3
import os
import re
import time
import sys
from datetime import datetime, timedelta
import http.cookies
import http.cookiejar
from urllib import request, parse
import requests
from typing import List, Dict

class Config:
    def __init__(self, config_file, alternates_file, spell_tokens_file, skipped_loot_file):
        self.guild_name = self.load_guild_name(config_file)
        self.load_alternates(alternates_file)
        self.load_spell_tokens(spell_tokens_file)
        self.load_skipped_loot(skipped_loot_file)

    def load_guild_name(self, config_file):
        with open(config_file) as f:
            name = f.read().strip().split(' ')[0].lower()
            if not name or "http" in name:
                print(self.config_txt_advice())
                sys.exit(1)
            return name

    def load_alternates(self, alternates_file):
        self.alternates = self.load_list(alternates_file)

    def load_spell_tokens(self, spell_tokens_file):
        self.spell_tokens = self.load_list(spell_tokens_file)

    def load_skipped_loot(self, skipped_loot_file):
        self.skipped_loot = self.load_list(skipped_loot_file)

    def config_txt_advice(self):
        return ("Could not load a valid config.txt file. Please create a file containing one line.\n"
                "The line must contain your guild's custom hostname on the Guild Launch site\n"
                "without the leading https://\n"
                "e.g. if you normally log in to myguild.guildlaunch.com then you would put myguild in the file.\n")

    def load_list(self, filename):
        try:
            with open(filename, 'r') as handle:
                list_ = [line.strip() for line in handle if line.strip()]
            print(f"Loaded {len(list_)} entries from {filename}.")
            return list_
        except FileNotFoundError:
            print(f"File not found: {filename}")
            sys.exit(1)

class Scraper:
    char_name_line = re.compile(r'^.*character_dkp\.php\?char=(\d+)&amp;gid=\d+\'>([a-zA-Z]+)<')
    dkp_earned_line = re.compile(r'^.*dkp_earned[\"\']>([0-9,\.]+)<')
    dkp_attend_line = re.compile(r'^.*dkp_[a-z]+_attend[\'\"]>\(([0-9]+)\%\)<')
    item_name_line = re.compile(r'^.*\[([\w\s\'\"\-\_\`\,]+)\]<.*$')
    looted_date_line = re.compile(r'^.*(\d{4}-\d{2}-\d{2})<\/td.*$')

    def __init__(self, config: Config):
        self.config = config
        self.base_url = f"https://{config.guild_name}.guildlaunch.com"
        self.char_limit = -1

    def run(self):
        self.try_login()
        self.select_char_limit()
        self.try_retrieve_members()
        self.build_char_map()
        self.load_dkp_stats()
        self.save_summary_report()

    def prompt(self, msg: str):
        print(msg, end='')
        f = input()
        return f

    def try_login(self):
        print(f"The script will log into {self.base_url}")
        print("Enter forum login. Your credentials will not be stored on your device.\n")
        self.login = self.prompt("Login (email address): ")
        self.password = self.prompt("Password: ")
        if not self.login or not self.password:
            raise Exception("Invalid credentials, please try again.")
        login_url = f"{self.base_url}/recruiting/login.php"
        login_form = {
            "action": "li2Login",
            "loginEmail": self.login,
            "loginPassword": self.password,
            "autoLogin": "on",
            "new": "Login",
        }
        self.session = requests.Session()
        login_response = self.session.post(login_url, data=login_form)
        if not login_response.ok:
            raise Exception(f"Error communicating with the server, couldn't log in: {login_response.status_code}")
        cookie_gl_session_id = login_response.cookies.get_dict().get("gl[session_id]", "")
        if not cookie_gl_session_id:
            raise Exception("Login failed, please try again.")

    def select_char_limit(self):
        while True:
            print("\nDo you want to do a full scrape of every active member?\n"
                  "If not, the program will run in test mode and scrape 3 characters before stopping.")
            scrape_mode = self.prompt("Full scrape y/n?: ")
            if scrape_mode.lower() == 'n':
                print("Ok, running in test mode.")
                self.char_limit = 3
                break
            elif scrape_mode.lower() == 'y':
                print("Initiating full scrape, please wait.")
                break
        
    def try_retrieve_members(self):
        print("Retrieving guild member list....")
        members_url = f"{self.base_url}/rapid_raid/members.php"
        members_response = self.session.get(members_url)
        if not members_response.ok:
            raise Exception(f"Failed to download members list, error code: {members_response.status_code}")
        with open("members.html", 'w', encoding='utf-8') as member_fh:
            member_fh.write(members_response.text)
        if "Members for the" not in members_response.text:
            raise Exception("Didn't find expected content in the members page.")

    def build_char_map(self):
        def get_next_line_generator(lines):
            for line in lines:
                yield line
        self.chars = {}
        with open("members.html", 'r', encoding='utf-8') as file:
            lines = list(file)
            line_gen = get_next_line_generator(lines)
            for line in line_gen:
                if not (char_match := self.char_name_line.match(line)):
                    continue
                charid, charname = char_match.groups()
                if any(re.search(charname, alt_char, re.IGNORECASE) for alt_char in self.config.alternates):
                    continue
                dkp = None
                attend_sixty = None
                subline_iter = line_gen
                while dkp is None or attend_sixty is None:
                    next_sub = next(subline_iter)
                    if dkp_earned_match := self.dkp_earned_line.match(next_sub):
                        dkp = float(dkp_earned_match.group(1).replace(',', ''))
                    elif dkp_attend_match := self.dkp_attend_line.match(next_sub):
                        # We expect there to be two dkp attend lines adjacent, the 2nd is the one of interest.
                        next_sub = next(subline_iter)
                        if dkp_attend_match := self.dkp_attend_line.match(next_sub):
                            attend_sixty = int(dkp_attend_match.group(1))
                        else:
                            print(f"Warning: skipping character {charname} because dkp attendance table cell was not found. The format of the page may have changed!")
                            break;
                if dkp is None or attend_sixty is None:
                    print(f"Warning: skipping character {charname} because dkp or attendance table cells could not be found. The format of the page may have changed!")
                    continue
                # Skip characters who are inactive raiders
                if dkp == 0 or attend_sixty == 0:
                    continue
                self.chars[charid] = {
                    'id': charid,
                    'name': charname,
                    'dkp': dkp,
                    'attend_sixty': attend_sixty
                }
                if self.char_limit > 0 and len(self.chars) >= self.char_limit:
                    break

        membercount = len(self.chars)
        print(f"Loaded {membercount} guild members.")
        if membercount == 0:
            raise Exception("At least one guild member should've been found. Something went wrong, try again later.")

    def try_retrieve_char_dkp(self, charid):
        dkp_url = f"{self.base_url}/users/characters/character_dkp.php?char={charid}"
        response = self.session.get(dkp_url)
        if not response.ok:
            raise Exception(f"Failed to download DKP for character {charid}, error code: {response.status_code}")
        # Place every line containing an anchor tag on a new line as the html parser goes line by line.
        split_html = response.text.replace('<a', '\n<a')
        with open("dkp.html", "w") as dkp_file:
            dkp_file.write(split_html)
        with open("dkp.html", "r") as dkp_file:
            return dkp_file.read()

    def format_date(self, seconds_ago: int):
        past_time = datetime.now() - timedelta(seconds=seconds_ago)
        return past_time.strftime('%Y-%m-%d')

    def days_in_seconds(self, days_ago: int):
        return days_ago * 24 * 60 * 60

    def get_recent_dates(self):
        return [self.format_date(self.days_in_seconds(d)) for d in [60, 30, 15, 7]]

    def load_dkp_stats(self):
        days_ago_60, days_ago_30, days_ago_15, days_ago_7 = self.get_recent_dates()
        for charid in self.chars.keys():
            spellcount = 0
            spellcount_sixty = 0
            gearcount = 0
            gearcount_sixty = 0
            total_loot = 0
            latest_gear_date = '1900-01-01'
            latest_gear_bracket = None
    
            time.sleep(1) # wait between downloads so we don't flood the server
            print("Processing: " + self.chars[charid]['name'])
            dkp_file_content = self.try_retrieve_char_dkp(charid)
            lines = dkp_file_content.split('\n')
    
            for line in lines:
                if not (item_match := self.item_name_line.match(line)):
                    continue
                item_name = item_match.group(1).lower();
                if any(re.search(item_name, skippable_item, re.IGNORECASE) for skippable_item in self.config.skipped_loot):
                    continue;
                total_loot += 1
    
                nextline = lines[lines.index(line) + 1]  # The date of looting is on the next line
                if looted_date_match := self.looted_date_line.match(nextline):
                    looted_date = looted_date_match.group(1)
    
                matched_spell = any(re.search(item_name, skippable_spell, re.IGNORECASE) for skippable_spell in self.config.spell_tokens)
                if matched_spell:  # Check case-insensitive match of item name on known spell tokens
                    spellcount += 1
                    if looted_date > days_ago_60:
                        spellcount_sixty += 1
                else:
                    gearcount += 1
                    if looted_date > days_ago_60:
                        gearcount_sixty += 1
    
                    if looted_date > latest_gear_date:
                        latest_gear_date = looted_date
    
            attend_sixty = self.chars[charid]['attend_sixty']
            if attend_sixty >= 75:
                attend_bracket_sixty = '1 (Excellent)'
            elif attend_sixty >= 50:
                attend_bracket_sixty = '2 (Solid)'
            elif attend_sixty >= 25:
                attend_bracket_sixty = '3 (Patchy)'
            else:
                attend_bracket_sixty = '4 (Low)'
    
            if gearcount == 0:
                latest_gear_date = 'N/A'
                latest_gear_bracket = '5'
            elif latest_gear_date < days_ago_30:
                latest_gear_bracket = '4'
            elif latest_gear_date < days_ago_15:
                latest_gear_bracket = '3'
            elif latest_gear_date < days_ago_7:
                latest_gear_bracket = '2'
            else:  # Most recent gear within last week
                latest_gear_bracket = '1'
            gear_attend_sixty_ratio = (gearcount_sixty / attend_sixty) * 100
            gear_dkp_alltime_ratio = (gearcount / self.chars[charid]['dkp']) * 100
            spells_attend_sixty_ratio = (spellcount_sixty / attend_sixty) * 100
            self.chars[charid].update({
                'spellcount': spellcount,
                'spellcount_sixty': spellcount_sixty,
                'gearcount': gearcount,
                'gearcount_sixty': gearcount_sixty,
                'total_loot': total_loot,
                'latest_gear_date': latest_gear_date,
                'attend_bracket_sixty': attend_bracket_sixty,
                'latest_gear_bracket': latest_gear_bracket,
                'gear_attend_sixty_ratio': gear_attend_sixty_ratio,
                'gear_dkp_alltime_ratio': gear_dkp_alltime_ratio,
                'spells_attend_sixty_ratio': spells_attend_sixty_ratio
            })

    def calculate_dkp_rankings(self):
        gear_attend_60d_rank = sorted(self.chars.keys(), key=lambda x: self.chars[x]['gear_attend_sixty_ratio'])
        gear_dkp_alltime_rank = sorted(self.chars.keys(), key=lambda x: self.chars[x]['gear_dkp_alltime_ratio'])
        spell_attend_60d_rank = sorted(self.chars.keys(), key=lambda x: self.chars[x]['spells_attend_sixty_ratio'])
        gear_attend_60d_map = {key: rank for rank, key in enumerate(gear_attend_60d_rank)}
        gear_dkp_alltime_map = {key: rank for rank, key in enumerate(gear_dkp_alltime_rank)}
        spell_attend_60d_map = {key: rank for rank, key in enumerate(spell_attend_60d_rank)}
        return (gear_attend_60d_map, gear_dkp_alltime_map, spell_attend_60d_map)
    
    def save_summary_report(self):
        gear_attend_60d_map, gear_dkp_alltime_map, spell_attend_60d_map = self.calculate_dkp_rankings()
        print("Generating a new summary.csv") 
        with open('summary.csv', 'w') as summary_file:
            summary_file.write(f"Generated at {time.ctime()}.\n[ Gear: Non-spell loot ] [ Rank Columns: Higher = Better Off ] [ Attendance: Excellent = 75%+ | Solid = 50%+ | Patchy = 25%+ | Low = Under 25%. ]\n")
            summary_file.write("Name,DKP,Attend (Last 60),Gear/Attend Rank (Last 60),Gear/DKP Rank (All Time),Spells/Attend Rank (Last 60),Last Gear Looted,Gear Total (Last 60),Gear Total (All Time)\n")
            for charid, char in self.chars.items():
                summary_file.write(
                        "{},{},{},{},{},{},{},{},{}\n".format(
                            char['name'],
                            char['dkp'],
                            char['attend_bracket_sixty'],
                            gear_attend_60d_map[charid],
                            gear_dkp_alltime_map[charid],
                            spell_attend_60d_map[charid],
                            char['latest_gear_bracket'],
                            char['gearcount_sixty'],
                            char['gearcount']))


config = Config('config.txt', 'alternates.txt', 'spell_tokens.txt', 'skipped_loot.txt')
scraper = Scraper(config)
scraper.run()

