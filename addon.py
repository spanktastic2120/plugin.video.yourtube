from datetime import datetime
import string
import sys
import xbmcgui
import xbmcplugin
import xbmcaddon
import xbmc
import urllib
import urlparse
import os
from resources.lib import peewee as pw

__handle__ = int(sys.argv[1])
args = urlparse.parse_qs(sys.argv[2][1:])

xbmcplugin.setContent(__handle__, 'files')

__addon__ = xbmcaddon.Addon('plugin.video.yourtube')
__data__ = xbmc.translatePath(__addon__.getAddonInfo('profile'))
__path__ = xbmc.translatePath(__addon__.getAddonInfo('path'))

db = pw.SqliteDatabase(os.path.join(__data__, 'yourtube.db'))

valid_chars = "-_.() %s%s" % (string.ascii_letters, string.digits)


class Channel(pw.Model):
    id = pw.CharField(primary_key=True)
    title = pw.CharField()
    plot = pw.CharField()
    thumb = pw.CharField()
    premiered = pw.DateField()

    class Meta:
        database = db


class Upload(pw.Model):
    id = pw.CharField(primary_key=True)
    channel = pw.ForeignKeyField(Channel, related_name='uploads')
    title = pw.CharField()
    plot = pw.CharField()
    thumb = pw.CharField()
    aired = pw.DateField()
    runtime = pw.IntegerField()

    class Meta:
        database = db

    @staticmethod
    def last_seen_id(channel):
        try:
            lsid = (Upload
                .select(Upload.id, Upload.aired)
                .where(Upload.channel == channel)
                .order_by(Upload.aired.desc())
                .get()
                .id)
        except Upload.DoesNotExist:
            lsid = None

        return lsid


def db_lookup(table, id):

    row = None
    
    try:
        row = table.select().where(table.id == id).dicts().get()
        
    except table.DoesNotExist:
        return None

    dictionary = {}

    if table.__name__ == 'Channel':
        dictionary = row
        dictionary['channel_id'] = dictionary.pop('id')

    elif table.__name__ == 'Upload':
        dictionary = row
        dictionary['video_id'] = dictionary.pop('id')
        dictionary['channel_id'] = dictionary.pop('channel')

    return dictionary
        

def db_insert(table, data, force=False):
    
    new = []

    for datum in data:
        if table.__name__ == 'Channel':
            try:
                new.append({
                    "id": datum["channel_id"],
                    "title": datum["title"],
                    "plot": datum["plot"],
                    "thumb": datum["thumb"],
                    "premiered": datum["premiered"]
                })
            except KeyError:  # missing necessary info
                raise

        elif table.__name__ == 'Upload':
            try:
                new.append({
                    "id": datum["video_id"],
                    "channel": datum["channel_id"],
                    "title": datum["title"],
                    "plot": datum["plot"],
                    "thumb": datum["thumb"],
                    "aired": datum['aired'],
                    "runtime": datum['runtime']
                })
            except KeyError:  # missing necessary info
                raise

    # Insert rows 100 at a time
    with db.atomic():
        for idx in range(0, len(new), 100):
            
            rows = pw.InsertQuery(table, rows=new[idx:idx+100])
            
            if force:
                rows = rows.on_conflict(action='REPLACE')

            else:
                rows = rows.on_conflict(action='IGNORE')

            rows.execute()
            
    return True


def userpass_from_file(file):
    # retrieve username and password from file
    with open(file, 'r') as f:
        username = f.readline().strip()
        password = f.readline().strip()
    return username, password


def fetch_subscriptions(force=False):
    # fetch all subscriptions from youtube-generated rss file
    # - file is saved as "subscriptions.rss"
    # - function returns the contents of that file
    # - if "force" is specified existing "subscriptions.rss" file is ignored

    fname = os.path.join(__data__, 'subscriptions.rss')
    exists = os.path.isfile(fname)

    if (exists and not force):
        with open(fname, 'r') as f:
            rss = f.read()
    else:
        userpass_file = os.path.join(__data__, 'userpass.txt')
        with open(fname, 'w') as f:
            from resources.lib.SessionGoogle import SessionGoogle
            username, password = userpass_from_file(userpass_file)
            # username = __addon__.getSetting('username')
            # password = __addon__.getSetting('password')
            session = SessionGoogle(username, password)
            rss = session.get("https://www.youtube.com/subscription_manager?action_takeout=1")
            f.write(rss.encode('utf-8'))
    return rss


