#!/usr/bin/env python3
import re
import sys
import time
from datetime import datetime, timedelta
from typing import Dict, List

import requests
from bs4 import BeautifulSoup
from requests import Response

class Config:

    def __init__(self, config_file: str, alternates_file: str, spell_tokens_file: str, skipped_loot_file: str):
        self.guild_name = self.load_guild_name(config_file)
        self.alternates = self.load_list(alternates_file)
        self.spell_tokens = self.load_list(spell_tokens_file)
        self.skipped_loot = self.load_list(skipped_loot_file)

    def load_guild_name(self, config_file: str) -> str:
        try:
            with open(config_file) as f:
                name: str = f.read().strip().split(" ")[0].lower()
                if not name or "http" in name:
                    print(self.config_txt_advice())
                    sys.exit(1)
                return name
        except FileNotFoundError:
            print(self.config_txt_advice())
            sys.exit(1)

    def config_txt_advice(self) -> str:
        return ("Please create a file called config.txt containing your guild's custom hostname on the Guild Launch site\n"
                "without the leading https://\n"
                "e.g. if you normally log in to myguild.guildlaunch.com then you would put myguild in the file.\n")

    def load_list(self, filename: str) -> List[str]:
        try:
            with open(filename, "r") as handle:
                list_ = [line.strip() for line in handle if line.strip()]
            return list_
        except FileNotFoundError:
            print(f"File not found: {filename}")
            sys.exit(1)

class RecentDates:

    def __init__(self):
        self.days_ago_60, self.days_ago_30, self.days_ago_15, self.days_ago_7 = [
            self.format_date(self.days_in_seconds(d)) for d in [60, 30, 15, 7]
        ]

    def format_date(self, seconds_ago: int) -> str:
        past_time = datetime.now() - timedelta(seconds = seconds_ago)
        return past_time.strftime("%Y-%m-%d")

    def days_in_seconds(self, days_ago: int) -> int:
        return days_ago * 24 * 60 * 60


# Calculates DKP stats for an individual Character based on their recent loot.
class DkpStats:

    def __init__(self, config: Config, recent_dates: RecentDates,
                 char_items: Dict[str, str], char_attend_60_day: int, char_dkp: int):
        self.gearcount: int = 0
        self.gearcount_60_day: int = 0
        spellcount: int = 0
        spellcount_60_day: int = 0
        latest_gear_date: str = "1900-01-01"
        for item in char_items:
            item_name: str = item["name"]
            loot_date: str = item["loot_date"]
            if any(re.search(item_name, skippable_item, re.IGNORECASE)
                   for skippable_item in config.skipped_loot):
                continue
            matched_spell: bool = any(re.search(item_name, skippable_spell, re.IGNORECASE)
                                for skippable_spell in config.spell_tokens)
            if matched_spell:  # Check case-insensitive match of item name on known spell tokens
                spellcount += 1
                if loot_date > recent_dates.days_ago_60:
                    spellcount_60_day += 1
            else:
                self.gearcount += 1
                if loot_date > recent_dates.days_ago_60:
                    self.gearcount_60_day += 1

                if loot_date > latest_gear_date:
                    latest_gear_date = loot_date

        self.attend_60_day_bracket: str = self.to_attend_60_day_bracket(char_attend_60_day)
        if self.gearcount == 0:
            latest_gear_date = "N/A"
        self.latest_gear_bracket: str = self.to_latest_gear_bracket(
            self.gearcount, latest_gear_date, recent_dates)
        self.gear_attend_60_day_ratio: float = (self.gearcount_60_day / char_attend_60_day) * 100
        self.gear_dkp_alltime_ratio: float = (self.gearcount / char_dkp) * 100
        self.spells_attend_60_day_ratio: float = (spellcount_60_day / char_attend_60_day) * 100

    # Converts a 60 day attendance percentage into a bracket label.
    def to_attend_60_day_bracket(self, char_attend_60_day: int) -> str:
        if char_attend_60_day >= 75:
            return "1 (Excellent)"
        elif char_attend_60_day >= 50:
            return "2 (Solid)"
        elif char_attend_60_day >= 25:
            return "3 (Patchy)"
        else:
            return "4 (Low)"

    def to_latest_gear_bracket(self, gearcount: int, latest_gear_date: str, recent_dates: RecentDates) -> str:
        if gearcount == 0:
            return "5"
        elif latest_gear_date < recent_dates.days_ago_30:
            return "4"
        elif latest_gear_date < recent_dates.days_ago_15:
            return "3"
        elif latest_gear_date < recent_dates.days_ago_7:
            return "2"
        else:  # Most recent gear within last week
            return "1"

