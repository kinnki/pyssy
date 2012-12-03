# -*- coding: utf-8 -*-

'''
-----
簡介
-----

Pyssy 是一系列用於 `上海交通大學 飲水思源站 <http://bbs.sjtu.edu.cn>`_ 的Python腳本。

Pyssy 既可以寄宿在Sina App Engine上，也可以單獨使用。

----------
依賴項
----------

==========  ======================================================
Flask        Pyssy使用Flask作爲網頁服務框架。
pylibmc      託管在SAE上的Pyssy使用pylibmc訪問SAE的memcached服務。
Redis-py     獨立運行的Pyssy使用Redis作爲memcached服務的替代。
==========  ======================================================

----------
模块
----------
'''

try:
    # try to load sae to test are we on sina app engine
    import sae

    # reload sys to use utf-8 as default encoding
    import sys
    reload(sys)
    
    sys.setdefaultencoding('utf-8')
    import pylibmc
    import sae
    import sae.core
    
    SAE_MC = True
except:
    SAE_MC = False
    try:
        from redis import StrictRedis
        REDIS_MC = True
    except:
        REDIS_MC = False


import json, re
import datetime
import time
from urllib2 import urlopen

from bs4 import BeautifulSoup as BS
import html5lib

from flask import (Flask, g, request, abort, redirect,
                   url_for, render_template, Markup, flash, Response)

from dict2xml import dict2xml
from iso8601 import parse_date

app = Flask(__name__)
app.debug = True

VERSION = 7

app.config[u'VERSION'] = VERSION


URLBASE="http://bbs.sjtu.edu.cn/"
URLTHREAD=URLBASE+"bbstfind0?"
URLARTICLE=URLBASE+"bbscon?"
URLTHREADALL="bbstcon"
URLTHREADFIND="bbstfind"

def str2datetime(st):
    if st == None:
        return None
    return parse_date(st)

def datetime2str(dt):
    if dt==None:
        return None
    return dt.isoformat()

def fetch(url, timeout):
    #Use Memcached in SAE or Redis locally
    #Redis only support String, so convert before/after store
    now = datetime2str(str2datetime(datetime2str(datetime.datetime.now())))
    if timeout > 0 and hasattr(g,'mc'):
        result = g.mc.get(url.encode('ascii'))
        if result:
            result = result.decode("gbk","ignore")
            result_time = str2datetime(g.mc.get('time'+url.encode('ascii')))
            if result_time:
                expired = (str2datetime(now) - result_time) > datetime.timedelta(seconds=timeout)
                if not expired:
                    return (result, datetime2str(result_time))
        html = urlopen(URLBASE + url).read().decode("gbk","ignore")
        if result == html and result_time != None:
            return (result, datetime2str(result_time))
        g.mc.set(url.encode('ascii'), html.encode("gbk","ignore"))
        g.mc.set('time'+url.encode('ascii'), now)
        return (html, now)
    else:
        return (urlopen(URLBASE + url).read().decode("gbk","ignore"), datetime2str(datetime.datetime.now()))

@app.before_request
def before_request():
    if SAE_MC:
        appinfo = sae.core.Application()
        g.mc = pylibmc.Client()
    elif REDIS_MC:
        g.mc = StrictRedis()
    
@app.teardown_request
def teardown_request(exception):
    if hasattr(g, 'db'): g.db.close()

@app.route('/')
def hello():
    html= u"""
        <p>欢迎使用pyssy工具。</p>
        """ 
    return render_template('template.html',body=html)


def soupdump(var):
    if isinstance(var,tuple):
        return [soupdump(x) for x in var]
    if isinstance(var,list):
        return [soupdump(x) for x in var]
    if isinstance(var,dict):
        return dict((x,soupdump(var[x])) for x in var)
    if isinstance(var, int):
        return var
    if isinstance(var, float):
        return var
    if hasattr(var,'stripped_strings'):
        return u''.join(var.stripped_strings)
    if hasattr(var,'string'):
        return unicode(var.string)
    else:
        return unicode(var)