def fetch_channel_about(title, channel_id, force=False):
    # returns a dictionary of channel information fetched from the channel's "about" page
    from bs4 import BeautifulSoup
    import requests

    exists = db_lookup(Channel, channel_id)

    if exists and not force:
        return exists

    sub = {
        'title': title,
        'showtitle': title,
        'channel_id': channel_id,
        'studio': 'YouTube'
    }
    print("Fetching %s" % sub['title'].encode("utf-8"))  # DEBUG #

    # TODO: make this try harder
    try:
        r = requests.get("https://www.youtube.com/channel/" + channel_id + "/about")
        about = BeautifulSoup(r.text, "html.parser")
        stats = about.find_all("span", class_="about-stat")
        joined = stats[2].text.split(" ", 1)[1]
        sub['premiered'] = datetime.strptime(joined, "%b %d, %Y").strftime("%Y-%m-%d")
        sub['thumb'] = about.find("img", class_="channel-header-profile-image")['src']
        sub['plot'] = about.find("pre").text
        # TODO: img_header = about.find("img", class_="channel-header-profile-image")['src']
        # TODO: image banner somewhere in here: about.find("div", id="gh-banner").style
    except Exception:
        pass
    return sub


def parse_subscriptions():
    # parse subscriptions into dictionary containing 'title' and 'channel_id'
    from bs4 import BeautifulSoup

    rss = fetch_subscriptions()
    outlines = BeautifulSoup(rss, "html.parser")
    subs = outlines.find_all(name="outline", type="rss")
    fetched = []
    for s in subs:
        fetched.append({'title': s['title'], 'channel_id': s['xmlurl'].split('=')[1]})
    return fetched


def make_nfo_tvshow(channel_info, path):
    # take a dictionary of channel_info and turn it into a tvshow.nfo xml for kodi
    import xml.etree.ElementTree as ET

    tvshow = ET.Element('tvshow')
    for tag in channel_info:
        ET.SubElement(tvshow, tag).text = channel_info[tag]
    tree = ET.ElementTree(tvshow)
    tree.write(os.path.join(path, 'tvshow.nfo'), encoding='utf-8', xml_declaration=True)
    return tree


def make_nfo_episode(upload_info, path):
    # take a dictionary of upload_info and turn it into an episode.nfo xml for kodi
    import xml.etree.ElementTree as ET

    episode = ET.Element('episodedetails')
    for tag in upload_info:
        ET.SubElement(episode, tag).text = upload_info[tag]
    tree = ET.ElementTree(episode)
    fname = "s" + upload_info['season'] + "e" + upload_info['episode'] + ".nfo"
    tree.write(os.path.join(path, fname), encoding='utf-8', xml_declaration=True)
    return tree


def make_strm(video_id, fpath):
    with open(fpath, 'w') as f:
        f.write('plugin://plugin.video.youtube/play/?video_id=' + video_id)


