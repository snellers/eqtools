#!/usr/bin/env perl
use strict;
use warnings;
use List::MoreUtils qw(any);
use HTTP::Cookies;
use HTTP::Request;
use LWP;
# Uncomment to debug http requests with debug_ua()
#use LWP::ConsoleLogger::Easy qw(debug_ua);
#use Data::Dumper;

unlink("members.html", "dkp.html", "summary.csv");

# $conf: global hash of config settings loaded from disk.
# $sess: global hash of Session Information.
# These are never passed directly to subroutines.
# All subroutines must only use the
# parameters they're passed, and never variables that
# are visible from their inherited scope.
my $conf = ();
my $sess = ();
$conf->{ guild_name } = load_config("config.txt");
$sess->{ base_url }= "https://$conf->{ guild_name }.guildlaunch.com";

print ("The script will log into $sess->{ base_url }\n");
print "Enter forum login. Your credentials will not be stored on your device.\n";

$sess->{ login }= prompt("Login (email address): ");
$sess->{ password } = prompt("Password: ");

if($sess->{ login } eq "" or $sess->{ password } eq "") {
    die("Invalid credentials, please try again.");
}

$sess->{ char_limit } = get_char_limit();
# load alternate characters so they can be skipped
$conf->{ alternates } = [ load_list("alternates.txt") ];
# load spell token names so we can count spells separately when scraping member loot history
$conf->{ spell_tokens } = [ load_list("spell_tokens.txt") ];
# load names of low value items we don't want to count when adding up someone's loot
$conf->{ skipped_loot } = [ load_list("skipped_loot.txt") ];

$sess->{ browser } = try_login($sess->{ base_url }, $sess->{ login }, $sess->{ password });
$sess->{ members } = try_retrieve_members($sess->{ browser }, $sess->{ base_url }, "members.html");
$sess->{ chars } = build_char_map($sess->{ members }, $sess->{ char_limit }, $conf->{ alternates });

load_dkp_stats($sess->{ browser }, $sess->{ base_url }, $sess->{ chars }, $conf->{ skipped_loot }, $conf->{ spell_tokens });

save_summary_report($sess->{ chars });

print("Scrape complete. You can now import summary.csv into a spreadsheet program.\nPlease sanity check that the data looks normal!\n");

##### Subroutines #####

sub prompt {
    my ($msg) = @_;
    print $msg;
    my $f = <STDIN>;
    die ("EOF") if !defined $f;
    chomp($f);
    return $f;
}

sub config_txt_advice {
    return "Could not load a valid config.txt file. Please create a file containing one line.\n" .
    "The line must contain your guild's custom hostname on the Guild Launch site\n" .
    "without the leading https://\n" .
    "e.g. if you normally log in to myguild.guildlaunch.com then you would put myguild in the file.\n";
}

# load the guild web domain
sub load_config {
    my ($filename) = @_;
    die(config_txt_advice()) unless -f $filename;
    my @list = load_list($filename);
    die(config_txt_advice()) if @list == 0;
    my $guild_name = $list[0];
    if ($guild_name eq "" or $guild_name =~ /http/i) {
        die(config_txt_advice());
    }
    return $guild_name;
}

sub load_list {
    my ($filename) = @_;
    open my $handle, $filename or die("can't open $filename");
    my @list;
    while(<$handle>) {
        chomp;
        next if /^$/;
        push(@list, $_);
    }
    close($handle);
    print("Loaded " . scalar(@list) . " entries from $filename.\n");
    return @list;
}

sub get_char_limit {
    my $char_limit = -1;
    while(1) { 
        print("\nDo you want to do a full scrape of every active member?\n" .
            "If not, the program will run in test mode and scrape 3 characters before stopping.\n");
        my $scrape_mode = prompt("Full scrape y/n?: ");
        if($scrape_mode =~ /n/i) {
            print("Ok, running in test mode.\n");
            $char_limit = 3;
            last;
        } elsif($scrape_mode =~ /y/i) {
            print("Initiating full scrape, please wait.\n");
            last;
        }
    }
    return $char_limit;
}