class api(object):
    def __init__(self, timeout):
        self.timeout = timeout
        
    def __call__(self, func):
        def wrap(*args, **kwargs):
            if 'format' in request.values:
                format = request.values['format']
            else:
                format = 'json'
            if 'pretty' in request.values:
                pretty = int(request.values['pretty']) == 1
            else:
                #pretty = False
                pretty = True
            if 'callback' in request.values:
                callback = request.values['callback']
            else:
                callback = '' 
            if 'include' in request.values:
                include = int(request.values['include']) == 1
            else:
                include = False
            
            if 'url'      in kwargs: url         = kwargs['url']
            if 'format'   in kwargs: format      = kwargs['format']
            if 'pretty'   in kwargs: pretty      = kwargs['pretty']
            if 'callback' in kwargs: callback    = kwargs['callback']
            if 'include'  in kwargs: include     = kwargs['include']
            
            if not format in [u'json', u'xml', u'jsonp', u'raw']:
                return u'Format "%s" not supported! Use "json" or "xml".'%format
            if format == u'json' and callback != u'':
                format = u'jsonp'
            
            if u'If-Modified-Since' in request.headers:
                modified_since = request.headers[u'If-Modified-Since']
            else:
                modified_since = u''
            
            start = time.clock()
            html,fetch_time = fetch(url, self.timeout)
            end_fetch = time.clock()
            
            if modified_since == fetch_time:
                return Response(status=304)
            
            result, xml_list_names = func(BS(html,'html5lib'))
            
            roottag = func.__name__
            
            if include and u'articles' in result:
                for artlink in result[u'articles']:
                    art,xl = article(url=artlink[u'link'], format=u'raw')
                    artlink[u'include'] = art
                    xml_list_names.update(xl)
            
            end_parse = time.clock()
            
            if format != u'raw':
                result[u'api'] = {
                    u'args'             : args,
                    u'kargs'            : kwargs, 
                    u'request_url'      : request.url,
                    u'format'           : format,
                    u'pretty'           : pretty,
                    u'callback'         : callback,
                    u'version'          : app.config[u'VERSION'],
                    u'values'           : request.values,
                    u'name'             : roottag,
                    u'fetch_time'       : fetch_time,
                    u'fetch_hash'       : hash(html),
                    u'fetch_elapse'     : end_fetch - start,
                    u'elapse'           : end_parse - start,
                }
            
            headers = {'Last-Modified': fetch_time}
            
            result = soupdump(result)
            xml_list_names['args'] = u'arg'
            
            if format == u'raw':
                return result, xml_list_names
            elif format == u'xml':
                return Response(dict2xml(result, roottag=roottag,
                    listnames=xml_list_names, pretty=pretty),
                    headers=headers,
                    content_type='text/xml; charset=utf-8')
            else:
                if pretty:
                    json_result = json.dumps(result,
                        ensure_ascii = False, sort_keys=True, indent=4)
                else:
                    json_result = json.dumps(result, ensure_ascii = False)
                if callback != '':
                    return Response('%s([%s]);'%(callback, json_result), 
                        headers=headers,
                        content_type='text/javascript; charset=utf-8')
                else:
                    return Response(json_result, 
                        headers=headers,
                        content_type='application/json; charset=utf-8')
        return wrap

# -----Article------        
@app.route(u'/api/article/<board>/<file_>', methods=[u'GET', u'POST'])
def rest_article(board, file_):
    '''
    @/api/article/<boardName>/<fileName>
    
    读取单篇文章,返回以下对象::
    
        results = {	
                    board: "ACMICPC", 
                    body_title: "饮水思源 - 文章阅读", 
                    content: {...}, 
                    content_lines: [...],
                    file: "M.1353674155.A",
                    file_id: 1353674155,
                    links: [],
                    page_title: "",
                    reid: 1353601828,
                    url: "bbscon?board=ACMICPC&file=M.1353674155.A"
                    }
    '''
    ext = file_[file_.rindex(u'.')+1:]
    if ext in [u'json', u'xml', u'jsonp']:
        format = ext
        file_ = file_[:file_.rindex(u'.')]
    else:
        format = 'json'
    
    url = u'bbscon?board=%s&file=%s'%(board, file_)
    return article(url=url, format=format)