def fetch_channel_uploads(channel_id, force=False, last_seen_id=None):
    # fetch a list of all upload URLs from channel
    # - function returns list of dicts containing 'video_id' and 'title'
    #
    # defaults to only getting URLs until a previously known URL is found
    #   - if "force" is specified any known URLs are ignored and the full
    #     list of uploads is retrieved
    #
    # ##### methodology:
    # ##### > go to channel's videos page
    # ##### > go to url of latest video with "&list=UU" appended
    # #####	> parse 79 video urls from playlist  (playlist does not include all items in it)
    # #####	> go to url of last item in the list
    # #####	> repeat
    from bs4 import BeautifulSoup
    import requests

    requests.packages.urllib3.disable_warnings()
    recent_uploads = []
    r = requests.get("https://www.youtube.com/channel/" + channel_id + "/videos?view=0&sort=dd&flow=list")
    page = BeautifulSoup(r.text, "html.parser")
    recent = page.find_all("h3", class_="yt-lockup-title ")
    for upload in recent:
        recent_uploads.append({'title': upload.a['title'], 'video_id': upload.a['href'].split('=')[1]})
        recent_uploads[-1]['thumb'] = "https://i.ytimg.com/vi/" + recent_uploads[-1]['video_id'] + "/hqdefault.jpg"

    seen = False
    uploads = []

    if not last_seen_id and not force:
        last_seen_id = Upload.last_seen_id(channel_id)

    if last_seen_id:
        for upload in recent_uploads:
            if upload['video_id'] == last_seen_id:
                seen = True
                break
            else:
                uploads.append(upload)
    else:
        uploads = recent_uploads

    if force or not seen:
        # fetch more uploads
        index = 0
        length = 1
        while index < length:
            r = requests.get("https://www.youtube.com/watch?v=" + uploads[-1]['video_id'] + "&list=UU" + channel_id[2:])
            page = BeautifulSoup(r.text, "html.parser")
            playlist = page.find_all("li", class_="yt-uix-scroller-scroll-unit")
            length = int(page.find("span", id="playlist-length").text.split(" ")[0].replace(',', ''))

            # remove items before and including currently playing item
            for i in range(len(playlist)):
                if playlist[i].span.text.strip().encode("utf-8") == b'\xe2\x96\xb6':
                    break
            playlist = playlist[i+1:]

            # sometimes playlist contain fewer items than they purport to
            # perhaps deleted videos?
            # this makes sure we dont get stuck in a loop because of it
            if len(playlist) == 0:
                # the current url is playing the last item in the playlist
                index = length
            else:
                index = int(playlist[-1].span.text.strip().replace(',', ''))

            print("finding uploads: index %s of %s total" % (index, length))  # DEBUG #

            if last_seen_id and not force:
                for video in playlist:
                    upload = {
                        'title': video['data-video-title'],
                        'video_id': video['data-video-id'],
                        'thumb': "https://i.ytimg.com/vi/" + video['data-video-id'] + "/hqdefault.jpg"
                    }
                    if upload['video_id'] == last_seen_id:
                        seen = True
                        break
                    else:
                        uploads.append(upload)

            else:
                for video in playlist:
                    uploads.append({
                        'title': video['data-video-title'],
                        'video_id': video['data-video-id'],
                        'thumb': "https://i.ytimg.com/vi/" + video['data-video-id'] + "/hqdefault.jpg"
                    })
            if seen and not force:
                # caught up with last_seen_id
                print("encountered recent video_id: %s" % last_seen_id)  # DEBUG #
                break

    else:
        print("last_seen_id found on first page")  # DEBUG #

    return uploads  # uploads SHOULD be in order and unique


def fetch_upload_about(video_id, force=False):
    # fetch the information about a video_id
    # - returns a dictionary of upload info
    # TODO: defaults to "database" lookup
    #       - if 'force' is specified, existing information is ignored and info is scraped from youtube
    from bs4 import BeautifulSoup
    import requests

    exists = db_lookup(Upload, video_id)
    if exists and not force:
        return exists

    upload = {'video_id': video_id}
    r = requests.get("https://www.youtube.com/watch?v=" + video_id)
    page = BeautifulSoup(r.text, "html.parser")

    upload['thumb'] = "https://i.ytimg.com/vi/" + video_id + "/hqdefault.jpg"
    upload['aired'] = page.find("meta", attrs={"itemprop": "datePublished"})['content']
    upload['title'] = page.find("meta", attrs={"itemprop": "name"})['content']
    upload['channel_id'] = page.find("meta", attrs={"itemprop": "channelId"})['content']

    # extract plot
    description = page.find("p", id="eow-description").strings
    plot = str()
    for line in description:
        plot += line + '\n'
    upload['plot'] = plot

    # get duration in minutes because Kodi's <runtime> is undocumented and minutes works
    from resources.lib.ISO8601 import convert_to_dict as ISO
    duration = ISO(page.find("meta", attrs={"itemprop": "duration"})['content'])
    runtime = \
        int(duration['days'] * 1440) if duration['days'] else 0 +\
        int(duration['hours'] * 60) if duration['hours'] else 0 +\
        int(duration['minutes'] * 1) if duration['minutes'] else 0

    upload['runtime'] = str(runtime)
    return upload


def fetch_upload_about_multithreaded(video_ids, force=False):
    # multithreaded wrapper function for fetch_upload_about() method
    # - takes a list of video_ids and returns a list of upload info

    import concurrent.futures

    thread_count = 10
    upload_count = len(video_ids)

    uploads = [None] * upload_count
    futures = [None] * upload_count

    index = 0
    with concurrent.futures.ThreadPoolExecutor(max_workers=thread_count) as executor:
        while index < upload_count:
            futures[index] = executor.submit(fetch_upload_about,
                                             video_ids[index],
                                             {'force': force})
            index += 1

    for i in range(upload_count):
        uploads[i] = futures[i].result()

    return uploads


