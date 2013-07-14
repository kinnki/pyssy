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
import cookielib

import urllib, urllib2
from bs4 import BeautifulSoup as BS
import html5lib

from flask import (Flask, g, request, abort, redirect,
                   url_for, render_template, Markup, flash, Response, jsonify)

from dict2xml import dict2xml
from iso8601 import parse_date

application = app = Flask(__name__)
app.debug = True

VERSION = 7
app.config[u'VERSION'] = VERSION


URLBASE="http://bbs.sjtu.edu.cn/"
URLTHREAD=URLBASE+"bbstfind0?"
URLARTICLE=URLBASE+"bbscon?"
URLTHREADALL="bbstcon"
URLTHREADFIND="bbstfind"

cj = cookielib.CookieJar()
cookie = urllib2.HTTPCookieProcessor(cj)
opener = urllib2.build_opener(cookie)
urllib2.install_opener(opener)

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
        return (urllib2.urlopen(URLBASE + url).read().decode("gbk","ignore"), datetime2str(datetime.datetime.now()))  

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

# -----API------
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
            lines = len(html.split('\n'))
            #用一个简单的方法判断页面是否存在
            if lines < 10 and re.search(u'[不存在|错误]', html):
                return 'The page does not exist'
            
            if modified_since == fetch_time:
                return Response(status=304)
            #为了向各别函数里传递maxid参数
            if 'maxid' in kwargs:
                
                result, xml_list_names = func(BS(html,'html5lib'), kwargs.get('maxid'))
            else:
                result, xml_list_names = func(BS(html,'html5lib'))
            #result[u'lines'] = lines   

            roottag = func.__name__
            
            if include and u'articles' in result:
                for artlink in result[u'articles']:
                    art,xl = article(url=artlink[u'link'], format=u'raw')
                    artlink[u'include'] = art
                    xml_list_names.update(xl)
            
            end_parse = time.clock()
            
#             if format != u'raw':
#                 result[u'api'] = {
#                     u'args'             : args,
#                     u'kargs'            : kwargs, 
#                     u'request_url'      : request.url,
#                     u'format'           : format,
#                     u'pretty'           : pretty,
#                     u'callback'         : callback,
#                     u'version'          : app.config[u'VERSION'],
#                     u'values'           : request.values,
#                     u'name'             : roottag,
#                     u'fetch_time'       : fetch_time,
#                     u'fetch_hash'       : hash(html),
#                     u'fetch_elapse'     : end_fetch - start,
#                     u'elapse'           : end_parse - start,
#                 }
            
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
                    return Response('%s(%s);'%(callback, json_result), 
                        headers=headers,
                        content_type='text/javascript; charset=utf-8')
                else:
                    return Response(json_result, 
                        headers=headers,
                        content_type='application/json; charset=utf-8')
        return wrap

@app.errorhandler(404)
def page_not_found(e):
    results = { "result": "fail", "status": 404 }
    json_result = json.dumps( results,
                               ensure_ascii = False, sort_keys=True, indent=4 )
                               
    if 'callback' in request.values:
        callback = request.values['callback']
    else:
        callback = '' 
        
    if callback != '':
        return Response('%s(%s);'%(callback, json_result), 
            content_type='text/javascript; charset=utf-8')
    else:
        return Response(json_result, 
            content_type='application/json; charset=utf-8')
    
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

# ----Index----
@app.route('/')
def hello():
    html= u"""
        <p>欢迎使用pyssy工具。</p>
        <p>目前可以使用以下api</p>
        <dl>
            <dt>/api/topics</dt>
            <dd>获取推荐阅读，今日十大，各分区十大最热话题</dd>
            
            <dt>/api/topic/articles/&lt;board_name&gt;/&lt;reid&gt;</dt>
            <dd>获取指定话题里的所有文章,若选择articles,则返回所有文章，若选择thread,则仅返回文章标题</dd>
            
            <dt>/api/board/&lt;board_name&gt;[/&lt;articles|topics&gt;]</dt>
            <dd>获取指定版面的文章或者话题</dd>
            
            <dt>/api/boards</dt>
            <dd>获取所有版面信息</dd>
            
            <dt>/api/user/&lt;userid&gt;</dt>
            <dd>获取单一用户</dd>
            
            <dt>/api/users/online</dt>
            <dd>获取在线用户</dd> 
        </dl>
        """ 
    return render_template('template.html',body=html)