@api(16)
def article(soup):
    result = {}
    
    result[u'page_title'] = soup.title
    body = soup.body.center
    result[u'body_title'] = body.contents[1]
    board_str = body.contents[2] # "[讨论区: BOARD]"
    result[u'board'] = board_str[board_str.rfind(':') + 2 : -1 ]
    
    link_index = [5, 7, 9, 11, 13, 15, 17, 19, 21, 23, 25]
    links = [body.contents[x] for x in link_index]
    result[u'links'] = []
    for link in links:
        result[u'links'].append({
            u'url' : link[u'href'],
            u'string' : link.string,
            u'action' : re.findall(u'^(\w*)',link[u'href'])[0],
            })
            
    re_link = unicode(filter(lambda x: x[u'action']==u'bbspst', result[u'links'])[0]['url'])
    result[u'reid'] = int(re.findall(u'(\w*)$',re_link)[0])
    result[u'file_id'] = int(re.findall(u'M\\.(\w*)\\.A',re_link)[0])
    result[u'file'] = 'M.%d.A'%result[u'file_id']
    result[u'url'] = u'bbscon?board=%s&file=%s'%(result[u'board'], result[u'file'])
    
    content = body.table.tr.pre #<pre>content</pre>
    content_raw = unicode(content)[5:-6]
    content_lines = content_raw.split(u'\n')
    result[u'content_lines'] = content_lines
    datetime_str = unicode(content_lines[2])[11:30]
    
    datetime_tuple = [ int(datetime_str[0:4]),
                        int(datetime_str[5:7]),
                        int(datetime_str[8:10]),
                        int(datetime_str[11:13]),
                        int(datetime_str[14:16]),
                        int(datetime_str[17:19]),]
    datetime_ = datetime.datetime(*datetime_tuple)
    
    from_index = -1
    for i in range(len(content_lines)-1, -1, -1):
        if len(re.findall(u'\[FROM: ([\w\.:]*)\]',content_lines[i])) > 0:
            from_index = i
        
    from_lines = filter(lambda x:x != '',content_lines[from_index:])
    if len(from_lines)>0:
        from_ip = re.findall(u'\[FROM: ([\w\.:]*)\]',from_lines[0])[0]
    else:
        from_ip = ''
    edit_times = len(from_lines) - 1 # 来自那行,和最后</font>的一行
    
    qmd_index = -1
    for i in range(len(content_lines)-1,-1,-1):
        if content_lines[i] == u'--':
            qmd_index = i
            break
    if qmd_index != -1:
        qmd_lines = content_lines[qmd_index + 1 : from_index]        
    else:
        qmd_lines = []
    
    reply_index = -1
    for i in range(qmd_index, -1, -1):
        if len(re.findall(u'^【 在.*的大作中提到: 】$',content_lines[i])) > 0:
            reply_index = i
            break
    if reply_index == -1:
        reply_index = qmd_index
    if reply_index != -1:
        reply_lines = content_lines[reply_index : qmd_index - 1] 
        for i in range(1,len(reply_lines)):
            if len(re.findall(u'<font color="808080">: (.*)$',reply_lines[i])) > 0:
                reply_lines[i] = re.findall(
                    u'<font color="808080">: (.*)$',reply_lines[i])[0]
    else:
        reply_lines = []
        
    text_lines = content_lines[4:reply_index]
    
    result[u'content'] = {
        u'author': content.a ,
        u'author_link': content.a[u'href'] ,
        u'nick'  : content_lines[0][content_lines[0].find('(')+1:content_lines[0].rfind(')')],
        u'board' : content_lines[0][content_lines[0].rfind(' ') + 1:] ,
        u'title' : content_lines[1][6:] ,
        u'datetime_str' : datetime_str ,
        u'datetime_tuple' : datetime_tuple ,
        u'datetime_epoch' : repr(time.mktime(datetime_.timetuple())),
        u'datetime_ctime' : datetime_.ctime() ,
        u'qmd_lines' : qmd_lines ,
        u'from_lines' : from_lines ,
        u'from_ip' : from_ip ,
        u'reply_lines' : reply_lines,
        u'text_lines' : text_lines,
        u'edit_times' : edit_times, 
    }
    
    xml_list_names= {
        u'qmd_lines':       u'line', 
        u'content_lines':   u'line',
        u'text_lines':      u'line',
        u'reply_lines':     u'line', 
        u'from_lines':      u'line',
        u'datetime_tuple':   u'int',
        u'links':           u'link',
        u'args':            u'arg',
    }

    return (result, xml_list_names)

