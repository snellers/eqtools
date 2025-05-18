#!/usr/bin/env perl
use strict;
use List::MoreUtils qw(any);
use HTTP::Cookies;
use HTTP::Request;
use LWP;
# Uncomment to debug http requests and see the debug_ua() further down.
# use LWP::ConsoleLogger::Easy qw(debug_ua);


sub prompt {
    print shift;
    my $f = <STDIN>;
    chomp($f);
    return $f;
}

my $testing_char_limit = -1; # if you set this positive, program will stop after this many characters

# determine the date string after which we count loot/spells in the "last 60 day" window
my $sixty_days = 60 * 24 * 60 * 60;
my ($old_day, $old_month, $old_year) = (localtime(time - $sixty_days))[3..5];
my $loot_sixty_date = sprintf('%04d-%02d-%02d', $old_year + 1900, $old_month + 1, $old_day);

# and the date string for 30 days ago
my $thirty_days = 30 * 24 * 60 * 60;
my ($old_day, $old_month, $old_year) = (localtime(time - $thirty_days))[3..5];
my $loot_thirty_date = sprintf('%04d-%02d-%02d', $old_year + 1900, $old_month + 1, $old_day);

# and the date string for 15 days ago
my $fifteen_days = 15 * 24 * 60 * 60;
my ($old_day, $old_month, $old_year) = (localtime(time - $fifteen_days))[3..5];
my $loot_fifteen_date = sprintf('%04d-%02d-%02d', $old_year + 1900, $old_month + 1, $old_day);

# and the date string for 7 days ago
my $seven_days = 7 * 24 * 60 * 60;
my ($old_day, $old_month, $old_year) = (localtime(time - $seven_days))[3..5];
my $loot_seven_date = sprintf('%04d-%02d-%02d', $old_year + 1900, $old_month + 1, $old_day);


unlink("members.html", "dkp.html", "summary.csv");

# load alternate characters so they can be skipped
open alternates_file, "alternates.txt" or die("can't open alternates.txt, no alts?");
my @alternates;
while(<alternates_file>) {
    chomp;
    next if /^$/;
    push(@alternates, $_);
}
close(alternates_file);

# load spell token names so we can count spells separately when scraping member loot history
open spell_tokens_file, "spell_tokens.txt" or die("can't open spell_tokens.txt, no spells?");
my @spell_tokens;
while(<spell_tokens_file>) {
    chomp;
    next if /^$/;
    push(@spell_tokens, $_);
}
close(spell_tokens_file);

# load names of low value items we don't want to count when adding up someone's loot
open skipped_loot_file, "skipped_loot.txt" or die("can't open skipped_loot.txt, no skipped loot?");
my @skipped_loot;
while(<skipped_loot_file>) {
    chomp;
    next if /^$/;
    push(@skipped_loot, $_);
}
close(skipped_loot_file);
# load the guild web domain and guild identifier
sub config_txt_advice {
    return "Could not load a valid config.txt file. Please create a file containing one line.\n" .
    "The line must contain your guild's custom hostname on the Guild Launch site.\n" .
    "e.g. if you normally log in to myguild.guildlaunch.com then you would put myguild in the file.\n";
}
open config_file, '<', "config.txt" or die(config_txt_advice());
my $guild_name = <config_file>;
my $guild_id = <config_file>;
close(config_file);
chomp($guild_name);
if ($guild_name eq "") {
    print(config_txt_advice());
    exit;
}
if ($guild_name =~ /http/) {
    print("Edit config.txt and remove the http URL scheme from your guild name.\n");
    exit;
}
my $base_url = "https://$guild_name.guildlaunch.com";
print ("The script will log into $base_url\n");
print "Enter forum login. Your credentials will not be stored on your device.\n";
my $login = prompt("Login (email address): ");
my $pw = prompt("Password: ");
if($login eq "" or $pw eq "") {
    print "Invalid credentials, please try again.\n";
    exit;
}