# -----Articles@Board------
@app.route(u'/api/board/<board>/articles/', methods=[u'GET', u'POST'])
def rest_articles_board(board):
    if request.args.get('page',0) and request.args.get('maxid', ''):
        page = request.args.get('page')
        id = request.args.get('maxid')
        url = u'bbsdoc?board=%s&page=%s'%(board, page)
        #/api/board/board_name/articles?page=323&maxid=333
        return articles_board(url = url, maxid = id)
    url = u'bbsdoc?board=%s'%(board)
    return articles_board(url = url)
@api(60)
def articles_board(soup,*args):
    result = {}
    result[u'board'] = soup.body(u'input', type=u'hidden')[0][u'value']
    title = soup.body.table.tr.font.b.string
    result[u'chinese_title'] = re.findall('\(.*\)$', title)[0][1:-1]
    result[u'wiki'] = soup.body.table.tr.a[u'href']
    try:
        prepageHref = soup.find('a', text=re.compile(u'上一页'))['href']
        result[u'prepage'] = re.search(u'page,(\d+)\.html', prepageHref).group(1)
    except Exception:
        result[u'prepage'] = "0"
    
    nobr = soup.nobr
    links_bms_line = [{
        u'text':unicode(a.string), 
        u'href':a[u'href'], 
        u'action':re.findall(u'^(\w*)',a[u'href'])[0]} 
            for a in nobr.table(u'a')]
    
    result[u'bms'] = [{'bm':bm[u'text'], 'api_link': '/api/user/'+bm[u'text']} for bm in 
        filter( lambda x:x[u'href'].startswith(u'bbsqry?userid='), 
            links_bms_line)]
    
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
    
    trs = soup.findAll('table')[5].findAll('tr')[1:]
    result[u'articles'] = []
    result[u'fixed_articles'] = []
    
    for i in range(len(trs)):
        anchors = trs[i].findAll('a')
        tds = trs[i].findAll('td')
        author = anchors[0].string
        title = anchors[1].string
        href = anchors[1]['href'] #bbscon,board,LoveBridge,file,M.1355037145.A.html
        board, file = re.findall('board[,=](\w+)[,&]file[,=](.*?)(?:$|\.html)', href)[0]
        id = tds[0].string
        try:
            maxid #取第一个id作为最大id,产生more链接时用上 /api/...?page=..&maxid=maxid
        except NameError:
            maxid = int(id)
        date = tds[3].string
        if re.match('\d+', id):
            if args and int(id) < int(args[0]):
                    #指定最大值的情况下做比较，筛选出本页小于最大id的所有帖子            
                    result['articles'].append({
                                                'title':    title,
                                                'href':     href,
                                                'author':   author,
                                                'id':       id,
                                                'date':     date,
                                                'file':     file,
                                                'api_link': '/api/article/'+board+'/'+file
                                                })
            elif not args:
                result['articles'].append({
                                            'title':    title,
                                            'href':     href,
                                            'author':   author,
                                            'id':       id,
                                            'date':     date,
                                            'file':     file,
                                            'api_link': '/api/article/'+board+'/'+file
                                            })                
        else:
            result['fixed_articles'].append({
                                        'title':    title,
                                        'href':     href,
                                        'author':   author,
                                        'id':       id,
                                        'date':     date,
                                        'file':     file,
                                        'api_link': '/api/article/'+board+'/'+file 
                                        })
                                        
    if result[u'prepage'] != '0':
        result[u'more'] = '/api/board/'+board+'/articles/?page='+result[u'prepage']+'&maxid='+str(maxid)
    else:
        result[u'more'] = None
    
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
    
# -----Article@File------
@app.route(u'/api/article/<board>/<file>', methods=[u'GET', u'POST'])
def rest_article(board, file):
    url = u'bbscon,board,%s,file,%s.html'%(board, file)
    return article(url = url)
@api(60)
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
    #pre = result[u'links'][
            
    re_link = unicode(filter(lambda x: x[u'action']==u'bbspst', result[u'links'])[0]['url'])
    result[u'reid'] = int(re.findall(u'(\w*)$',re_link)[0])
    result[u'file_id'] = int(re.findall(u'M\\.(\w*)\\.A',re_link)[0])
    result[u'file'] = 'M.%d.A'%result[u'file_id']
    result[u'api_link'] = u'/api/topic/articles/%s/%s'%(result[u'board'], result[u'reid'])
    
    content = body.table.tr.pre #<pre>content</pre>
    content_raw = unicode(content)[5:-6]
    content_lines = content_raw.split(u'\n')
    result[u'content_lines'] = content_lines
    datetime_str = unicode(content_lines[2])[11:30]
    
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