sub new_browser {
    my $browser = LWP::UserAgent->new(
        cookie_jar => {},
        allowed_protocols => ['https'],
        timeout => 60
    );
    # uncomment this to debug http requests
    #debug_ua($browser, 7);
    return $browser;
}

sub try_login {
    my ($base_url, $login, $password) = @_;
    my $browser= new_browser(); 
    my $login_url = "$base_url/recruiting/login.php";
    my %login_form = (
        action => 'li2Login',
        loginEmail => $login,
        loginPassword => $password,
        autoLogin => 'on',
        new => 'Login'
    );
    my $login_response = $browser->post($login_url, \%login_form);
    if ($login_response->is_error) {
        die("Error communicating with the server, couldn't log in: " . $login_response->code . "\n");
    }
    # gl[session_id] contains the session cookie.
    my $cookie_gl_session_id = $browser->cookie_jar->get_cookies($base_url, "gl[session_id]");
    if ($cookie_gl_session_id =~ /^$/) {
        die("Login failed, please try again.\n");
    }
    return $browser;
}

sub try_retrieve_members {
    my ($browser, $base_url, $filename) = @_;
    print("Retrieving guild member list....\n");
    my $members_url = "$base_url/rapid_raid/members.php";
    my $members_response = $browser->get($members_url);
    if ($members_response->is_error) {
        die("Failed to download members list, error code: " . $members_response->code);
    }
    # The members list is written to a temp file and read back in again. Mainly to aid debugging.
    open my $member_fh, ">", $filename or die("Can't open member list members.html for writing.");
    print $member_fh $members_response->decoded_content;
    close($member_fh);
    if (!$members_response->decoded_content =~ /Members for the/) {
        die("Didn't find expected content in the members page.");
    }
    open $member_fh, "<", $filename or die("Can't open member list members.html.");
    return $member_fh;
}