# ------Articles----
@app.route('/api/articles', methods=['GET', 'POST'])
@app.route('/api/articles/<b>', methods=['GET', 'POST'])
def rest_board(b='Script'):
    '''
    @/api/articles/<boardName>[?page=int]
    
    读取board里的帖子,返回以下对象：::
    
        results = { 
                    board: "boardName",
                    title: "Script(脚本语言)", 
                    chinese_title: "脚本语言",
                    district: {char: 3, name: "3区"},
                    has_next_page: false || true, 
                    has_prev_page: true || true, 
                    other_tables: [], 
                    page: 397, 
                    up_links: [],
                    down_links: [],
                    wiki: "wiki",
                    friend_links: [...],
                    fixed_articles: [{...}],
                    articles: [{...}]
        }
    '''
    if u'.' in b:
        ext = b[b.rindex(u'.')+1:]
        if ext in [u'json', u'xml', u'jsonp']:
            format = ext
            b = b[:b.rindex(u'.')]
        else:
            format = 'json'
    else:
        format = 'json'

    board_ = b
    if 'page' in request.values:
        page_str = request.values[u'page']
        page_re = re.findall('[0-9]+',page_str)
        if len(page_re) > 0:
            page = int(page_re[0])
            url = u'bbsdoc?board=%s&page=%d'%(board_, page)
        else:
            page = 'latest'
            url = u'bbsdoc?board=%s'%(board_)
    else:
        page = 'latest'
        url = u'bbsdoc?board=%s'%(board_)
    return board(url=url)