# -----Topics@Index OR Board--------
@app.route(u'/api/topics/', methods=[u'GET', u'POST'])
@app.route(u'/api/index/topics/', methods=[u'GET', u'POST'])
@app.route(u'/api/board/<board>/', methods=[u'GET', u'POST'])
@app.route(u'/api/board/<board>/topics/', methods=[u'GET', u'POST'])
def rest_topics(board=''):
    '''
    @/api/topics
    
    读取bbs首页十大主题列表,以及推荐阅读
    
    @/api/board/<board>/
    
    读取版块最新主题列表
    '''
    if board:
        if request.args.get('page',0) and request.args.get('maxid', ''):
            page = request.args.get('page')
            id = request.args.get('maxid')
            url = u'bbstdoc?board=%s&page=%s'%(board, page)
            #/api/board/board_name/articles?page=323&maxid=333
            return topics(url = url, maxid = id)
        url = u'bbstdoc,board,%s.html'%(board)
        return topics(url = url)
    else:
        url = u'php/bbsindex.html'
        return topics(url = url)
@api(60)
def topics(soup, *args):
    tables = soup.findAll('table')
    results = {}
    if soup.center:
        #bbstdoc页面
        trs = tables[0].findAll('tr')[1:]
        boardInfo = tables[0].previousSibling.previousSibling.previousSibling #'] 文章4365, 主题2467个'
        #[讨论区: Script] 板主[<a href="bbsqry?userid=prompt">prompt</a>]
        boardName = soup.find(text=re.compile(u'讨论区: \w+\]'))
        results[u'boardName'] = re.search(u'讨论区: (\w+)\]', boardName).group(1)
        boardMaster = tables[0].findPreviousSiblings('a')
        results[u'bms'] = [{'bm': i.string, 'api_link': '/api/user/'+str(i.string)} for i in boardMaster[::-1]]
        try:
            prepageHref = soup.find('a', text=re.compile(u'上一页'))['href']
            prepage = re.search(u'page,(\d+)\.html', prepageHref).group(1)
        except Exception:
            prepage = "0"
        
        results[u'totalTopics'] = re.findall('\d+',unicode(boardInfo))[1]
        results[u'topics'] = []    
        results[u'fixedTopics'] = []
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
                
            try:
                maxid #取第一个id作为最大id,产生more链接时用上 /api/...?page=..&maxid=maxid
            except NameError:
                maxid = int(id)
            
            if re.match('bbstcon',str(anchors[1]['href'])):
                board, reid = re.findall('bbstcon,board,(.*?),reid,(\d+)\.html',str(anchors[1]['href']))[0]       
            elif re.match('bbstopcon',str(anchors[1]['href'])):
                board, file = re.findall('board=(.*)&file=(.*)',str(anchors[1]['href']))[0]
            
            status = tds[1].string
            author = tds[2].contents[0].string
            date = tds[3].string

            reply = re.findall('\((\d+)', unicode(tds[4].contents[1]))

            if len(reply):
                reply = reply[0]
            else:
                reply = None
            if id:
                if args and int(id) < int(args[0]):
                    results['topics'].append({  'title':    title.strip(),
                                                'href':     anchors[1]['href'],
                                                'id':       id,
                                                'status':   status,
                                                'author':   author,
                                                'date':     date,
                                                'reply':    reply,
                                                'api_link': '/api/topic/articles/'+board+'/'+reid
                                                })
                elif not args:
                    results['topics'].append({  'title':    title.strip(),
                                                'href':     anchors[1]['href'],
                                                'id':       id,
                                                'status':   status,
                                                'author':   author,
                                                'date':     date,
                                                'reply':    reply,
                                                'api_link': '/api/topic/articles/'+board+'/'+reid
                                                })
            else:
                results['fixedTopics'].append({  'title':    title.strip(),
                                                'href':     anchors[1]['href'],
                                                'status':   status,
                                                'author':   author,
                                                'date':     date,
                                                'reply':    reply,
                                                'api_link': '/api/topic/articles/'+board+'/'+file+'?opcon=true'
                                                })
        if prepage != '0':
            results[u'more'] = '/api/board/'+board+'/topics/?page='+prepage+'&maxid='+str(maxid)
        else:
            results[u'more'] = None                                            
    else:
        #bbsindex首页
        results[u'recommendation'] = []
        recommendations = tables[10].findAll('tr');
        for recom in recommendations:
            href = recom.findAll('a')[1]['href']
            #href = '/bbstcon?board=feeling&reid=1354047027&file=M.1354047027.A'
            board, reid, file = [x
                                    for x in re.findall('board=(.*)&reid=(\d+)&file=(.*)',
                                                        recom.findAll('a')[1]['href'])][0]
            results[u'recommendation'].append({ 'title':    recom.findAll('a')[1].string,
                                                'href':     href,
                                                'author':   "/api/user/" + recom.findAll('td')[3].string.strip().split('/')[0],
                                                'board':    board,
                                                'date':     recom.findAll('td')[2].string.strip(),
                                                'api_link': '/api/topic/articles/'+board+'/'+reid
                                                })
    
        #get districts top10
        tableIndex = [15,23,26,29,32,35,38,41,44,47,50,53]
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
                href = anchors[1]['href']
                #"/bbstcon?board=PalSword&reid=1354897923", 
                board, reid = [x for x in re.findall('board=(.*)&reid=(\d+)', href)][0]
                
                if not i:  # i==0时，为十大热门话题，单独处理
                    results['top10'].append({   'title':    anchors[1].string.strip(),
                                                'href':     anchors[1]['href'],
                                                'board':    board.strip(),
                                                'author':   tr.findAll('td')[2].string.strip(),
                                                'api_link': '/api/topic/articles/'+board+'/'+reid
                                                    })
                else:
                    results['top10_dis'+str(i)].append({
                                                    'title':    anchors[1].string.strip(),
                                                    'href':     anchors[1]['href'],
                                                    'board':    board.strip(),
                                                    'author':   tr.findAll('td')[2].string.strip(),
                                                    'api_link': '/api/topic/articles/'+board+'/'+reid
                                                    })
    return (results,{})