def lookup_lastseen(channel_title):
    # check the data folder for the most recent episode of channel_title
    # - returns video_id of latest "cached" episode
    # TODO: make actual cache based on channel_id

    # make the name windows-safe
    channel_title = ''.join(c for c in channel_title if c in valid_chars)

    path = os.path.join(__data__, 'TV', channel_title)
    episodes = [int(f.split('e')[1].split('.')[0]) for f in os.listdir(path) if f.endswith(".strm")]
    if not episodes:
        # no episodes seen
        return None

    latest = str(max(episodes)).zfill(2)
    with open(os.path.join(path, "s01e" + latest + ".strm"), 'r') as f:
        contents = f.read()

    last_seen = contents.split('=')[1]
    print("last seen video of %s is %s with episode %s"
          % (channel_title.encode("utf-8"), last_seen, latest.split('.')[0]))  # DEBUG #
    return last_seen


def lookup_lastepisode(channel_title):
    # find the highest numbered episode for a channel_title
    # - returns an int
    # TODO: in the future this will need to work for series instead of channels

    # make the name windows-safe
    channel_title = ''.join(c for c in channel_title if c in valid_chars)

    path = os.path.join(__data__, 'TV', channel_title)
    episodes = [int(f.split('e')[1].split('.')[0]) for f in os.listdir(path) if f.endswith(".strm")]
    if not episodes:
        # no episodes seen
        return 0

    else:
        return max(episodes)

def db_test():
    start = datetime.now()
    subs = parse_subscriptions()
    total = len(subs)
    current = 1
    
    for sub in subs:

        print("processing sub %s of %s" % (current, total) )
        
        about = fetch_channel_about(sub['title'], sub['channel_id'])
        db_insert(Channel, [about])
        
        uploads = fetch_channel_uploads(sub['channel_id'])
        video_ids = [u['video_id'] for u in uploads]
        upload_abouts = fetch_upload_about_multithreaded(video_ids, force=False)
        db_insert(Upload, upload_abouts)

        current += 1
    end = datetime.now()

    print("Time elapsed: %s" % (end - start))


def sync(force=False):

    subs = parse_subscriptions()
    total_subs = len(subs)
    current_sub = 1
    for sub in subs:
        print("processing sub %s of %s" % (current_sub, total_subs))
        safe_title = ''.join(c for c in sub['title'] if c in valid_chars)
        sub_folder = os.path.join(__data__, 'TV', safe_title)
        if not os.path.exists(sub_folder):
            os.makedirs(sub_folder)
        if not os.path.exists(os.path.join(sub_folder, 'tvshow.nfo')):
            channel_about = fetch_channel_about(sub['title'], sub['channel_id'])
            make_nfo_tvshow(channel_about, sub_folder)

        print("finding uploads for channel %s" % sub['title'].encode("utf-8"))  # DEBUG #

        lastseen = lookup_lastseen(sub['title'])
        uploads = fetch_channel_uploads(sub['channel_id'], force=force, last_seen_id=lastseen)

        print("%s new uploads for channel %s" % (len(uploads), sub['title'].encode("utf-8")))  # DEBUG #

        uploads = fetch_upload_about_multithreaded([u['video_id'] for u in uploads], force=force)

        # reverse the list so they are ordered oldest -> newest
        uploads = uploads[::-1]

        next_ep = lookup_lastepisode(sub['title'])
        for i, upload in enumerate(uploads):
            upload['season'] = '01'  # TODO
            upload['episode'] = str(i + 1 + next_ep).zfill(2)
            name = "s" + upload['season'] + "e" + upload['episode']
            nfoname = name + ".nfo"
            strmname = name + ".strm"
            if not os.path.exists(os.path.join(sub_folder, nfoname)):
                make_nfo_episode(upload, sub_folder)
            if not os.path.exists(os.path.join(sub_folder, strmname)):
                make_strm(upload['video_id'], os.path.join(sub_folder, strmname))

        current_sub += 1
    return True


class ruleTree:
    def __init__(self, cargo, left=None, right=None):
        self.cargo = cargo
        self.left = left
        self.right = right


def rules_from_string(rules_str):
    # builds a ruleTree from a postfix string
    rule_list = rules_str.split(',')
    stack = []
    for rule in rule_list:
        node = ruleTree(rule)
        if node.cargo in ('IS', 'IS NOT', 'CONTAINS', 'DOES NOT CONTAIN', 'OR', 'AND'):
            node.right = stack.pop()
            node.left = stack.pop()
        stack.append(node)
    return stack[0]


