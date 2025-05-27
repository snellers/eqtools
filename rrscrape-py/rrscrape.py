#!/usr/bin/env python3
import re
import sys
import time
from datetime import datetime, timedelta
import requests
from bs4 import BeautifulSoup

class Config:

    def __init__(self, config_file, alternates_file, spell_tokens_file, skipped_loot_file):
        self.guild_name = self.load_guild_name(config_file)
        self.alternates = self.load_list(alternates_file)
        self.spell_tokens = self.load_list(spell_tokens_file)
        self.skipped_loot = self.load_list(skipped_loot_file)

    def load_guild_name(self, config_file):
        try:
            with open(config_file) as f:
                name = f.read().strip().split(" ")[0].lower()
                if not name or "http" in name:
                    print(self.config_txt_advice())
                    sys.exit(1)
                return name
        except FileNotFoundError:
            print(self.config_txt_advice())
            sys.exit(1)

    def config_txt_advice(self):
        return ("Please create a file called config.txt containing your guild's custom hostname on the Guild Launch site\n"
                "without the leading https://\n"
                "e.g. if you normally log in to myguild.guildlaunch.com then you would put myguild in the file.\n")

    def load_list(self, filename):
        try:
            with open(filename, "r") as handle:
                list_ = [line.strip() for line in handle if line.strip()]
            return list_
        except FileNotFoundError:
            print(f"File not found: {filename}")
            sys.exit(1)

class GuildMembersScraper:
    character_dkp_re = re.compile(r"character_dkp\.php")
    dkp_earned_re = re.compile(r"dkp_earned")
    dkp_attend_re = re.compile(r"dkp_[a-z]+_attend")
    parens_pct_re = re.compile(r"[\(\)%]")

    def __init__(self, html, char_limit):
        self.soup = BeautifulSoup(html, "lxml")
        self.char_limit = char_limit

    def parse(self):
        def is_td_dkp_span(tag):
            return tag.name == "td" and tag.find("span", class_ = self.dkp_attend_re) is not None
        form = self.soup.find("form", attrs = {"action": "", "method": "post"})
        chars = {}
        if form is None:
            print("A HTML form containing the guild characters could not be found.\n"
                  + "There was either a problem loading the page or the page layout has changed.")
            return chars
        for row_tag in form.find_all("tr"):
            compare_char_input = row_tag.find("input", attrs = {"name": "compare_char_id[]"})
            char_anchor = row_tag.find("a", href = self.character_dkp_re)
            dkp_earned_span = row_tag.find("span", class_ = self.dkp_earned_re)
            if compare_char_input is None or char_anchor is None or dkp_earned_span is None:
                continue
            if not (char_id := compare_char_input["value"]):
                continue
            dkp_span_tds = row_tag.find_all(is_td_dkp_span)
            if dkp_span_tds is None:
                continue
            # There are two DKP attendance ratio columns, the second one tracking 60 day attendance is needed.
            dkp_60day_span = dkp_span_tds[1].find("span", class_ = self.dkp_attend_re)
            charname = char_anchor.text.strip()
            dkp_earned = float(dkp_earned_span.text.strip().replace(",", ""))
            dkp_60_day_attended = int(re.sub(self.parens_pct_re, "", dkp_60day_span.text.strip()))
            # Skip characters who are inactive raiders
            if dkp_earned == 0 or dkp_60_day_attended == 0:
                continue
            chars[char_id] = {
                    "id": char_id,
                    "name": charname,
                    "dkp": dkp_earned,
                    "attend_60_day": dkp_60_day_attended
            }
            if 0 < self.char_limit <= len(chars):
                break
        return chars

class ItemHistoryScraper:
    item_name_re = re.compile(r"\[.*\]")
    loot_date_re = re.compile(r"(\d{4}-\d{2}-\d{2})")

    def __init__(self, html):
        self.soup = BeautifulSoup(html, "lxml")

    def parse(self):
        loot = []
        if not (item_history_header := self.soup.find("h4", string = "Item History")):
            print("Could not locate the Item History table in the Character DKP page.\n"
                  + "There was either a problem loading the page or the page layout has changed.")
            return loot
        if not (loot_table := item_history_header.find_next_sibling("table", class_="forumline")):
            return loot
        for row_tag in loot_table.find_all("tr"):
            # The item names sit within an anchor tag, and are surrounded by square brackets. However, the page is quite
            # complicated, with some items being nested within a span. There are at least three variations. Fortunately
            # extracting the anchor text suffices.
            if not (item_anchor := row_tag.find("a", string=re.compile(self.item_name_re))):
                continue
            item_name = item_anchor.text.strip().replace("[", "").replace("]", "")
            if not (loot_date_td := row_tag.find("td", string=re.compile(self.loot_date_re))):
                continue
            loot_date = loot_date_td.text.strip()
            loot.append({"name": item_name, "loot_date": loot_date})
        return loot