# -----Thread@Topic--------
@app.route(u'/api/topic/thread/<board>/<reid>', methods=[u'GET', u'POST'])
def rest_thread(board, reid):
    '''
    @//api/topic/<board>/<reid> ##目前只返回json对象
    
	读取主题的所有讨论的标题，返回以下对象：::
	
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
@api(200)
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
            u'title': cont[3].a,
            u'link': link,
            u'board': board,
            u'file': file_,
            u'api_link': "/api/articles/"+board+"/"+file_,
        }
        result['articles'].append(art)
    result[u'count'] = int(re.findall(u'共找到 ([0-9]+) 篇',center[6])[0])
    result[u'board_link'] = center[7][u'href']
    result[u'bbstcon_link'] = center[9][u'href']
    return (result,{'datetime_tuple':'int','articles':'article'})

# -----Articles@Topic------
@app.route(u'/api/topic/articles/<board>/<reid>', methods=[u'GET', u'POST'])
def rest_articles_topic(board, reid):
    '''
    @/api/articles/<boardName>/<reid>
    
    读取topic下的文章,返回以下对象::
    
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
    
    #https://bbs.sjtu.edu.cn/bbstopcon?board=Search&file=T.1333982802.A
    if 'opcon' in request.values: #置底贴
        url = u'bbstopcon?board=%s&file=%s'%(board, reid) #用获得的reid参数替代file
    elif 'page' in request.values:
        url = u'bbstcon?board=%s&reid=%s&page=%s'%(board, reid, request.values['page'])
    else:
        url = u'bbstcon?board=%s&reid=%s'%(board, reid)
    #bbstcon?board=bicycle&reid=1354900460
    return articles(url=url)