@api(200)
def board(soup):
    result = {}
    
    result[u'board'] = soup.body(u'input', type=u'hidden')[0][u'value']
    title = soup.body.table.tr.font.b.string
    result[u'title'] = title
    result[u'chinese_title'] = re.findall('\(.*\)$', title)[0][1:-1]
    
    result[u'wiki'] = soup.body.table.tr.a[u'href']
    
    nobr = soup.nobr
    
    
    links_bms_line = [{
        u'text':unicode(a.string), 
        u'href':a[u'href'], 
        u'action':re.findall(u'^(\w*)',a[u'href'])[0]} 
            for a in nobr.table(u'a')]
    
    result[u'bms'] = [bm[u'text'] for bm in 
        filter( lambda x:x[u'href'].startswith(u'bbsqry?userid='), 
            links_bms_line)]
    
    result[u'up_links'] = filter( 
        lambda x: not x[u'href'].startswith(u'bbsqry?userid='),
        links_bms_line)
        
    result[u'has_next_page'] = len(
        filter(lambda x: x[u'text']== u'下一页', result[u'up_links'])
        ) > 0
    
    result[u'has_prev_page'] = len(
        filter(lambda x: x[u'text']== u'上一页', result[u'up_links'])
        ) > 0
    
    if result[u'has_prev_page']:
        prev_page = unicode(filter(lambda x: x[u'text']== u'上一页', result[u'up_links'])[0]['href'])
        result[u'page'] = int(re.findall(u'[0-9]+',prev_page)[0]) + 1
    else:
        result[u'page'] = 0
    
    table2 = nobr.contents[3].tr.contents

    if table2[0].string == None:
        bm_words = [child for child in table2[0].table.tr.td][2:]
        result[u'bm_words'] ={ 
            u'plain': u''.join(
                filter(lambda x:x != None,(x.string for x in bm_words))),
            u'color': u''.join(unicode(x) for x in bm_words)}
    else:
        result[u'bm_words'] ={u'plain': u'',u'color': u''}

    district = table2[1].string
    result[u'district'] = {u'name':district, u'char':district[0]}
    #return ({u'r':[unicode(tr) for tr in nobr.contents[6].table('tr')]},{})
    
    articles = [tr for tr in nobr.contents[6].table('tr')][3:] # 前面三项是\n, 标题, \n
    result[u'articles'] = []
    result[u'fixed_articles'] = []
    for art in articles:
        art_list = [item for item in art]
        words_str = [string for string in art_list[4].contents][2].string
        if words_str[-1] == 'K':
            words = int(float(words_str[:-1])*1000)
        else:
            words = int(words_str[:-1])
        mark = art_list[1].string
        mark = mark if mark != None else u''
        link = unicode(art_list[4].a[u'href'])
        file_ = re.findall(u'file.(.+?)(\.html){0,1}$', link)[0][0]
        file_id = int(file_[2:-2])
        datetime_str = art_list[3].string
        current_year = str(datetime.datetime.now().year)+datetime_str
        datetime_ = datetime.datetime.strptime(current_year,'%Y%b %d %H:%M')
        
        tit = art_list[4].a
        if tit.font != None:
            cannot_re = tit.font['color']
            tit = list(tit.strings)[1]
        else:
            cannot_re = ''

        article = {
            #u'list': [unicode(x) for x in art_list],
            u'id': art_list[0],
            u'mark': mark,
            u'author': art_list[2].a,
            u'datetime_str': datetime_str,
            u'datetime_ctime': datetime_.ctime(),
            u'datetime_tuple': tuple(datetime_.timetuple()[:6]),
            u'datetime_epoch': repr(time.mktime(datetime_.timetuple())),
            u'title': tit,
            u'link': link,
            u'file': file_,
            u'file_id': file_id,
            u'words_str': words_str,
            u'words' : words,
            u'cannot_re': cannot_re,
            u'api_link': "/api/article/"+result[u'board']+"/"+file_,
        }
        
        font = article[u'id'](u'font') 
        if len(font) == 0:
            article[u'id'] = int(article[u'id'].string)
            result[u'articles'].append(article)
        else:
            article[u'type'] = font[0]
            del article[u'id']
            result[u'fixed_articles'].append(article)
    
    tables = [tab for tab in nobr.contents[6]('table')[1:]]
    result[u'other_tables'] = []

    for tab in tables:
        name = unicode(tab.contents[1].td.string)
        tds = filter(lambda td: td.find('a')!= None, tab(u'td'))
        if name == u'板主推荐':
            links = [{u'href': td.a[u'href'],
                      u'text': td.a.string} for td in tds]
            result[u'bm_recommends'] = links
        elif name == u'友情链接':
            links = [{u'href':    td.a[u'href'],
                      u'board':   td.a.contents[0], 
                      u'chinese': td.contents[1]} for td in tds]
            result[u'friend_links'] = links
        else:
            result[u'other_tables'].append({u'name':name,u'links':links})
    
    down_links = [ ]
    after_hr = False
    for tag in nobr.contents:
        if not hasattr(tag, u'name'): continue
        if tag.name == u'hr':
            after_hr = True 
        if after_hr and tag.name == u'a':
            down_links.append(tag)
        
    result['down_links'] = [{u'href': tag[u'href'],
                             u'action': re.findall(u'^(\w*)', tag[u'href'])[0],
                             u'text': u''.join(unicode(child) for child in tag.contents),
                            } for tag in down_links]
    
    xml_map = { u'bms':             u'bm',
                u'up_links':        u'link',
                u'args':            u'arg',
                u'articles':        u'article',
                u'fixed_articles':  u'article',
                u'down_links':      u'link',
                u'friend_links':    u'link',
                u'datetime_tuple':  u'int',
              }
    return (result, xml_map)

# -----Topic--------
@app.route(u'/api/topic/<board>/<reid>', methods=[u'GET', u'POST'])
def rest_thread(board, reid):
    '''
    @//api/topic/<board>/<reid> ##目前只返回json对象
    
	读取主题的所有讨论，返回以下对象：::
	
		results = {
                    articles: [{}],
                    bbstcon_link: "",
                    board: "boardName",
                    board_link: "bbsdoc?board=PPPerson", 
                    count: 3, 
                    page_title: "饮水思源 - 同主题查找", 
                    topic: "yamamoto itsuka"
		}
	'''
    if reid.rfind(u'.'):
        ext = reid[reid.rfind(u'.')+1:]
        if ext in [u'json', u'xml', u'jsonp']:
            format = ext
            reid = reid[:reid.rindex(u'.')]
    else:
        format = 'json'
    
    url = u'bbstfind0?board=%s&reid=%s'%(board, reid)
    return thread(url=url)