class Scraper:

    def __init__(self, config: Config):
        self.config = config
        self.base_url = f"https://{config.guild_name}.guildlaunch.com"
        self.session = requests.Session()

    def run(self):
        self.try_login()
        char_limit = self.select_char_limit()
        self.try_retrieve_members()
        chars = self.build_char_map(char_limit)
        self.load_dkp_stats(chars)
        self.save_summary_report(chars)

    def prompt(self, msg: str):
        print(msg, end="")
        try:
            f = input()
            return f
        except KeyboardInterrupt:
            sys.exit(0)

    def try_login(self):
        print(f"The script will log into {self.base_url}")
        print("Enter forum login. Your credentials will not be stored on your device.\n")
        login_email = self.prompt("Login (email address): ")
        password = self.prompt("Password: ")
        if not login_email or not password:
            raise Exception("Invalid credentials, please try again.")
        login_url = f"{self.base_url}/recruiting/login.php"
        login_form = {
            "action": "li2Login",
            "loginEmail": login_email,
            "loginPassword": password,
            "autoLogin": "on",
            "new": "Login",
        }
        login_response = self.session.post(login_url, data = login_form)
        if not login_response.ok:
            raise Exception(f"Error communicating with the server, couldn't log in: {login_response.status_code}")
        cookie_gl_session_id = login_response.cookies.get_dict().get("gl[session_id]", "")
        if not cookie_gl_session_id:
            raise Exception("Login failed, please try again.")

    def select_char_limit(self):
        while True:
            print("\nDo you want to do a full scrape of every active member?\n"
                  "If not, the program will run in test mode and scrape 3 characters before stopping.")
            is_full_scrape = self.prompt("Full scrape y/n?: ")
            if is_full_scrape.lower() == "n":
                print("Ok, running in test mode.")
                return 3
            elif is_full_scrape.lower() == "y":
                print("Initiating full scrape, please wait.")
                return -1

    def try_retrieve_members(self):
        print("Retrieving guild member list....")
        members_url = f"{self.base_url}/rapid_raid/members.php"
        members_response = self.session.get(members_url)
        if not members_response.ok:
            raise Exception(f"Failed to download members list, error code: {members_response.status_code}")
        with open("members.html", "w", encoding="utf-8") as member_fh:
            member_fh.write(members_response.text)
        if "Members for the" not in members_response.text:
            raise Exception("Didn't find expected content in the members page.")

    def build_char_map(self, char_limit):
        with open("members.html", "r", encoding="utf-8") as file:
            html = file.read()
            chars = GuildMembersScraper(html, char_limit).parse()
            member_count = len(chars)
            print(f"Loaded {member_count} guild members.")
            if member_count == 0:
                raise Exception("At least one guild member should've been found. Something went wrong, try again later.")
            return chars

    def try_retrieve_char_dkp(self, charid):
        dkp_url = f"{self.base_url}/users/characters/character_dkp.php?char={charid}"
        response = self.session.get(dkp_url)
        if not response.ok:
            raise Exception(f"Failed to download DKP for character {charid}, error code: {response.status_code}")
        with open("dkp.html", "w") as dkp_file:
            dkp_file.write(response.text)
        with open("dkp.html", "r") as dkp_file:
            return dkp_file.read()

    def format_date(self, seconds_ago: int):
        past_time = datetime.now() - timedelta(seconds = seconds_ago)
        return past_time.strftime("%Y-%m-%d")

    def days_in_seconds(self, days_ago: int):
        return days_ago * 24 * 60 * 60

    def get_recent_dates(self):
        return [self.format_date(self.days_in_seconds(d)) for d in [60, 30, 15, 7]]

    def load_dkp_stats(self, chars):
        days_ago_60, days_ago_30, days_ago_15, days_ago_7 = self.get_recent_dates()
        for charid in chars.keys():
            spellcount = 0
            spellcount_60_day = 0
            gearcount = 0
            gearcount_60_day = 0
            total_loot = 0
            latest_gear_date = "1900-01-01"
            time.sleep(1) # wait between downloads so we don"t flood the server
            print("Processing: " + chars[charid]["name"])
            dkp_file_content = self.try_retrieve_char_dkp(charid)
            items = ItemHistoryScraper(dkp_file_content).parse()
            for item in items:
                item_name = item["name"]
                loot_date = item["loot_date"]
                if any(re.search(item_name, skippable_item, re.IGNORECASE)
                       for skippable_item in self.config.skipped_loot):
                    continue
                total_loot += 1
                matched_spell = any(re.search(item_name, skippable_spell, re.IGNORECASE)
                                    for skippable_spell in self.config.spell_tokens)
                if matched_spell:  # Check case-insensitive match of item name on known spell tokens
                    spellcount += 1
                    if loot_date > days_ago_60:
                        spellcount_60_day += 1
                else:
                    gearcount += 1
                    if loot_date > days_ago_60:
                        gearcount_60_day += 1
    
                    if loot_date > latest_gear_date:
                        latest_gear_date = loot_date
    
            attend_60_day = chars[charid]["attend_60_day"]
            if attend_60_day >= 75:
                attend_60_day_bracket = "1 (Excellent)"
            elif attend_60_day >= 50:
                attend_60_day_bracket = "2 (Solid)"
            elif attend_60_day >= 25:
                attend_60_day_bracket = "3 (Patchy)"
            else:
                attend_60_day_bracket = "4 (Low)"
    
            if gearcount == 0:
                latest_gear_date = "N/A"
                latest_gear_bracket = "5"
            elif latest_gear_date < days_ago_30:
                latest_gear_bracket = "4"
            elif latest_gear_date < days_ago_15:
                latest_gear_bracket = "3"
            elif latest_gear_date < days_ago_7:
                latest_gear_bracket = "2"
            else:  # Most recent gear within last week
                latest_gear_bracket = "1"
            gear_attend_60_day_ratio = (gearcount_60_day / attend_60_day) * 100
            gear_dkp_alltime_ratio = (gearcount / chars[charid]["dkp"]) * 100
            spells_attend_60_day_ratio = (spellcount_60_day / attend_60_day) * 100
            chars[charid].update({
                "spellcount": spellcount,
                "spellcount_60_day": spellcount_60_day,
                "gearcount": gearcount,
                "gearcount_60_day": gearcount_60_day,
                "total_loot": total_loot,
                "latest_gear_date": latest_gear_date,
                "attend_60_day_bracket": attend_60_day_bracket,
                "latest_gear_bracket": latest_gear_bracket,
                "gear_attend_60_day_ratio": gear_attend_60_day_ratio,
                "gear_dkp_alltime_ratio": gear_dkp_alltime_ratio,
                "spells_attend_60_day_ratio": spells_attend_60_day_ratio
            })

    def calculate_dkp_rankings(self, chars):
        gear_attend_60d_rank = sorted(chars.keys(), key = lambda x: chars[x]["gear_attend_60_day_ratio"])
        gear_dkp_alltime_rank = sorted(chars.keys(), key = lambda x: chars[x]["gear_dkp_alltime_ratio"])
        spell_attend_60d_rank = sorted(chars.keys(), key = lambda x: chars[x]["spells_attend_60_day_ratio"])
        gear_attend_60d_map = {key: rank for rank, key in enumerate(gear_attend_60d_rank)}
        gear_dkp_alltime_map = {key: rank for rank, key in enumerate(gear_dkp_alltime_rank)}
        spell_attend_60d_map = {key: rank for rank, key in enumerate(spell_attend_60d_rank)}
        return gear_attend_60d_map, gear_dkp_alltime_map, spell_attend_60d_map
    
    def save_summary_report(self, chars):
        gear_attend_60d_map, gear_dkp_alltime_map, spell_attend_60d_map = self.calculate_dkp_rankings(chars)
        print("Generating a new summary.csv") 
        with open("summary.csv", "w") as summary_file:
            summary_file.write(
                f"Generated at {time.ctime()}.\n"
                + "[ Gear: Non-spell loot ] [ Rank Columns: Higher = Better Off ] "
                + "[ Attendance: Excellent = 75%+ | Solid = 50%+ | Patchy = 25%+ | Low = Under 25%. ]\n")
            summary_file.write(
                "Name,DKP,Attend (Last 60),Gear/Attend Rank (Last 60),Gear/DKP Rank (All Time),"
                + "Spells/Attend Rank (Last 60),Last Gear Looted,Gear Total (Last 60),Gear Total (All Time)\n")
            for charid, char in chars.items():
                summary_file.write(
                        "{},{},{},{},{},{},{},{},{}\n".format(
                            char["name"],
                            char["dkp"],
                            char["attend_60_day_bracket"],
                            gear_attend_60d_map[charid],
                            gear_dkp_alltime_map[charid],
                            spell_attend_60d_map[charid],
                            char["latest_gear_bracket"],
                            char["gearcount_60_day"],
                            char["gearcount"]))


config = Config("config.txt", "alternates.txt",
                "spell_tokens.txt", "skipped_loot.txt")
scraper = Scraper(config)
scraper.run()