def rules_to_string(tree, rules_str=None):
    # returns the postfix string from a ruleTree
    if tree.left:
        rules_str = rules_to_string(tree.left, rules_str)
    if tree.right:
        rules_str = rules_to_string(tree.right, rules_str)
    if rules_str is not None:
        return rules_str + ',' + str(tree.cargo)
    else:
        return str(tree.cargo)


def make_rules_directory(rules):
    url = build_url({'mode': 'rule_builder', 'rule_item': 'chanel_id', 'rules': rules})
    li = xbmcgui.ListItem('Channel', iconImage='DefaultFolder.png')
    xbmcplugin.addDirectoryItem(handle=__handle__, url=url, listitem=li, isFolder=True)

    url = build_url({'mode': 'rule_builder', 'rule_item': 'title', 'rules': rules})
    li = xbmcgui.ListItem('Video Title', iconImage='DefaultFolder.png')
    xbmcplugin.addDirectoryItem(handle=__handle__, url=url, listitem=li, isFolder=True)

    url = build_url({'mode': 'rule_builder', 'rule_item': 'description', 'rules': rules})
    li = xbmcgui.ListItem('Video Description', iconImage='DefaultFolder.png')
    xbmcplugin.addDirectoryItem(handle=__handle__, url=url, listitem=li, isFolder=True)


def build_url(query):
    for key in query.keys():
        query[key] = query[key].encode('utf-8')
    return sys.argv[0] + '?' + urllib.urlencode(query)


mode = args.get('mode', None)

db.connect()
db.create_tables([Channel, Upload], safe=True)

if mode is None:
#    url = build_url({'mode': 'folder', 'foldername': 'Folder One'})
#    li = xbmcgui.ListItem('Folder One', iconImage='DefaultFolder.png')
#    xbmcplugin.addDirectoryItem(handle=__handle__, url=url, listitem=li, isFolder=True)
#
#    url = build_url({'mode': 'folder', 'foldername': 'Folder Two'})
#    li = xbmcgui.ListItem('Folder Two', iconImage='DefaultFolder.png')
#    xbmcplugin.addDirectoryItem(handle=__handle__, url=url, listitem=li, isFolder=True)
#
#    url = build_url({'mode': 'folder', 'foldername': __data__})
#    li = xbmcgui.ListItem(__data__, iconImage='DefaultFolder.png')
#    xbmcplugin.addDirectoryItem(handle=__handle__, url=url, listitem=li, isFolder=True)
#
#    url = build_url({'mode': 'experiment', 'foldername': 'root'})
#    li = xbmcgui.ListItem('Pick me!', iconImage='DefaultFolder.png')
#    xbmcplugin.addDirectoryItem(handle=__handle__, url=url, listitem=li, isFolder=True)

    url = build_url({'mode': 'sync', 'foldername': 'root'})
    li = xbmcgui.ListItem('Add all subscriptions to library', iconImage='DefaultFolder.png')
    xbmcplugin.addDirectoryItem(handle=__handle__, url=url, listitem=li, isFolder=False)

    url = build_url({'mode': 'db_test', 'foldername': 'root'})
    li = xbmcgui.ListItem('db_test', iconImage='DefaultFolder.png')
    xbmcplugin.addDirectoryItem(handle=__handle__, url=url, listitem=li, isFolder=False)

    xbmcplugin.endOfDirectory(__handle__)

elif mode[0] == 'sync':
    foldername = args['foldername'][0]
    if foldername == 'force':
        sync(force=True)
    else:
        sync(force=False)


elif mode[0] == 'db_test':
    db_test()

elif mode[0] == 'folder':
    foldername = args['foldername'][0]
    url = ''
    li = xbmcgui.ListItem(foldername + ' Video', iconImage='DefaultVideo.png')
    xbmcplugin.addDirectoryItem(handle=__handle__, url=url, listitem=li)
    xbmcplugin.endOfDirectory(__handle__)