@api(2)
def thread(soup):
    result = {}
    center = soup.center.contents
    
    result[u'page_title'] = center[0]
    headline = center[1]
    result[u'board'] = re.findall(u'\[讨论区: (.+?)\]', headline)[0]
    result[u'topic'] = re.findall(u" \[主题 '(.+?)'\]", headline)[0]
    
    trs = soup.table(u'tr')[1:]
    result['articles'] = []
    for tr in trs:
        cont = tr.contents
        datetime_str = cont[2].string
        current_year = unicode(datetime.datetime.now().year)+datetime_str
        datetime_ = datetime.datetime.strptime(current_year, u'%Y%b %d')
        link = cont[3].a[u'href']
        board = re.findall(u'board=(.+?)&', link)[0]
        file_ = re.findall(u'file=(.+)$', link)[0]
        art = {
            u'id': int(cont[0].string),
            u'user': cont[1].a ,
            u'user_link': cont[1].a[u'href'], 
            u'datetime_str': datetime_str,
            u'datetime_ctime': datetime_.ctime(),
            u'datetime_tuple': tuple(datetime_.timetuple()[:6]),
            u'datetime_epoch': repr(time.mktime(datetime_.timetuple())),
            u'title': cont[3].a,
            u'link': link,
            u'board': board,
            u'file': file_,
            u'api_link': "/api/article/"+board+"/"+file_,
        }
        result['articles'].append(art)
    result[u'count'] = int(re.findall(u'共找到 ([0-9]+) 篇',center[6])[0])
    result[u'board_link'] = center[7][u'href']
    result[u'bbstcon_link'] = center[9][u'href']
    return (result,{'datetime_tuple':'int','articles':'article'})

# -----Topics--------
@app.route(u'/api/topics', methods=[u'GET', u'POST'])
@app.route(u'/api/topics/<board>', methods=[u'GET', u'POST'])
def rest_topics(board=''):
    '''
    @/api/topics
    
    读取bbs首页十大主题列表
    
    @/api/topics/<board>
    
    读取版块最新主题列表
    '''
    if board:
        url = u'bbstdoc,board,%s.html'%(board)
        return topics(url = url)
    else:
        url = u'php/bbsindex.html'
        return topics(url = url)
@api(60)
def topics(soup):
    tables = soup.findAll('table')
    results = {}
    if soup.center:
        #bbstdoc页面
        trs = tables[0].findAll('tr')[1:]
        pageLink = tables[0].nextSibling.nextSibling.nextSibling #第一个翻页链接，除非位于第一页时，链接为下一页，其余情况均为上一页
        boardInfo = tables[0].previousSibling.previousSibling.previousSibling #'] 文章4365, 主题2467个'
        
        results[u'TotalTopics'] = re.findall('\d+',unicode(boardInfo))[1]
        results[u'topics'] = []        
        for i in range(len(trs)):
            anchors = trs[i].findAll('a')
            tds = trs[i].findAll('td')
            if not anchors[1].string:
                title = re.sub('<.*?>', '', str(tds[4].contents[0])).decode('utf-8')
                #print type(t.decode('utf-8'))
                #title = 'None'
            else:
                title = anchors[1].string
                
            if re.match('\d+', str(tds[0].contents[0])):
                id = tds[0].contents[0]
            else:
                id = 0
            
            if re.match('bbstcon',str(anchors[1]['href'])):
                board = re.findall('bbstcon,board,(.*?),reid,(\d+)\.html',str(anchors[1]['href']))[0][0]           
                reid = re.findall('bbstcon,board,(.*?),reid,(\d+)\.html',str(anchors[1]['href']))[0][1]
            elif re.match('bbstopcon',str(anchors[1]['href'])):
                print re.findall('board=(.*)&file=.*?(\d+)',str(anchors[1]['href']))
                board = re.findall('board=(.*)&file=.*?(\d+)',str(anchors[1]['href']))[0][0]
                reid = re.findall('board=(.*)&file=.*?(\d+)',str(anchors[1]['href']))[0][1]
            
            status = tds[1].string
            author = tds[2].contents[0].string
            date = tds[3].string

            reply = re.findall('\((\d+)', unicode(tds[4].contents[1]))

            if len(reply):
                reply = reply[0]
            else:
                reply = None
            results['topics'].append({  'title':    title.strip(),
                                        'href':     anchors[1]['href'],
                                        'id':       id,
                                        'status':   status,
                                        'author':   author,
                                        'date':     date,
                                        'reply':    reply,
                                        'api_link': '/api/topic/'+board+'/'+reid
                                        })
    else:
        #bbsindex
        results[u'recommendation'] = []
        recommendations = tables[10].findAll('tr');
        for recom in recommendations:
            results[u'recommendation'].append({ 'title':    recom.findAll('a')[1].string,
                                                'href':     recom.findAll('a')[1]['href'],
                                                'author':   recom.findAll('td')[3].string.strip(),
                                                'board':    recom.findAll('a')[0].string,
                                                'date':     recom.findAll('td')[2].string.strip()
                                                })
    
        #get districts top10
        tableIndex = [15,23,26,29,32,35,38,41,44,47,50,53] #normal index, 如果某个区没有十大，需要另外计算index
        for i in range(len(tableIndex)):
            #取index,然后循环抽取tr里的条目
            if i == 0:
                results['top10'] = []
            else:
                results['top10_dis'+str(i)] = []
                
            index = tableIndex[i]
            trs = tables[index].findAll('tr')
            for tr in trs:
                anchors = tr.findAll('a')
                if i == 0:  # i==0时，为十大热门话题，单独处理
                    results['top10'].append({   'title':    anchors[1].string.strip(),
                                                'href':     anchors[1]['href'],
                                                'board':    anchors[0].string.strip(),
                                                'author':   tr.findAll('td')[2].string.strip()
                                                    })
                else:
                    results['top10_dis'+str(i)].append({ 'title':    anchors[1].string.strip(),
                                                    'href':     anchors[1]['href'],
                                                    'board':    anchors[0].string.strip(),
                                                    'author':   tr.findAll('td')[2].string.strip()
                                                    })
    