my $full_scrape_choice;
while(1) { 
    print("\nDo you want to do a full scrape of every active member?\n" .
        "If not, the program will run in test mode and scrape 3 characters before stopping.\n");
    $full_scrape_choice = prompt("Full scrape y/n?: ");
    if($full_scrape_choice =~ /n/i) {
        print("Ok, running in test mode.\n");
        $testing_char_limit = 3;
        last;
    } elsif($full_scrape_choice =~ /y/i) {
        print("Initiating full scrape, please wait.\n");
        $testing_char_limit = -1;
        last;
    }
}

my $browser = LWP::UserAgent->new(
    cookie_jar => {},
    allowed_protocols => ['https'],
    timeout => 10
);
# uncomment this to debug http requests
#debug_ua($browser, 7);
my $login_url = "$base_url/recruiting/login.php";
my %login_form = (
    action => 'li2Login',
    loginEmail => $login,
    loginPassword => $pw,
    autoLogin => 'on',
    'new' => 'Login'
);
my $login_response = $browser->post($login_url, \%login_form);
if ($login_response->is_error) {
    print("Error communicating with the server, couldn't log in.\n");
    exit;
}
# gl[session_id] contains the session cookie.
my $cookie_gl_session_id = $browser->cookie_jar->get_cookies($base_url, "gl[session_id]");
if ($cookie_gl_session_id =~ /^$/) {
    print("Login failed, please try again.\n");
    exit;
}
print("Retrieving guild member list....\n");
my $members_url = "$base_url/rapid_raid/members.php";
my $members_response = $browser->get($members_url);
if ($members_response->is_error) {
    print("Failed to download members list, error code: " . $members_response->code);
    exit;
}
# The members list is written to a temp file and read back in again. Mainly to aid debugging.
open (my $members_file, ">", "members.html") or die("Can't open member list members.html for writing.");
print $members_file $members_response->decoded_content;
close(members_file);
open members_file, "members.html" or die("Can't open member list members.html.");
open(my $summary_file, ">", "summary.csv");

# walk the member list, extract character ids, names, dkp and attendance
my $charmap = {};

while(<members_file>) {
    if (/^.*character_dkp\.php\?char=(\d+)&amp;gid=\d+'>([:a-zA-Z]+)<.*$/) {
        my $charid = $1;
        my $charname = $2;
        my $matched_alt = any {/$charname/i} @alternates;
        if($matched_alt == 1) {
            next;
        }
        my $dkp;
        my $attend_sixty;
        while(<members_file>) {
            if(/^.*dkp_earned'>([0-9\,\.]+)<.*$/) {
                $dkp = $1;
                $dkp =~ s/,//g;
            } elsif(/^.*dkp_[a-z]+_attend'>\(([0-9\,\.\%]+)\)<.*$/) {  # line containing 30 day attendance
                while(<members_file>) {
                    if(/^.*dkp_[a-z]+_attend'>\(([0-9\,\.\%]+)\)<.*$/) {  # TODO change to readline?
                        $attend_sixty = $1;
                        $attend_sixty =~ s/\%//g;
                        last;
                    } 
                }
                last;
            }
        }
        # ignore players with no points or attendance - not added to the hash so later stages don't see them
        next if ($dkp == "0.00" or $attend_sixty == "0");

        $charmap->{$charid} = {
            'id' => $charid,
            'name' => $charname,
            'dkp' => $dkp, 
            'attend_sixty' => $attend_sixty
        };
    }
    # exit early if testing with only a few characters
    last if ($testing_char_limit > 0 and keys %{$charmap} >= $testing_char_limit);

}

close(members_file);