class Character:
    def __init__(self, id, name, dkp_earned, attend_60_day):
        self.id = id
        self.name = name
        self.dkp_earned = dkp_earned
        self.attend_60_day = attend_60_day
        self.dkp_stats = None # initialized later by load_dkp_stats()


class GuildMembersScraper:
    character_dkp_re: re.Pattern[str] = re.compile(r"character_dkp\.php")
    dkp_earned_re:  re.Pattern[str] = re.compile(r"dkp_earned")
    dkp_attend_re:  re.Pattern[str] = re.compile(r"dkp_[a-z]+_attend")
    parens_pct_re:  re.Pattern[str] = re.compile(r"[\(\)%]")

    def __init__(self, html: str, char_limit: int):
        self.soup = BeautifulSoup(html, "lxml")
        self.char_limit = char_limit

    def parse(self) -> Dict[str, Character]:

        def is_td_dkp_span(tag) -> bool:
            return tag.name == "td" and tag.find("span", class_ = self.dkp_attend_re) is not None

        form = self.soup.find("form", attrs = {"action": "", "method": "post"})
        chars: Dict[str, Character] = {}
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
            charname: str = char_anchor.text.strip()
            dkp_earned: float = float(dkp_earned_span.text.strip().replace(",", ""))
            dkp_60_day_attended: int = int(re.sub(self.parens_pct_re, "", dkp_60day_span.text.strip()))
            # Skip characters who are inactive raiders
            if dkp_earned == 0 or dkp_60_day_attended == 0:
                continue
            chars[char_id] = Character(char_id, charname, dkp_earned, dkp_60_day_attended);
            if 0 < self.char_limit <= len(chars):
                break
        return chars

class ItemHistoryScraper:
    item_name_re: re.Pattern[str] = re.compile(r"\[.*\]")
    loot_date_re: re.Pattern[str] = re.compile(r"(\d{4}-\d{2}-\d{2})")

    def __init__(self, html):
        self.soup = BeautifulSoup(html, "lxml")

    def parse(self) -> Dict[str, str]:
        loot: Dict[str, str] = []
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
            item_name: str = item_anchor.text.strip().replace("[", "").replace("]", "")
            if not (loot_date_td := row_tag.find("td", string=re.compile(self.loot_date_re))):
                continue
            loot_date: str = loot_date_td.text.strip()
            loot.append({"name": item_name, "loot_date": loot_date})
        return loot