elif mode[0] == 'experiment':
    foldername = args['foldername'][0]

    if foldername == 'root':
        url = build_url({'mode': 'experiment', 'foldername': 'fetch_subscriptions'})
        li = xbmcgui.ListItem(foldername + '/fetch_subscriptions', iconImage='DefaultVideo.png')
        xbmcplugin.addDirectoryItem(handle=__handle__, url=url, listitem=li, isFolder=True)

        url = build_url({'mode': 'experiment', 'foldername': 'parse_subscriptions'})
        li = xbmcgui.ListItem(foldername + '/parse_subscriptions', iconImage='DefaultVideo.png')
        xbmcplugin.addDirectoryItem(handle=__handle__, url=url, listitem=li, isFolder=True)

    elif foldername == 'fetch_subscriptions':
        truth = bool(fetch_subscriptions())
        li = xbmcgui.ListItem(foldername + str(truth), iconImage='DefaultVideo.png')
        xbmcplugin.addDirectoryItem(handle=__handle__, url=None, listitem=li)

    elif foldername == 'parse_subscriptions':
        subs = parse_subscriptions()
        for sub in subs:
            url = build_url({'mode': 'channel', 'channel_id': sub['channel_id'], 'title': sub['title']})
            li = xbmcgui.ListItem(sub['title'] + ' :: ' + sub['channel_id'], iconImage='DefaultVideo.png')
            xbmcplugin.addDirectoryItem(handle=__handle__, url=url, listitem=li, isFolder=True)

    xbmcplugin.endOfDirectory(__handle__)

elif mode[0] == 'channel':
    channel = fetch_channel_about(args['title'][0], args['channel_id'][0])
    xbmcplugin.setContent(__handle__, 'tvshows')
    for key in channel.keys():
        li = xbmcgui.ListItem(key + ' ' + channel[key], iconImage='DefaultVideo.png')
        xbmcplugin.addDirectoryItem(handle=__handle__, url=None, listitem=li, isFolder=False)

    url = build_url({'mode': 'fetch_uploads', 'channel_id': args['channel_id'][0]})
    li = xbmcgui.ListItem('Fetch Uploads', iconImage=channel['thumb'])
    xbmcplugin.addDirectoryItem(handle=__handle__, url=url, listitem=li, isFolder=True)

    rules = 'channel IS %s' % args['channel_id'][0]
    url = build_url({
        'mode': 'rule_builder', 'channel_id': args['channel_id'][0],
        'title': args['title'][0], 'rules': rules
    })
    li = xbmcgui.ListItem('Create Rule from Channel', iconImage=channel['thumb'])
    xbmcplugin.addDirectoryItem(handle=__handle__, url=url, listitem=li, isFolder=True)
    xbmcplugin.endOfDirectory(__handle__)

elif mode[0] == 'fetch_uploads':
    uploads = fetch_channel_uploads(args['channel_id'][0], force=True)
    for upload in uploads:
        url = build_url({'mode': 'upload_root', 'video_id': upload['video_id'], 'title': upload['title']})
        li = xbmcgui.ListItem(upload['title'] + ' :: ' + upload['video_id'], iconImage='DefaultVideo.png')
        xbmcplugin.addDirectoryItem(handle=__handle__, url=url, listitem=li, isFolder=True)
    xbmcplugin.endOfDirectory(__handle__)

elif mode[0] == 'upload_root':
    upload = fetch_upload_about(args['video_id'][0])
    url = build_url({'mode': 'play', 'video_id': upload['video_id']})
    li = xbmcgui.ListItem('Play: ' + upload['title'], iconImage=upload['thumb'])
    li.setInfo('video', {'plot': upload['plot'], 'title': upload['title'], 'duration': int(upload['runtime']) * 60,
                         'studio': 'YouTube', 'aired': upload['aired']})
    xbmcplugin.addDirectoryItem(handle=__handle__, url=url, listitem=li, isFolder=True)
    xbmcplugin.endOfDirectory(__handle__)

elif mode[0] == 'play':
    xbmc.Player().play('plugin://plugin.video.youtube/play/?video_id=' + args['video_id'][0])

elif mode[0] == 'export_channel':

    safe_title = ''.join(c for c in args['title'][0] if c in valid_chars)
    dest = os.path.join(__data__, 'TV', safe_title)
    if not os.path.exists(dest):
        os.makedirs(dest)

# elif mode[0] == 'rule_builder':
#    rules = args.get('rules', None)
#    rules = rules_from_string(rules)
#    # TODO: add item to fetch results with current rule set
#    for rule in (rules or []):
#        url = build_url({'mode':'rule_builder', 'rules': rules})
#        li = xbmcgui.ListItem('' + rule['title'], iconImage = 'DefaultVideo.png')
#        xbmcplugin.addDirectoryItem(handle = __handle__, url = url, listitem = li, isFolder = False)
#    xbmcplugin.endOfDirectory(__handle__)