# walk the members, download their item and spell loot
print $summary_file "Generated at " . localtime(time) . ". [ Gear: Non-spell loot ] [ Rank Columns: Higher = Better Off ] [ Attendance: Excellent = 75%+ | Solid = 50%+ | Patchy = 25%+ | Low = Under 25%. ]\n";
print $summary_file "Name,DKP,Attend (Last 60),Gear/Attend Rank (Last 60),Gear/DKP Rank (All Time),Spells/Attend Rank (Last 60),Last Gear Looted,Gear Total (Last 60),Gear Total (All Time)\n";


for my $charid (keys %$charmap) {

    sleep 1; # wait between downloads so we don't flood the server

    my $dkp_url = "$base_url/users/characters/character_dkp.php?char=$charid";
    my $dkp_response = $browser->get($dkp_url);
    if ($dkp_response->is_error) {
        print("Failed to download DKP for character $charid error code: " . $dkp_response->code);
        exit;
    }

    # Place every line containing an anchor tag on a new line as the html parser goes line by line.
    (my $dkp_unsplit = $dkp_response->decoded_content ) =~ s/(<a)/\n$1/g;
    # Print the character's dkp history to a temp file, mainly to aid debugging.
    open (my $dkp_file, ">", "dkp.html") or die("Can't dkp.html for writing.");
    print $dkp_file $dkp_unsplit;
    close(dkp_file);
    open dkp_file, "dkp.html" or die("Can't open dkp.html.");
    my $spellcount = 0;
    my $spellcount_sixty = 0;
    my $gearcount = 0;
    my $gearcount_sixty = 0;
    my $total_loot = 0;
    my $latest_gear_date = '1900-01-01';
    my $latest_gear_bracket;

    print "Processing: " . $charmap->{ $charid }->{ 'name' } . "\n";
    while(<dkp_file>) {
        if(/^.*\[([\w\s\'\"\-\_\`\,]+)\]<.*$/) {  # TODO test negated ] 
            my $item_name = lc($1);
            # skip low value item?
            my $matched_skipped = any {/$item_name/i} @skipped_loot;
            if($matched_skipped == 1) {  
                next;
            }

            my $looted_date;
            $total_loot++;
            my $nextline = readline dkp_file;  # the date of looting is on the next line
            if($nextline =~ /^.*(\d{4}-\d{2}-\d{2})<\/td.*$/) {
                $looted_date = $1;
            }
            my $matched_spell = any {/$item_name/i} @spell_tokens;
            if($matched_spell == 1) {  # case insensitive match of item name on all known spell tokens  TODO TEST
                $spellcount++;
                $spellcount_sixty++ if $looted_date gt $loot_sixty_date;
            } else {
                $gearcount++;
                $gearcount_sixty++ if $looted_date gt $loot_sixty_date;
                if($looted_date gt $latest_gear_date) {
                    $latest_gear_date = $looted_date;
                }

            }
        } 
    }

    close(dkp_file);

    my $attend_bracket_sixty = '4 (Low)';

    if($charmap->{ $charid }->{ 'attend_sixty' } >= 75) {
        $attend_bracket_sixty = '1 (Excellent)';
    } elsif( $charmap->{ $charid }->{ 'attend_sixty' } >= 50) {
        $attend_bracket_sixty = '2 (Solid)';
    } elsif( $charmap->{ $charid }->{ 'attend_sixty' } >= 25) {
        $attend_bracket_sixty = '3 (Patchy)';
    }

    if($gearcount == 0) {
        $latest_gear_date = 'N/A';
        $latest_gear_bracket = '5';
    } else {
        if($latest_gear_date lt $loot_thirty_date) {
            $latest_gear_bracket = '4';
        } elsif($latest_gear_date lt $loot_fifteen_date) {
            $latest_gear_bracket = '3';
        } elsif($latest_gear_date lt $loot_seven_date) {
            $latest_gear_bracket = '2';
        } else {
            $latest_gear_bracket = '1';
        }
    }
    $latest_gear_bracket = $latest_gear_bracket . ' (' . $latest_gear_date . ')';

    # now add computed values to the character map
    # TODO make less verbose? 
    $charmap->{ $charid }->{ 'attend_bracket_sixty'} = $attend_bracket_sixty;
    $charmap->{ $charid }->{ 'latest_gear_date'} = $latest_gear_date;
    $charmap->{ $charid }->{ 'latest_gear_bracket'} = $latest_gear_bracket;

    $charmap->{ $charid }->{ 'gearcount_sixty'} = $gearcount_sixty;
    $charmap->{ $charid }->{ 'gearcount'} = $gearcount;
    $charmap->{ $charid }->{ 'spellcount'} = $spellcount;
    $charmap->{ $charid }->{ 'spellcount_sixty'} = $spellcount_sixty;
    $charmap->{ $charid }->{ 'total_loot'} = $total_loot;

    $charmap->{ $charid }->{ 'gear_attend_sixty_ratio'} = ($gearcount_sixty / $charmap->{ $charid }->{ 'attend_sixty' }) * 100;
    $charmap->{ $charid }->{ 'gear_dkp_alltime_ratio'} = ($gearcount / $charmap->{ $charid }->{ 'dkp' }) * 100;
    $charmap->{ $charid }->{ 'spells_attend_sixty_ratio'} = ($spellcount_sixty / $charmap->{ $charid }->{ 'attend_sixty' }) * 100;

}

# now sort the character id keys by:  gear/attendance60,   gear/dkp,  spells/attendance60
my @sorted_gear_attend_sixty   = sort sort_gear_attend_sixty_ratio (keys(%$charmap));
my @sorted_gear_dkp_alltime    = sort sort_gear_dkp_alltime_ratio (keys(%$charmap));
my @sorted_spells_attend_sixty = sort sort_spells_attend_sixty_ratio (keys(%$charmap));

# create index hashes for the sorted lists so we can efficiently determine each character's ranking within each category
my %index_gear_attend_sixty;
my %index_gear_dkp_alltime;
my %index_spells_attend_sixty;

@index_gear_attend_sixty{@sorted_gear_attend_sixty} = (0..$#sorted_gear_attend_sixty);
@index_gear_dkp_alltime{@sorted_gear_dkp_alltime} = (0..$#sorted_gear_dkp_alltime);
@index_spells_attend_sixty{@sorted_spells_attend_sixty} = (0..$#sorted_spells_attend_sixty);

sub sort_gear_attend_sixty_ratio {
    return $charmap->{$a}->{ 'gear_attend_sixty_ratio' } <=> $charmap->{$b}->{ 'gear_attend_sixty_ratio' };
}

sub sort_gear_dkp_alltime_ratio {
    return $charmap->{$a}->{ 'gear_dkp_alltime_ratio' } <=> $charmap->{$b}->{ 'gear_dkp_alltime_ratio' };
}

sub sort_spells_attend_sixty_ratio {
    return $charmap->{$a}->{ 'spells_attend_sixty_ratio' } <=> $charmap->{$b}->{ 'spells_attend_sixty_ratio' };
}

for my $charid (keys %$charmap) {

    print $summary_file 
    $charmap->{ $charid }->{ 'name' } . "," .
    $charmap->{ $charid }->{ 'dkp' } . "," .
    $charmap->{ $charid }->{ 'attend_bracket_sixty' } . "," .
    $index_gear_attend_sixty{ $charid } . "," .
    $index_gear_dkp_alltime{ $charid } . "," .
    $index_spells_attend_sixty{ $charid } . "," .
    $charmap->{ $charid }->{ 'latest_gear_bracket' } . "," .
    $charmap->{ $charid }->{ 'gearcount_sixty' } . "," .
    $charmap->{ $charid }->{ 'gearcount' } . 
    "\n";
}

close($summary_file);

print("Scrape complete. You can now import summary.csv into a spreadsheet program.\nPlease sanity check that the data looks normal!\n");
if($testing_char_limit != -1) {
    print("As this was just a test scrape, summary.csv will not contain many entries.\n");
}