# walk the member list, extract character ids, names, dkp and attendance
sub build_char_map {
    my ($members_file, $test_char_count, $alt_chars) = @_;
    my $chars = {};
    while(<$members_file>) {
        if (/^.*character_dkp\.php\?char=(\d+)&amp;gid=\d+'>([:a-zA-Z]+)<.*$/) {
            my $charid = $1;
            my $charname = $2;
            my $matched_alt = any {/$charname/i} @$alt_chars;
            if($matched_alt == 1) {
                next;
            }
            my $dkp;
            my $attend_sixty;
            while(<$members_file>) {
                if(/^.*dkp_earned'>([0-9\,\.]+)<.*$/) {
                    $dkp = $1;
                    $dkp =~ s/,//g;
                } elsif(/^.*dkp_[a-z]+_attend'>\(([0-9\,\.\%]+)\)<.*$/) {  # line containing 30 day attendance
                    while(<$members_file>) {
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

            $chars->{$charid} = {
                id => $charid,
                name => $charname,
                dkp => $dkp,
                attend_sixty => $attend_sixty
            };
        }
        # exit early if testing with only a few characters
        last if ($test_char_count > 0 and keys %{$chars} >= $test_char_count);

    }
    close($members_file);
    my $membercount = keys %$chars;
    print("Loaded $membercount guild members.\n");
    if ($membercount == 0) {
        die("At least one guild member should've been found. Something went wrong, try again later.");
    }
    return $chars;
}

# Downloads character DKP stats page, splits the content into new lines
# at each HTML anchor and writes it to a temp file.
sub try_retrieve_char_dkp {
    my ($browser, $base_url, $charid) = @_;
    my $dkp_url = "$base_url/users/characters/character_dkp.php?char=$charid";
    my $dkp_response = $browser->get($dkp_url);
    if ($dkp_response->is_error) {
        die("Failed to download DKP for character $charid error code: " . $dkp_response->code);
    }
    # Place every line containing an anchor tag on a new line as the html parser goes line by line.
    (my $split_html = $dkp_response->decoded_content ) =~ s/(<[aA])/\n$1/g;
    open (my $dkp_file, ">", "dkp.html") or die("Can't dkp.html for writing.");
    print $dkp_file $split_html;
    close($dkp_file);
    open $dkp_file, "dkp.html" or die("Can't open dkp.html.");
    return $dkp_file;
}

# Fetches the DKP stats for every character and transforms it into summary stats in $chars.
sub load_dkp_stats {
    my ($browser, $base_url, $chars, $skipped_loot, $spell_tokens) = @_;
    my ($days_ago_60, $days_ago_30, $days_ago_15, $days_ago_7) = get_recent_dates();
    for my $charid (keys %$chars) {
        sleep 1; # wait between downloads so we don't flood the server
        my $spellcount = 0;
        my $spellcount_sixty = 0;
        my $gearcount = 0;
        my $gearcount_sixty = 0;
        my $total_loot = 0;
        my $latest_gear_date = '1900-01-01';
        my $latest_gear_bracket;

        print "Processing: " . $chars->{ $charid }->{ name } . "\n";
        my $dkp_file = try_retrieve_char_dkp($browser, $base_url, $charid);
        while(<$dkp_file>) {
            if(/^.*\[([\w\s\'\"\-\_\`\,]+)\]<.*$/) {  # TODO test negated ] 
                my $item_name = lc($1);
                # skip low value item?
                my $matched_skipped = any {/$item_name/i} @$skipped_loot;
                if($matched_skipped == 1) {  
                    next;
                }

                my $looted_date;
                $total_loot++;
                my $nextline = readline $dkp_file;  # the date of looting is on the next line
                if($nextline =~ /^.*(\d{4}-\d{2}-\d{2})<\/td.*$/) {
                    $looted_date = $1;
                }
                my $matched_spell = any {/$item_name/i} @$spell_tokens;
                if($matched_spell == 1) {  # case insensitive match of item name on all known spell tokens
                    $spellcount++;
                    $spellcount_sixty++ if $looted_date gt $days_ago_60;
                } else {
                    $gearcount++;
                    $gearcount_sixty++ if $looted_date gt $days_ago_60;
                    if($looted_date gt $latest_gear_date) {
                        $latest_gear_date = $looted_date;
                    }

                }
            } 
        }

        close($dkp_file);

        my $attend_bracket_sixty = '4 (Low)';

        if($chars->{ $charid }->{ attend_sixty } >= 75) {
            $attend_bracket_sixty = '1 (Excellent)';
        } elsif( $chars->{ $charid }->{ attend_sixty } >= 50) {
            $attend_bracket_sixty = '2 (Solid)';
        } elsif( $chars->{ $charid }->{ attend_sixty } >= 25) {
            $attend_bracket_sixty = '3 (Patchy)';
        }

        if($gearcount == 0) {
            $latest_gear_date = 'N/A';
            $latest_gear_bracket = '5';
        } else {
            if($latest_gear_date lt $days_ago_30) {
                $latest_gear_bracket = '4';
            } elsif($latest_gear_date lt $days_ago_15) {
                $latest_gear_bracket = '3';
            } elsif($latest_gear_date lt $days_ago_7) {
                $latest_gear_bracket = '2';
            } else {
                $latest_gear_bracket = '1';
            }
        }
        $latest_gear_bracket = $latest_gear_bracket . ' (' . $latest_gear_date . ')';

        # now add computed values to the character map
        $chars->{ $charid }->{ attend_bracket_sixty} = $attend_bracket_sixty;
        $chars->{ $charid }->{ latest_gear_date} = $latest_gear_date;
        $chars->{ $charid }->{ latest_gear_bracket} = $latest_gear_bracket;
        $chars->{ $charid }->{ gearcount_sixty} = $gearcount_sixty;
        $chars->{ $charid }->{ gearcount} = $gearcount;
        $chars->{ $charid }->{ spellcount} = $spellcount;
        $chars->{ $charid }->{ spellcount_sixty} = $spellcount_sixty;
        $chars->{ $charid }->{ total_loot} = $total_loot;
        $chars->{ $charid }->{ gear_attend_sixty_ratio} = ($gearcount_sixty / $chars->{ $charid }->{ attend_sixty }) * 100;
        $chars->{ $charid }->{ gear_dkp_alltime_ratio} = ($gearcount / $chars->{ $charid }->{ dkp }) * 100;
        $chars->{ $charid }->{ spells_attend_sixty_ratio} = ($spellcount_sixty / $chars->{ $charid }->{ attend_sixty }) * 100;
    }
}

sub save_summary_report {
    my ($chars) = @_;
    my ($gear_attend_60d_map,
        $gear_dkp_alltime_map,
        $spell_attend_60d_map) = calculate_dkp_rankings($chars);

    open(my $summary_file, ">", "summary.csv") or die ("Could not open summary.csv for writing.");
    print $summary_file "Generated at " . localtime(time) . ". [ Gear: Non-spell loot ] [ Rank Columns: Higher = Better Off ] [ Attendance: Excellent = 75%+ | Solid = 50%+ | Patchy = 25%+ | Low = Under 25%. ]\n";
    print $summary_file "Name,DKP,Attend (Last 60),Gear/Attend Rank (Last 60),Gear/DKP Rank (All Time),Spells/Attend Rank (Last 60),Last Gear Looted,Gear Total (Last 60),Gear Total (All Time)\n";
    for my $charid (keys %$chars) {
        print $summary_file 
        $chars->{ $charid }->{ name } . "," .
        $chars->{ $charid }->{ dkp } . "," .
        $chars->{ $charid }->{ attend_bracket_sixty } . "," .
        %$gear_attend_60d_map{ $charid } . "," .
        %$gear_dkp_alltime_map{ $charid } . "," .
        %$spell_attend_60d_map{ $charid } . "," .
        $chars->{ $charid }->{ latest_gear_bracket } . "," .
        $chars->{ $charid }->{ gearcount_sixty } . "," .
        $chars->{ $charid }->{ gearcount } . 
        "\n";
    }
    close($summary_file);
}

# Create hashes of character id to their relative ranking, in three different categories.
# Sort the character id keys by:  gear/attendance60,   gear/all time dkp,  spells/attendance60
sub calculate_dkp_rankings {
    my ($chars) = @_;
    my @gear_attend_60d_rank  = sort { $chars->{$a}->{ gear_attend_sixty_ratio } <=> $chars->{$b}->{ gear_attend_sixty_ratio } } (keys(%$chars));
    my @gear_dkp_alltime_rank = sort { $chars->{$a}->{ gear_dkp_alltime_ratio } <=> $chars->{$b}->{ gear_dkp_alltime_ratio } } (keys(%$chars));
    my @spell_attend_60d_rank = sort { $chars->{$a}->{ spells_attend_sixty_ratio } <=> $chars->{$b}->{ spells_attend_sixty_ratio } } (keys(%$chars));
    my %gear_attend_60d_map;
    my %gear_dkp_alltime_map;
    my %spell_attend_60d_map;
    # Populates the hash using the sorted char ids as the keys and their position in the sorted list as the rank value.
    @gear_attend_60d_map{@gear_attend_60d_rank} = (0..$#gear_attend_60d_rank);
    @gear_dkp_alltime_map{@gear_dkp_alltime_rank} = (0..$#gear_dkp_alltime_rank);
    @spell_attend_60d_map{@spell_attend_60d_rank} = (0..$#spell_attend_60d_rank);
    return (\%gear_attend_60d_map, \%gear_dkp_alltime_map, \%spell_attend_60d_map);
}

sub get_recent_dates {
    my $days_ago_60 = format_date(days_in_seconds(60));
    my $days_ago_30 = format_date(days_in_seconds(30));
    my $days_ago_15 = format_date(days_in_seconds(15));
    my $days_ago_7 = format_date(days_in_seconds(7));
    return ($days_ago_60, $days_ago_30, $days_ago_15, $days_ago_7);
}

# Returns a date string in YYYY-MM-DD format, $seconds_ago before today.
sub format_date {
    my ($seconds_ago) = @_;
    my ($old_day, $old_month, $old_year) = (localtime(time - $seconds_ago))[3..5];
    my $formatted_date = sprintf('%04d-%02d-%02d', $old_year + 1900, $old_month + 1, $old_day);
    return $formatted_date;
}
sub days_in_seconds {
    my ($days_ago) = @_;
    return $days_ago * 24 * 60 * 60;
}