@api(16)
def articles(soup):
    results = {}
    body = soup.body.center
    tables = body.findAll('table')
    if not len(tables):
        abort(404)
        
    board_str = body.contents[2] # "[讨论区: BOARD]"
    if re.findall('(\d+)', body.contents[4]):
        results[u'totalArticles'], results[u'totalPages'], results[u'currentPage'] = re.findall('(\d+)', body.contents[4])
    else:
        results[u'totalArticles']=results[u'totalPages']=results[u'currentPage']=None
    
    results[u'title'] = soup.title    
    results[u'board'] = board_str[board_str.rfind(':') + 2 : -1 ]
    results[u'contents'] = []
    
    #bbstcon?board=Script&reid=1358496290&file=M.1358496290.A&page=2
    next = tables[0].findPreviousSiblings('a',text='下一页')
    if next:
        board, reid, page = re.findall(u'board=(.*)&reid=(\d+).*page=(\d+)', next[0]['href'])[0]
        results[u'next'] =  '/api/topic/articles/' + board + '/' + reid + '?page=' + page
    else:
        results[u'next'] = None
        
    pre = tables[0].findPreviousSiblings('a',text='上一页')
    if pre:
        board, reid, page = re.findall(u'board=(.*)&reid=(\d+).*page=(\d+)', pre[0]['href'])[0]
        results[u'pre'] =  '/api/topic/articles/' + board + '/' + reid + '?page=' + page 
    else:
        results[u'pre'] = None
        
    for i in range(len(tables)):
        #每个table代表一篇帖子
        # bug: 一些特殊的帖子需要考虑，如此处 https://bbs.sjtu.edu.cn/bbstcon,board,WebDevelop,reid,1358414689.html
        # bug: 一些帖子不可回复
        content = tables[i].tr.pre  #<pre>content</pre>
        content_raw = unicode(content)[5:-6]
        if 'opcon' in request.values:
            content_lines = content_raw.split(u'\n')
        else:
            content_lines = content_raw.split(u'\n')[1:]
        datetime_str = unicode(content_lines[2])[11:30]
        
        from_lines, from_ip, from_index, edit_times = "", "", -1, 0
        for i in range(len(content_lines)-1, -1, -1):
            if len(re.findall(u'\[FROM: ([\w\.:]*)\]',content_lines[i])) > 0:
                from_index = i
        if from_index != -1:    
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
        
        author = re.search(u'发信人: SJTUBBS \(自动发信系统\)', content_lines[0])
        #发信人: <a href="bbsqry?userid=GetUp">GetUp</a>(起来), 信区: Search
        if author:
            author = 'SJTUBBS'
        else:
            author = re.search(u'userid=(.*)"', content_lines[0]).group(1)
        nick = re.search(u'\(.*\)', content_lines[0])
        if nick:
            nick = nick.group(0)
        #[<a href=\"bbspst?board=Script&amp;file=M.1356509314.A\">回复本文</a>][<a href=\"bbscon?board=Script&amp;file=M.1356509314.A\">原帖</a>] 发信人: <a href=\"bbsqry?userid=PythonShell\">PythonShell</a>(提问机), 信区: Script
        #[<a href='bbspst?board=WebDevelop&file=M.1358414689.A'>回复本文</a>][<a href='bbscon?board=WebDevelop&file=M.1358414689.A'>原帖</a>] </font><font class='c33'>发信人: SJTUBBS (自动发信系统), 信区: WebDevelop                               </font><font class='c37'> 
        results[u'contents'].append({
            u'full_contents':   content_lines,
            u'author': author,
            u'author_link': '/api/user/' + author,
            u'nick' : nick,
            u'board' : content_lines[0][content_lines[0].rfind(' ') + 1:], #信区
            u'title' : content_lines[1][6:],
            u'datetime_str' : datetime_str ,
            u'qmd_lines' : qmd_lines ,
            u'from_lines' : from_lines ,
            u'from_ip' : from_ip ,
            u'reply_lines' : reply_lines,
            u'text_lines' : text_lines,
            u'edit_times' : edit_times, 
        })
        
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

    return (results, xml_list_names)
    
    
# ------User-------
@app.route(u'/api/user/<userid>', methods=[u'GET', u'POST'])
def api_user(userid):
    url = u'bbsqry?userid=%s'%(userid)
    return user(url=url)
@api(3600)
def user(soup):
    results = {}
    center = soup.center
    
    if len(center(u'table')) == 0:
        result['error'] = unicode(center)
        return (result,{})
    
    pre = center.pre
    results['all'] = unicode(pre)
    results[u'user'] = str(pre.contents[0]).strip()[:-1]
    results[u'nick'] = pre.contents[1].string
    results[u'totalLogin'] = pre.contents[3].string
    results[u'onlineAge'] = pre.contents[5].string
    if re.findall(u"天  \[.*>(.*座)", results['all']):
        results[u'constellation'] = re.findall(u"天  \[.*>(.*座)", results['all'])[0]
    else:
        results[u'constellation'] = None
    results[u'lastOnline'], results[u'lastIP'] = re.findall(u"上 次 在.*>(.*)</font>.*从.*?>([\d\.]*)</font>", results['all'])[0]
    
    if re.findall(u"目前在线",results['all']):
        results[u'isOnline'] = True
    else:
        results[u'isOnline'] = False
    
    results[u'life'], results[u'totalArticles'] = re.findall(u"生命力:.*>(\d+)</font>.*文章:.*>(\d+)</font>", unicode(pre))[0]
    
    if re.findall(u"职务: \[(.*)\]", unicode(pre)):
        results[u'isBM'] = True
        bm = re.findall(u"职务: \[(.*)\]", unicode(pre))[0]
        results[u'bM'] = re.sub(u'<.*?>', '', bm)
    else:
        results[u'isBM'] = False
        
    return (results,{})
    