#     results[u'pre_page'] = re.findall(',(\d+)\.html',pageLink['href'])[0]
#     results[u'total_page'] = int(results[u'pre_page']) + page
#     返回页面数目，总页数（只在首页可以获得），当前页数
    return (results,{})
    
    
# ------User-------
@app.route(u'/api/user', methods=[u'GET', u'POST'])
def api_user():
    if 'url' in request.values:
        url = request.values[u'url']
    if 'userid' in request.values:
        url = u'bbsqry?userid=%s'%request.values['userid']
    return user(url=url)
@api(3600)
def user(soup):
    result = {}
    center = soup.center
    
    if len(center(u'table')) == 0:
        result['error'] = unicode(center)
        return (result,{})
    
    pre = center.pre
    result['pre'] = unicode(pre)
    return (result,{})
    

# -----AllBoards--------
@app.route(u'/api/boards', methods=[u'GET', u'POST'])
def api_bbsall():
    '''
    @/api/boards
    
    读取所有版面信息,返回以下对象： ::
    
        results ={
            boards: [
                {
                "bm": "sonichen", //bbsMaster
                "board": "Accounting", 
                "category": "科学", 
                "chinese": "会计", 
                "id": 1, 
                "link": "bbsdoc,board,Accounting.html", 
                "api_link": "/api/board/Accounting",
                "trans": "○"
                }, ...],
                count: 395
            }
    '''
    if 'url' in request.values:
        url = request.values[u'url']
    else:
        url = u'bbsall'
    rurl = request.url[request.url.rindex('/'):]
    if '.' in rurl:
        if '?' in rurl:
            last = rurl.rindex('?')
        else:
            last = len(rurl)
        format = rurl[rurl.rindex('.')+1: last]
    else:
        format = 'json'
    return bbsall(url=url,format=format)
@api(3600)
def bbsall(soup):
    result = {}
    center = soup.center
    
    result['count'] = int(re.findall(u'\[讨论区数: (\\d+)\]',center.contents[2])[0])
    result['boards'] = []
    
    for tr in center(u'tr')[1:]:
        board = {}
        tds = tr(u'td')
        board[u'id'] = int(tds[0].string)
        board[u'board'] = tds[1].a
        board[u'link'] = tds[1].a[u'href']
        board[u'category'] = tds[2].string[1:-1]
        chinese = tds[3].a.string
        board[u'chinese'] = chinese[3:]
        board[u'trans'] = chinese[1]
        board[u'bm'] = u'' if tds[4].a == None else tds[4].a
        board[u'api_link'] = "/api/board/"+board[u'board'].string
        result[u'boards'] .append(board)
    

    return (result,{u'boards':u'board'})
    

if __name__ == '__main__':
    app.run()
#########################################################################