class Scraper:

    def __init__(self, config: Config):
        self.config = config
        self.base_url = f"https://{config.guild_name}.guildlaunch.com"
        self.session = requests.Session()

    def run(self) -> None:
        self.try_login()
        char_limit: int = self.select_char_limit()
        self.try_retrieve_members()
        chars: Dict[str, Character] = self.build_char_map(char_limit)
        self.load_dkp_stats(chars)
        self.save_summary_report(chars)

    def prompt(self, msg: str) -> str:
        print(msg, end="")
        try:
            f = input()
            return f
        except KeyboardInterrupt:
            sys.exit(0)

    def try_login(self) -> None:
        print(f"The script will log into {self.base_url}")
        print("Enter forum login. Your credentials will not be stored on your device.\n")
        login_email: str = self.prompt("Login (email address): ")
        password: str = self.prompt("Password: ")
        if not login_email or not password:
            raise Exception("Invalid credentials, please try again.")
        login_url: str = f"{self.base_url}/recruiting/login.php"
        login_form: Dict[str, str] = {
            "action": "li2Login",
            "loginEmail": login_email,
            "loginPassword": password,
            "autoLogin": "on",
            "new": "Login",
        }
        login_response: Response = self.session.post(login_url, data = login_form)
        if not login_response.ok:
            raise Exception(f"Error communicating with the server, couldn't log in: {login_response.status_code}")
        if not login_response.cookies.get_dict().get("gl[session_id]", ""):
            raise Exception("Login failed, please try again.")

    def select_char_limit(self) -> int:
        while True:
            print("\nDo you want to do a full scrape of every active member?\n"
                  "If not, the program will run in test mode and scrape 3 characters before stopping.")
            is_full_scrape: str = self.prompt("Full scrape y/n?: ")
            if is_full_scrape.lower() == "n":
                print("Ok, running in test mode.")
                return 3
            elif is_full_scrape.lower() == "y":
                print("Initiating full scrape, please wait.")
                return -1

    def try_retrieve_members(self) -> None:
        print("Retrieving guild member list....")
        members_url: str = f"{self.base_url}/rapid_raid/members.php"
        members_response: Response = self.session.get(members_url)
        if not members_response.ok:
            raise Exception(f"Failed to download members list, error code: {members_response.status_code}")
        with open("members.html", "w", encoding="utf-8") as member_fh:
            member_fh.write(members_response.text)
        if "Members for the" not in members_response.text:
            raise Exception("Didn't find expected content in the members page.")

    def build_char_map(self, char_limit) -> Dict[str, Character]:
        with open("members.html", "r", encoding="utf-8") as file:
            html: str = file.read()
            chars: Dict[str, Character] = GuildMembersScraper(html, char_limit).parse()
            member_count = len(chars)
            print(f"Loaded {member_count} guild members.")
            if member_count == 0:
                raise Exception("At least one guild member should've been found. Something went wrong, try again later.")
            return chars

    def try_retrieve_char_dkp(self, char_id: str) -> str:
        dkp_url: str = f"{self.base_url}/users/characters/character_dkp.php?char={char_id}"
        response: Response = self.session.get(dkp_url)
        if not response.ok:
            raise Exception(f"Failed to download DKP for character {char_id}, error code: {response.status_code}")
        with open("dkp.html", "w") as dkp_file:
            dkp_file.write(response.text)
        with open("dkp.html", "r") as dkp_file:
            return dkp_file.read()

    def load_dkp_stats(self, chars: Dict[str, Character]) -> None:
        recent_dates = RecentDates()
        for char_id in chars.keys():
            time.sleep(1) # wait between downloads so we don"t flood the server
            print("Processing: " + chars[char_id].name)
            dkp_file_content: str = self.try_retrieve_char_dkp(char_id)
            char_items: Dict[str, str] = ItemHistoryScraper(dkp_file_content).parse()
            chars[char_id].dkp_stats = DkpStats(
                config, recent_dates,
                char_items,
                chars[char_id].attend_60_day,
                chars[char_id].dkp_earned
            )

    # Returns a list of Dicts that map character ids to the character's ordinal rank in 3 different categories.
    def calculate_dkp_rankings(self, chars: Dict[str, Character]) -> List[Dict[str, int]]:
        gear_attend_60d_rank: int = sorted(chars.keys(), key = lambda x: chars[x].dkp_stats.gear_attend_60_day_ratio)
        gear_dkp_alltime_rank: int = sorted(chars.keys(), key = lambda x: chars[x].dkp_stats.gear_dkp_alltime_ratio)
        spell_attend_60d_rank: int = sorted(chars.keys(), key = lambda x: chars[x].dkp_stats.spells_attend_60_day_ratio)
        gear_attend_60d_map: Dict[str, int] = {key: rank for rank, key in enumerate(gear_attend_60d_rank)}
        gear_dkp_alltime_map: Dict[str, int] = {key: rank for rank, key in enumerate(gear_dkp_alltime_rank)}
        spell_attend_60d_map: Dict[str, int] = {key: rank for rank, key in enumerate(spell_attend_60d_rank)}
        return gear_attend_60d_map, gear_dkp_alltime_map, spell_attend_60d_map
    
    def save_summary_report(self,  chars: Dict[str, Character]):
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
            for char_id, char in chars.items():
                summary_file.write(
                        "{},{},{},{},{},{},{},{},{}\n".format(
                            char.name,
                            char.dkp_earned,
                            char.dkp_stats.attend_60_day_bracket,
                            gear_attend_60d_map[char_id],
                            gear_dkp_alltime_map[char_id],
                            spell_attend_60d_map[char_id],
                            char.dkp_stats.latest_gear_bracket,
                            char.dkp_stats.gearcount_60_day,
                            char.dkp_stats.gearcount))

if __name__ == "__main__":
    config = Config("config.txt", "alternates.txt",
                    "spell_tokens.txt", "skipped_loot.txt")
    scraper = Scraper(config)
    scraper.run()