@app.route(u'/api/users/', methods=[u'GET', u'POST'])
@app.route(u'/api/users/online', methods=[u'GET', u'POST'])
def api_user_online():
    url = 'bbsufind?search=*'
    return user_online(url = url)
def user_online(url = ''):
    results = {}
    h = fetch(url, 600)
    online = re.search(u'(\d+)人', h[0]).group(1)
    results[u'online'] = int(online)
    
    results[u'users'] = []
    trs = re.findall(u'<tr>.*userid=(.*?)>.*?((?:\d+\.){3}\d+)', h[0])
    for tr in trs:
        userid, ip = tr
        results[u'users'].append({
                                    'userid':   userid,
                                    'ip':       ip
                                })

                                
    json_result = json.dumps( results,
                               ensure_ascii = False, sort_keys=True, indent=4 )
                               
    if 'callback' in request.values:
        callback = request.values['callback']
    else:
        callback = ''                                
    
    if callback != '':
        return Response('%s(%s);'%(callback, json_result), 
            content_type='text/javascript; charset=utf-8')
    else:
        return Response(json_result, 
            content_type='application/json; charset=utf-8')


# -----AllBoards--------
@app.route(u'/api/boards/', methods=[u'GET', u'POST'])
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

# -----Login--------
@app.route(u'/api/login/', methods=[u'GET', u'POST'])
def api_login():
    url = "https://bbs.sjtu.edu.cn/bbslogin"
    isLogin = False
    data = {}
    data['id'] = request.values['user']  #testapi
    data['pw'] = request.values['password']  #testapi
    data["submit"] = "login"
    
    req = urllib2.Request(url, urllib.urlencode(data))
    response = urllib2.urlopen(req).read().decode('gb2312','ignore')
    if re.search(u'frameset', response):
        return jsonify(isLogin = True, token = "%s_%s_%s" % tuple([x.value for x in cj]))
    else:
        return jsonify(isLogin = False, message = "Wrong username or password, or new user waiting for authorizing")

# -----MailLists--------
@app.route(u'/api/mail/', methods=[u'GET', u'POST'])
def api_mail():
    #mail check
    if 'token' not in request.values:
        return jsonify( result = "Fail", message = "Please check your login token" )
    
    if 'more' in request.values:
        url = "https://bbs.sjtu.edu.cn/bbsmail?start=" + request.values['more'].split('_')[1]
    else:
        url = "https://bbs.sjtu.edu.cn/bbsmail"
    token = request.values['token'].split('_')
    req = urllib2.Request(  url,
                            headers = { 'Cookie': "utmpuserid=%s; utmpkey=%s; utmpnum=%s" % (token[2], token[0], token[1]),
                                        "Referer": "https://bbs.sjtu.edu.cn/bbsleftnew"
                                        }
                        )
    response = urllib2.urlopen(req).read().decode('gbk','ignore')
    soup = BS(response,'html5lib')
    if re.search(u'ERROR', response):
        return jsonify({'result': 'fail'}) 
    
    table = soup.table
    
    results = {}
    
    results['mail'] = []
    unread = 0
    for tr in table.findAll('tr')[1:]:
        order = tr.contents[0].string
        status = tr.contents[2].string
        if status == 'N':
            unread = unread + 1
        sendfrom = tr.contents[3].string.lstrip()
        date = tr.contents[4].string
        file, num = re.findall(u'file=(.*)&num=(\d+)', tr.contents[5].a['href'])[0]
        link = "/api/mail/read?file=%s&num=%s" % (file, num)
        title = tr.contents[5].a.contents[0]
        results['mail'].append( {
                                    'order':    order,
                                    'status':   status,
                                    'sendfrom': sendfrom,
                                    'date':     date,
                                    'link':     link,
                                    'title':    title.strip(' /a>(')
                                })
    results['unread'] = unread
    results['total'] = re.findall(u'信件总数: (\d+)封', table.nextSibling.nextSibling.nextSibling.nextSibling)[0]
    more = re.findall(u'\?start=(\d+)', table.findNextSiblings('a')[2]['href'])
    if more: 
        results['more'] = "/api/mail?more=startfrom_" + more[0]
    else:
        results['more'] = ''
        
    return json.dumps(results,
                        ensure_ascii = False, sort_keys=True, indent=4)
        
# -----NewMail--------
@app.route(u'/api/mail/new', methods=[u'GET', u'POST'])
def api_newmail():
    #mail check
    if 'token' not in request.values \
        or 'title' not in request.values \
        or 'text' not in request.values \
        or 'touser' not in request.values:
        return jsonify( result = "Fail", message = "Please check your login token" )
    
    url = "https://bbs.sjtu.edu.cn/bbssndmail"
    data = {}
    data['title'] = request.values['title']
    data['text'] = request.values['text']
    data['userid'] = request.values['touser']
    data['signature'] = 1
    token = request.values['token'].split('_')
    
    req = urllib2.Request(  url,
                            headers = { 'Cookie': "utmpuserid=%s; utmpkey=%s; utmpnum=%s" % (token[2], token[0], token[1]),
                                        "Referer": "https://bbs.sjtu.edu.cn/bbsleftnew"
                                        },
                            data = urllib.urlencode(data)
                        )
    response = urllib2.urlopen(req).read().decode('gbk','ignore')
    if re.search(u'已寄给', response):
        return jsonify({'result': 'success', 'message': 'success'})
        
# -----ReadMail--------
@app.route(u'/api/mail/read', methods=[u'GET', u'POST'])
def api_readmail():
    if 'file' not in request.values \
    or 'token' not in request.values:
        return jsonify({ 'result': 'Fail', 'Message': 'Missing parameter' })
    
    url = "https://bbs.sjtu.edu.cn/bbsmailcon?file=%s&num=%s" % (request.values['file'], request.values['num'])
    token = request.values['token'].split('_')
    req = urllib2.Request(  url,
                            headers = { 'Cookie': "utmpuserid=%s; utmpkey=%s; utmpnum=%s" % (token[2], token[0], token[1]),
                                        "Referer": "https://bbs.sjtu.edu.cn/bbsmail"
                                        }
                        )
    response = urllib2.urlopen(req).read().decode('gbk', 'ignore')
    #return response
    soup = BS(response,'html5lib')
    pre = soup.table.pre
    
    result = {}
    result['next'] = result['previous'] = ""
        
    
    try:
        content = pre.contents[0]
    except:
        content = ""
    
    if content == u'寄信人: ': #包含有寄信人信息的Mail
        lines = unicode(pre).split("\n")
        user = pre.a.string
        
        title = lines[1][6:]
        posOfPar = lines[2].find("(")
        date = pre.contents[2].split("\n")[2][posOfPar+1: -1]
        ip = lines[3][6: -1]
        
        text = lines[5:-2]
        
        result['user'] = user
        result['api_user'] = "/api/user/" + user
        result['title'] = title
        result['date'] = date
        result['ip'] = ip
        result['text'] = text
    else: #系统信息不带有寄信人信息
        result['text'] = content
            
    if re.search(u'ERROR', response):
        return jsonify({'result': 'fail'}) 
    
    return jsonify(result)
    
# -----NewTopic--------
@app.route(u'/api/topic/create/', methods=[u'GET', u'POST'])
def api_newTopic():
    if  'title' not in request.values \
        or  'text' not in request.values \
        or  'token' not in request.values:
        return jsonify( result = "Fail", message = "Parameters missing" )
        
    url = "https://bbs.sjtu.edu.cn/bbssnd"
    title = request.values['title'].encode('gb2312')
    text = request.values['text'].encode('gb2312')
    board = request.values['board']
    token = request.values['token'].split('_')
    
    data = {'board':          board,
            'title':          title,
            'text':           text,
            'file':           '',
            'reidstr':        '',
            'reply_to_user':  '',
            'signatrure':     '1',
            'autocr':         'on'
    }
    
    req = urllib2.Request(  url,
                            headers = { 'Cookie': "utmpuserid=%s; utmpkey=%s; utmpnum=%s" % (token[2], token[0], token[1]),
                                        "Referer": "https://bbs.sjtu.edu.cn/bbsleftnew"
                                        },
                            data = urllib.urlencode(data)
                        )
    response = urllib2.urlopen(req).read()
    if not re.search(u'ERROR', response):
        return jsonify( result = "Success", message = "Topic has been successfully posted" )
    else:
        return  jsonify( result = "Fail", message = "Please check the board name or sth else." )

# -----ReplyTopic--------
@app.route(u'/api/topic/reply/', methods=[u'GET', u'POST'])
def api_replyTopic():
    if  'title' not in request.values \
        or 'text' not in request.values \
        or 'file' not in request.values \
        or 'reidstr' not in request.values \
        or 'replyto' not in request.values \
        or 'token' not in request.values:
        return jsonify( result = "Fail", message = "Parameters missing" )
        
    url = "https://bbs.sjtu.edu.cn/bbssnd"
    title = request.values['title'].encode('gb2312')
    text = request.values['text'].encode('gb2312')
    board = request.values['board']
    file = request.values['file']
    reid = request.values['reidstr']
    replyto = request.values['replyto']
    token = request.values['token'].split('_')
    
    data = {'board':          board,
            'title':          title,
            'text':           text,
            'file':           file,
            'reidstr':        reid,
            'reply_to_user':  replyto,
            'signatrure':     '1',
            'autocr':         'on'
    }
    
    req = urllib2.Request(  url,
                            headers = { 'Cookie': "utmpuserid=%s; utmpkey=%s; utmpnum=%s" % (token[2], token[0], token[1]),
                                        "Referer": "https://bbs.sjtu.edu.cn/bbsleftnew"
                                        },
                            data = urllib.urlencode(data)
                        )
    response = urllib2.urlopen(req).read()
    
    if not re.search(u'ERROR', response):
        return jsonify( result = "Success", message = "Topic has been successfully posted" )
    else:
        return  jsonify( result = "Fail", message = "Please check the board name or sth else, or the topic is not allowed to reply" )    
    return jsonify( result = "Fail", message = "not login or missing file parameter" )
    
# -----EditTopic--------
@app.route(u'/api/topic/edit/', methods=[u'GET', u'POST'])
def api_editTopic():
    if 'board' not in request.values or 'file' not in request.values or 'token' not in request.values:
        return jsonify( result = "Fail", message = "not login or missing file parameter" )
        
    #url = 'https://bbs.sjtu.edu.cn/bbsedit?board=%s&file=%s' % (request.values['board'], request.values['file'])
    url = "https://bbs.sjtu.edu.cn/bbsedit"
    token = request.values['token'].split('_')
    
    data = {'board':        request.values['board'],
            'title':        request.values['title'].encode('gb2312'),
            'text':         request.values['text'].encode('gb2312'),
            'file':         request.values['file'],
            'type':         1
    }
    
    req = urllib2.Request(  url,
                            headers = { 'Cookie': "utmpuserid=%s; utmpkey=%s; utmpnum=%s" % (token[2], token[0], token[1]),
                                        "Referer": "https://bbs.sjtu.edu.cn/bbsleftnew"
                                        },
                            data = urllib.urlencode(data)
                        )
    response = urllib2.urlopen(req).read()
    if re.search(u'ERROR', response):
        return jsonify( result = 'Fail', message = 'Check is login' )
    return  response

# -----DelTopic--------
@app.route(u'/api/topic/del/', methods=[u'GET', u'POST'])
def api_delTopic():
    if 'board' not in request.values or 'file' not in request.values or 'token' not in request.values:
        return jsonify( result = "Fail", message = "not login or missing file parameter" )
    
    url = "https://bbs.sjtu.edu.cn/bbsdel?board=%s&file=%s" % (request.values['board'], request.values['file'])
    token = request.values['token'].split('_')
    
    req = urllib2.Request(  url,
                            headers = { 'Cookie': "utmpuserid=%s; utmpkey=%s; utmpnum=%s" % (token[2], token[0], token[1]),
                                        "Referer": "https://bbs.sjtu.edu.cn/bbsleftnew"
                                        }
                        )
    response = urllib2.urlopen(req).read()
    if re.search(u'ERROR', response):
        return jsonify( result = 'Fail', message = 'Not login or missing parameters' )
    return  jsonify( result = 'Success', message = 'Topic deleted.' )
    

if __name__ == '__main__':
    app.run()
#########################################################################
