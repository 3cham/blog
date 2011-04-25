# This code is in Public Domain. Take all the code you want, we'll just write more.
import bz2
import cgi
import datetime
import logging
import math
import os
import pickle
import re
import sha
import string
import StringIO
import time
import traceback
import urllib
import wsgiref.handlers
from google.appengine.ext import db
from google.appengine.api import mail
from google.appengine.api import memcache
from google.appengine.api import urlfetch
from google.appengine.api import users
from google.appengine.ext import webapp
from google.appengine.ext.webapp import template
from django.utils import feedgenerator
from django.template import Context, Template

COMPRESS_PICKLED = False
USE_MEMCACHE = True

# deployed name of the server. Only for redirection from *.appspot.com 
SERVER = "blog.kowalczyk.info"

# memcache key for caching atom.xml
ATOM_MEMCACHE_KEY = "at"
ATOM_ALL_MEMCACHE_KEY = "ata"
JSON_ADMIN_MEMCACHE_KEY = "jsa"
JSON_NON_ADMIN_MEMCACHE_KEY = "jsna"

NOTE_TAG = "note"

# e.g. "http://localhost:8081" or "http://blog.kowalczyk.info"
g_root_url = None

HTTP_NOT_ACCEPTABLE = 406

(POST_DATE, POST_FORMAT, POST_BODY, POST_TITLE, POST_TAGS, POST_URL, POST_PRIVATE) = ("date", "format", "body", "title", "tags", "url", "private")

ALL_FORMATS = (FORMAT_TEXT, FORMAT_HTML, FORMAT_TEXTILE, FORMAT_MARKDOWN) = ("text", "html", "textile", "markdown")

class TextContent(db.Model):
    content = db.TextProperty(required=True)
    published_on = db.DateTimeProperty(auto_now_add=True)
    format = db.StringProperty(required=True,choices=set(ALL_FORMATS))
    # sha1 of content + format
    sha1_digest = db.StringProperty(required=True)

class Article(db.Model):
    permalink = db.StringProperty(required=True)
    # for redirections
    permalink2 = db.StringProperty(required=False)
    is_public = db.BooleanProperty(default=False)
    is_deleted = db.BooleanProperty(default=False)
    title = db.StringProperty()
    # copy of TextContent.content
    body = db.TextProperty(required=True)
    # copy of TextContent.published_on of first version
    published_on = db.DateTimeProperty(auto_now_add=True)
    # copy of TextContent.published_on of last version
    updated_on = db.DateTimeProperty(auto_now_add=True)
    # copy of TextContent.format
    format = db.StringProperty(required=True,choices=set(ALL_FORMATS))
    tags = db.StringListProperty(default=[])
    # points to TextContent
    previous_versions = db.ListProperty(db.Key, default=[])

def to_rfc339(dt): return dt.strftime('%Y-%m-%dT%H:%M:%SZ')

def to_simple_date(dt): return dt.strftime('%Y-%m-%d')

def httpdate(dt): return dt.strftime('%a, %d %b %Y %H:%M:%S GMT')

def utf8_to_uni(val): return unicode(val, "utf-8")

BASE_36_LETTERS = "0123456789abcdefghijklmnopqrstuvwxyz"
def baseN(n, b, numerals=BASE_36_LETTERS):
    return ((n == 0) and  "0" ) or ( baseN(n // b, b, numerals).lstrip("0") + numerals[n % b])

def shortenId(n): return baseN(n, 36)
def expandId(s): return int(s, 36)
def getIdFromUrl(s):
    parts = s.split("/")
    if len(parts) == 1: return None
    for c in parts[0]:
        if c not in BASE_36_LETTERS: return None
    # TODO: check for max length?
    return expandId(parts[0])

def isUrlWithId(s): return None != getIdFromUrl(s)

def encode_code(text):
    for (txt,replacement) in [("&","&amp;"), ("<","&lt;"), (">","&gt;")]:
        text = text.replace(txt, replacement)
    return text

def txt_cookie(txt): return sha.new(txt.encode("utf-8")).hexdigest()

def my_hostname():
    # TODO: handle https as well
    h = "http://" + os.environ["SERVER_NAME"];
    port = os.environ["SERVER_PORT"]
    if port != "80":
        h += ":%s" % port
    return h

def articles_info_memcache_key():
    if COMPRESS_PICKLED:
        return "akc"
    return "ak"

def clear_memcache():
    memcache.delete(articles_info_memcache_key())
    memcache.delete(ATOM_MEMCACHE_KEY)
    memcache.delete(ATOM_ALL_MEMCACHE_KEY)
    memcache.delete(JSON_ADMIN_MEMCACHE_KEY)
    memcache.delete(JSON_NON_ADMIN_MEMCACHE_KEY)

def build_articles_summary():
    ATTRS_TO_COPY = ["title", "permalink", "published_on", "format", "tags", "is_public", "is_deleted"]
    query = Article.all()
    articles = []
    for article in query:
        a = {}
        for attr in ATTRS_TO_COPY:
            a[attr] = getattr(article,attr)
        articles.append(a)
    articles.sort(lambda x, y: cmp(y["published_on"], x["published_on"]))
    return articles

def build_articles_json(for_admin):
    import simplejson as json
    ATTRS_TO_COPY = ["title", "permalink", "published_on", "tags", "is_public", "is_deleted"]
    query = Article.all()
    articles = []
    for article in query:
        if article.is_deleted or not article.is_public and not for_admin:
            continue
        a = []
        a.append(getattr(article, "published_on"))
        a.append(getattr(article, "permalink"))
        a.append(getattr(article, "title"))
        a.append(getattr(article, "tags"))
        a.append(getattr(article, "is_public"))
        a.append(getattr(article, "is_deleted"))
        articles.append(a)
    articles.sort(lambda x, y: cmp(y[0], x[0]))
    for a in articles:
        a[0] = to_simple_date(a[0])
    #json_txt = json.dumps(articles, indent=4) # pretty-printed version
    #json_txt = json.dumps(articles) # regular version
    json_txt = json.dumps(articles, separators=(',',':')) # compact version
    return "var __articles_json = %s; articlesJsonLoaded(__articles_json);" % json_txt

def pickle_data(data):
    fo = StringIO.StringIO()
    pickle.dump(data, fo, pickle.HIGHEST_PROTOCOL)
    pickled_data = fo.getvalue()
    if COMPRESS_PICKLED:
        pickled_data = bz2.compress(pickled_data)
    #fo.close()
    return pickled_data

def unpickle_data(data_pickled):
    if COMPRESS_PICKLED:
        data_pickled = bz2.decompress(data_pickled)
    fo = StringIO.StringIO(data_pickled)
    data = pickle.load(fo)
    fo.close()
    return data

def filter_nonadmin_articles(articles_summary):
    for article_summary in articles_summary:
        if article_summary["is_public"] and not article_summary["is_deleted"]:
            yield article_summary

def filter_deleted_articles(articles_summary):
    for article_summary in articles_summary:
        if not article_summary["is_deleted"]:
            yield article_summary

# not private: not public and not deleted
def filter_nonprivate_articles(articles_summary):
    for article_summary in articles_summary:
        if not article_summary["is_public"] and not article_summary["is_deleted"]:
            yield article_summary

def filter_nondeleted_articles(articles_summary):
    for article_summary in articles_summary:
        if article_summary["is_deleted"]:
            yield article_summary

def filter_notes(articles_summary):
    for article_summary in articles_summary:
        if NOTE_TAG not in article_summary['tags']:
            yield article_summary
    
def filter_by_tag(articles_summary, tag):
    for article_summary in articles_summary:
        if tag in article_summary["tags"]:
            yield article_summary

def new_or_dup_text_content(body, format):
    assert isinstance(body, unicode)
    assert isinstance(format, unicode)
    full = body + format
    sha1_digest = sha.new(full.encode("utf-8")).hexdigest()
    existing = TextContent.gql("WHERE sha1_digest = :1", sha1_digest).get()
    if existing: 
        return (existing, True)
    text_content = TextContent(content=body, format=format, sha1_digest=sha1_digest)
    text_content.put()
    return (text_content, False)

(ARTICLE_SUMMARY_PUBLIC_OR_ADMIN, ARTICLE_PRIVATE, ARTICLE_DELETED) = range(3)

def get_articles_summary(articles_type = ARTICLE_SUMMARY_PUBLIC_OR_ADMIN, include_notes=True, tag=None):
    pickled = None
    if USE_MEMCACHE: pickled = memcache.get(articles_info_memcache_key())
    if pickled:
        articles_summary = unpickle_data(pickled)
        #logging.info("len(articles_summary) = %d" % len(articles_summary))
    else:
        articles_summary = build_articles_summary()
        pickled = pickle_data(articles_summary)
        #logging.info("len(articles_pickled) = %d" % len(pickled))
        memcache.set(articles_info_memcache_key(), pickled)
    if articles_type == ARTICLE_SUMMARY_PUBLIC_OR_ADMIN:
        if users.is_current_user_admin():
            articles_summary = filter_deleted_articles(articles_summary)
        else:
            articles_summary = filter_nonadmin_articles(articles_summary)
    elif articles_type == ARTICLE_PRIVATE:
        articles_summary = filter_nonprivate_articles(articles_summary)
    elif articles_type == ARTICLE_DELETED:
        articles_summary = filter_nondeleted_articles(articles_summary)
    if not include_notes: articles_summary = filter_notes(articles_summary)
    if tag: articles_summary = filter_by_tag(articles_summary, tag)
    return list(articles_summary)

def get_articles_json():
    memcache_key = JSON_NON_ADMIN_MEMCACHE_KEY
    if users.is_current_user_admin():
        memcache_key = JSON_ADMIN_MEMCACHE_KEY

    articles_json = None
    if USE_MEMCACHE: articles_json = memcache.get(memcache_key)
    if not articles_json:
        #logging.info("re-generating articles_json")
        for_admin = users.is_current_user_admin()
        articles_json = build_articles_json(for_admin)
        memcache.set(memcache_key, articles_json)
    else:
        #logging.info("articles_json in cache")
        pass
    sha1 = sha.new(articles_json).hexdigest()
    return (articles_json, sha1)

def get_article_json_url():
    (json, sha1) = get_articles_json()
    return "/djs/articles.js?%s" % sha1

def show_analytics(): return not is_localhost()

def jquery_url():
    url = "http://ajax.googleapis.com/ajax/libs/jquery/1.4.2/jquery.min.js"
    if is_localhost(): url = "/js/jquery-1.4.2.js"
    return url

def prettify_js_url():
    return "/js/prettify.js"

def prettify_css_url():
    return "/js/prettify.css"

def is_empty_string(s):
    if not s: return True
    s = s.strip()
    return 0 == len(s)

def urlify(title):
    url = re.sub('-+', '-', 
                  re.sub('[^\w-]', '', 
                         re.sub('\s+', '-', title.strip())))
    return url[:48]

def tags_from_string_iter(tags_string):
  for t in tags_string.split(","):
      t = t.strip()
      if t:
          yield t

# given e.g. "a, b  c , ho", returns ["a", "b", "c", "ho"]
def tags_from_string(tags_string):
    return [t for t in tags_from_string_iter(tags_string)]

def checkbox_to_bool(checkbox_val): return "on" == checkbox_val.strip()

def is_localhost():
    return "://localhost" in g_root_url or "://127.0.0.1" in g_root_url

def remember_root_url(wsgi_app):
    def helper(env, start_response):
        global g_root_url
        g_root_url = env["wsgi.url_scheme"] + "://" + env["HTTP_HOST"]
        return wsgi_app(env, start_response)
    return helper

def redirect_from_appspot(wsgi_app):
    def redirect_if_needed(env, start_response):
        if env["HTTP_HOST"].startswith('kjkblog.appspot.com'):
            import webob, urlparse
            request = webob.Request(env)
            scheme, netloc, path, query, fragment = urlparse.urlsplit(request.url)
            url = urlparse.urlunsplit([scheme, SERVER, path, query, fragment])
            start_response('301 Moved Permanently', [('Location', url)])
            return ["301 Moved Peramanently", "Click Here %s" % url]
        else:
            return wsgi_app(env, start_response)
    return redirect_if_needed

def template_out(response, template_name, template_values = {}):

    template_values['jquery_url'] = jquery_url()
    template_values['prettify_js_url'] = prettify_js_url()
    template_values['prettify_css_url'] = prettify_css_url()
    template_values['articles_js_url'] = get_article_json_url()

    response.headers['Content-Type'] = 'text/html'
    #path = os.path.join(os.path.dirname(__file__), template_name)
    path = template_name
    #logging.info("tmpl: %s" % path)
    res = template.render(path, template_values)
    response.out.write(res)

def do_404(response, url):
    response.set_status(404)
    template_out(response, "tmpl/404.html", { "url" : url })

def get_redirect(url):
    import redirects
    return redirects.redirects.get(url, None)

def lang_to_prettify_lang(lang):
    #from http://google-code-prettify.googlecode.com/svn/trunk/README.html
    #"bsh", "c", "cc", "cpp", "cs", "csh", "cyc", "cv", "htm", "html",
    #"java", "js", "m", "mxml", "perl", "pl", "pm", "py", "rb", "sh",
    #"xhtml", "xml", "xsl".
    LANG_TO_PRETTIFY_LANG_MAP = { 
        "c" : "c", 
        "c++" : "cc", 
        "cpp" : "cpp", 
        "python" : "py",
        "html" : "html",
        "xml" : "xml",
        "perl" : "pl",
        "c#" : "cs",
        "javascript" : "js",
        "java" : "java"
    }
    if lang in LANG_TO_PRETTIFY_LANG_MAP:
        return "lang-%s" % LANG_TO_PRETTIFY_LANG_MAP[lang]
    return None

def txt_with_code_parts(txt):
    code_parts = {}
    while True:
        code_start = txt.find("<code", 0)
        if -1 == code_start: break
        lang_start = code_start + len("<code")
        lang_end = txt.find(">", lang_start)
        if -1 == lang_end: break
        code_end_start = txt.find("</code>", lang_end)
        if -1 == code_end_start: break
        code_end_end = code_end_start + len("</code>")
        lang = txt[lang_start:lang_end].strip()
        code = txt[lang_end+1:code_end_start].strip()
        prettify_lang = None
        if lang:
            prettify_lang = lang_to_prettify_lang(lang)
        if prettify_lang:
            new_code = '<pre class="prettyprint %s">\n%s</pre>' % (prettify_lang, encode_code(code))
        else:
            new_code = '<pre class="prettyprint">\n%s</pre>' % encode_code(code)
        new_code_cookie = txt_cookie(new_code)
        assert(new_code_cookie not in code_parts)
        code_parts[new_code_cookie] = new_code
        to_replace = txt[code_start:code_end_end]
        txt = txt.replace(to_replace, new_code_cookie)
    return (txt, code_parts)

def markdown_with_code_to_html(txt):
    from markdown2 import markdown
    (txt, code_parts) = txt_with_code_parts(txt)
    html = markdown(txt)
    for (code_replacement_cookie, code_html) in code_parts.items():
        html = html.replace(code_replacement_cookie, code_html)
    return html

def textile_with_code_to_html(txt):
    from textile import textile
    (txt, code_parts) = txt_with_code_parts(txt)
    txt = txt.encode('utf-8')
    html = textile(txt, encoding='utf-8', output='utf-8')
    html =  unicode(html, 'utf-8')
    for (code_replacement_cookie, code_html) in code_parts.items():
        html = html.replace(code_replacement_cookie, code_html)
    return html

def text_with_code_to_html(txt):
    (txt, code_parts) = txt_with_code_parts(txt)
    html = plaintext2html(txt)
    for (code_replacement_cookie, code_html) in code_parts.items():
        html = html.replace(code_replacement_cookie, code_html)
    return html

# from http://www.djangosnippets.org/snippets/19/
re_string = re.compile(r'(?P<htmlchars>[<&>])|(?P<space>^[ \t]+)|(?P<lineend>\r\n|\r|\n)|(?P<protocal>(^|\s)((http|ftp)://.*?))(\s|$)', re.S|re.M|re.I)
def plaintext2html(text, tabstop=4):
    def do_sub(m):
        c = m.groupdict()
        if c['htmlchars']:
            return cgi.escape(c['htmlchars'])
        if c['lineend']:
            return '<br>'
        elif c['space']:
            t = m.group().replace('\t', '&nbsp;'*tabstop)
            t = t.replace(' ', '&nbsp;')
            return t
        elif c['space'] == '\t':
            return ' '*tabstop
        else:
            url = m.group('protocal')
            if url.startswith(' '):
                prefix = ' '
                url = url[1:]
            else:
                prefix = ''
            last = m.groups()[-1]
            if last in ['\n', '\r', '\r\n']:
                last = '<br>'
            return '%s<a href="%s">%s</a>%s' % (prefix, url, url, last)
    return re.sub(re_string, do_sub, text)

def gen_html_body(format, txt):
    if format == "textile":
        html = textile_with_code_to_html(txt)
    elif format == "markdown":
        html = markdown_with_code_to_html(txt)
    elif format == "text":
        html = text_with_code_to_html(txt)
    elif format == "html":
        # TODO: code highlighting for html
        html = txt
    return html

def article_gen_html_body(article):
    article.html_body = gen_html_body(article.format, article.body)

def article_summary_gen_html_body(article):
    permalink = article["permalink"]
    article2 = Article.gql("WHERE permalink = :1", permalink).get()
    html = gen_html_body(article["format"], article2.body)
    article["html_body"] = html

def do_sitemap_ping():
    if is_localhost(): return
    sitemap_url = "%s/sitemap.xml" % g_root_url
    form_fields = { "sitemap" : sitemap_url }
    urlfetch.fetch(url="http://www.google.com/webmasters/tools/ping",
                   payload=urllib.urlencode(form_fields),
                   method=urlfetch.GET)
    logging.info("Pinged http://www.google.com/webmasters/tools/ping with %s" % sitemap_url)

def find_next_prev_article(article):
    articles_summary = get_articles_summary()
    permalink = article.permalink
    num = len(articles_summary)
    i = 0
    next = None
    prev = None
    # TODO: could bisect for (possibly) faster search
    while i < num:
        a = articles_summary[i]
        if a["permalink"] == permalink:
            if i > 0:
                next = articles_summary[i-1]
            if i < num-1:
                prev = articles_summary[i+1]
            return (next, prev, i, num)
        i = i + 1
    return (next, prev, i, num)

def get_login_logut_url(url):
    if users.is_current_user_admin():
        return users.create_logout_url(url)
    else:
        return users.create_login_url(url)

def url_for_tag(tag):
    return '<a href="/tag/%s" class="taglink">%s</a>' % (urllib.quote(tag), tag)

def render_article(response, article):
    full_permalink = g_root_url + "/" + article.permalink
    article_gen_html_body(article)
    (next, prev, article_no, articles_count) = find_next_prev_article(article)
    tags_urls = [url_for_tag(tag) for tag in article.tags]
    vals = {
        'is_admin' : users.is_current_user_admin(),
        'login_out_url' : get_login_logut_url(full_permalink),
        'article' : article,
        'next_article' : next,
        'prev_article' : prev,
        'show_analytics' : show_analytics(),
        'tags_display' : ", ".join(tags_urls),
        'article_no' : article_no + 1,
        'articles_count' : articles_count,
        'full_permalink' : full_permalink,
    }
    template_out(response, "tmpl/article.html", vals)

ARTICLES_PER_PAGE = 5

class PageHandler(webapp.RequestHandler):
    # for human readability, pageno starts with 1
    def do_page(self, pageno):
        articles_summary = get_articles_summary(include_notes=False)
        articles_count = len(articles_summary)
        pages_count = int(math.ceil(float(articles_count) / float(ARTICLES_PER_PAGE)))
        if pageno > pages_count:
            pageno = pages_count

        first_article = (pageno - 1) * ARTICLES_PER_PAGE
        last_article = first_article + ARTICLES_PER_PAGE
        if last_article > articles_count:
            last_article = articles_count
        articles_summary = articles_summary[first_article:last_article]
        articles_summary_set_tags_display(articles_summary)
        no = 1
        for article in articles_summary:
            article_summary_gen_html_body(article)
            article["no"] = no
            no += 1
        newer_page = None
        if pageno > 1:
            newer_page = { 'no' : pageno - 1 }
        older_page = None
        if pageno < pages_count:
            older_page = { 'no' : pageno + 1 }

        # don't index those pages except the first one
        no_index = True
        if newer_page == None: no_index = False

        vals = {
            'is_admin' : users.is_current_user_admin(),
            'login_out_url' : get_login_logut_url("/page/%d" % pageno),
            'articles_summary' : articles_summary,
            'articles_count' : articles_count,
            'newer_page' : newer_page,
            'older_page' : older_page,
            'page_no' : pageno,
            'pages_count' : pages_count,
            'show_analytics' : show_analytics(),
            'no_index' : no_index,
        }
        template_out(self.response, "tmpl/articles.html", vals)

    def get(self, pageno):
        self.do_page(int(pageno))

# responds to /
class IndexHandler(PageHandler):
    def get(self):
        self.do_page(1)

NOTES_PER_PAGE = 10
# responds to /notes/(.*)
class NotesHandler(webapp.RequestHandler):
    def get(self, pageno):
        pageno = (1 if len(pageno) == 0 else int(pageno))
        articles_summary = get_articles_summary(tag="note")
        articles_count = len(articles_summary)
        pages_count = int(math.ceil(float(articles_count) / float(NOTES_PER_PAGE)))
        if pageno > pages_count:
            pageno = pages_count

        first_article = (pageno - 1) * NOTES_PER_PAGE
        last_article = first_article + NOTES_PER_PAGE
        if last_article > articles_count:
            last_article = articles_count
        articles_summary = articles_summary[first_article:last_article]
        articles_summary_set_tags_display(articles_summary, to_exclude=[NOTE_TAG])
        no = 1
        for article in articles_summary:
            article_summary_gen_html_body(article)
            article["no"] = no
            no += 1
        newer_page = None
        if pageno > 1:
            newer_page = { 'no' : pageno - 1 }
        older_page = None
        if pageno < pages_count:
            older_page = { 'no' : pageno + 1 }

        no_index = True  # don't index those pages

        vals = {
            'is_admin' : users.is_current_user_admin(),
            'login_out_url' : get_login_logut_url("/notes/%d" % pageno),
            'articles_summary' : articles_summary,
            'articles_count' : articles_count,
            'newer_page' : newer_page,
            'older_page' : older_page,
            'page_no' : pageno,
            'pages_count' : pages_count,
            'show_analytics' : show_analytics(),
            'no_index' : no_index,
        }
        template_out(self.response, "tmpl/notes.html", vals)
        

# responds to /tag/${tag}
class TagHandler(webapp.RequestHandler):
    def get(self, tag):
        tag = urllib.unquote(tag)
        do_archives(self.response, get_articles_summary(tag=tag), self.request.path, tag)

# responds to /djs/${url}
class JsHandler(webapp.RequestHandler):
    def get(self, url):
        #logging.info("JsHandler, asking for '%s'" % url)
        if url == "articles.js":
            (json_txt, sha1) = get_articles_json()
            # must over-ride Cache-Control (is 'no-cache' by default)
            self.response.headers['Cache-Control'] = 'public, max-age=31536000'
            self.response.headers['Content-Type'] = 'text/javascript '
            now = datetime.datetime.now()
            expires_date_txt = httpdate(now + datetime.timedelta(days=365))
            self.response.headers.add_header("Expires", expires_date_txt)
            self.response.out.write(json_txt)

def article_only_for_admin(article): return article and (article.is_deleted or not article.is_public)
    
# responds to /article/* and /kb/* and /blog/* (/kb and /blog for redirects
# for links from old website)
class ArticleHandler(webapp.RequestHandler):
    def get(self, url):
        article = None
        articleId = getIdFromUrl(url)
        if articleId: article = Article.get_by_id(articleId)
        if not article:
            permalink = "article/" + url
            article = Article.gql("WHERE permalink = :1", permalink).get()
        if not article:
            #logging.info("No article with permalink: '%s'" % permalink)
            url = self.request.path_info[1:]
            #logging.info("path: '%s'" % url)
            article = Article.gql("WHERE permalink2 = :1", url).get()
            if article:
                self.redirect(g_root_url + "/" + article.permalink, True)
                return

        if article_only_for_admin(article) and not users.is_current_user_admin():
            return do_404(self.response, url)

        if not article:
            redirect_url = get_redirect(self.request.path_info)
            if redirect_url:
                self.redirect(redirect_url, True)
                return
            return do_404(self.response, url)
        render_article(self.response, article)

class PermanentDeleteHandler(webapp.RequestHandler):
    def get(self):
        assert users.is_current_user_admin()
        article_id = self.request.get("article_id")
        article = Article.get_by_id(int(article_id))
        url = article.permalink
        article.delete()
        clear_memcache()
        #logging.info("Permanently deleted article with id %s" % article_id)
        vals = {
            'article_id' : article_id,
            'url' : url,
        }
        template_out(self.response, "tmpl/articledeleted.html", vals)

class DeleteUndeleteHandler(webapp.RequestHandler):
    def get(self):
        assert users.is_current_user_admin()
        article_id = self.request.get("article_id")
        #logging.info("article_id: '%s'" % article_id)
        article = Article.get_by_id(int(article_id))
        assert article

        if article.is_deleted:
            article.is_deleted = False
        else:
            article.is_deleted = True
        article.put()
        clear_memcache()
        url = "/" + article.permalink
        self.redirect(url)

def gen_permalink(title, id):
    url_base = "article/%s/%s" % (shortenId(id), urlify(title))
    # TODO: maybe use some random number or article.key.id to get
    # to a unique url faster
    iteration = 0
    while iteration < 19:
        permalink = url_base # default, for the case without the title
        if len(title) > 0: permalink = url_base + ".html"
        if iteration > 0: permalink = "%s-%d.html" % (url_base, iteration)
        existing = Article.gql("WHERE permalink = :1", permalink).get()
        if not existing:
            #logging.info("new_permalink: '%s'" % permalink)
            return permalink
        iteration += 1
    return None

def clean_html(html):
    from html2text import html2text
    html = html2text(html)
    assert isinstance(html, unicode)
    return html
    
class ClearMemcacheHandler(webapp.RequestHandler):
    def get(self):
        if not users.is_current_user_admin():
            return self.redirect("/404.html")
        clear_memcache()
        self.response.headers['Content-Type'] = 'text/plain'
        self.response.out.write("memcache cleared")

class CleanHtmlHandler(webapp.RequestHandler):

    def post(self):
        html = self.request.get("note")
        html = clean_html(html)
        self.response.headers['Content-Type'] = 'text/html' # does it matter?
        self.response.out.write(html)

class PreviewHandler(webapp.RequestHandler):

    def post(self):
        format = self.request.get("format")
        body = self.request.get("note")
        assert format in ALL_FORMATS
        html = gen_html_body(format, body)
        self.response.headers['Content-Type'] = 'text/html' # does it matter?
        self.response.out.write(html)

class EditHandler(webapp.RequestHandler):

    def create_new_article(self):
        #logging.info("private: '%s'" % self.request.get("privateOrPublic"))
        #logging.info("format: '%s'" % self.request.get("format"))
        #logging.info("title: '%s'" % self.request.get("title"))
        #logging.info("body: '%s'" % self.request.get("note"))

        format = self.request.get("format")
        assert format in ALL_FORMATS
        title = self.request.get("title").strip()
        body = self.request.get("note")
        (text_content, is_dup) = new_or_dup_text_content(body, format)
        assert not is_dup

        published_on = text_content.published_on
        article = Article(permalink = "tmp", title=title, body=body, format=format)
        article.is_public = not checkbox_to_bool(self.request.get("private_checkbox"))
        article.previous_versions = [text_content.key()]
        article.published_on = published_on
        article.updated_on = published_on
        article.tags = tags_from_string(self.request.get("tags"))
        article.put()
        
        article.permalink = gen_permalink(title, article.key().id())
        assert article.permalink != None
        article.put()

        clear_memcache()
        if article.is_public:
            do_sitemap_ping()
        url = "/" + article.permalink
        self.redirect(url)

    def post(self):
        #logging.info("article_id: '%s'" % self.request.get("article_id"))
        logging.info("private: '%s'" % self.request.get("private_checkbox"))
        #logging.info("format: '%s'" % self.request.get("format"))
        #logging.info("title: '%s'" % self.request.get("title"))
        #logging.info("body: '%s'" % self.request.get("note"))

        if not users.is_current_user_admin():
            return self.redirect("/404.html")

        article_id = self.request.get("article_id")
        if is_empty_string(article_id):
            return self.create_new_article()

        format = self.request.get("format")
        assert format in ALL_FORMATS
        is_public = not checkbox_to_bool(self.request.get("private_checkbox"))
        logging.info("is_public: " + str(is_public))
        update_published_on = checkbox_to_bool(self.request.get("update_published_on"))
        title = self.request.get("title").strip()
        body = self.request.get("note")
        article = db.get(db.Key.from_path("Article", int(article_id)))
        assert article

        tags = tags_from_string(self.request.get("tags"))

        text_content = None
        invalidate_articles_cache = False
        if article.body != body:
            (text_content, is_dup) = new_or_dup_text_content(body, format)
            article.body = body
            #logging.info("updating body")
        else:
            #logging.info("body is the same")
            pass

        if article.title != title:
            new_permalink = gen_permalink(title, article.key().id())
            assert new_permalink
            article.permalink = new_permalink
            invalidate_articles_cache = True

        if text_content:
            article.updated_on = text_content.published_on
        else:
            article.updated_on = datetime.datetime.now()

        if update_published_on:
            article.published_on = article.updated_on
            invalidate_articles_cache = True
    
        if text_content:
            article.previous_versions.append(text_content.key())

        if article.is_public != is_public:
            invalidate_articles_cache = True
        if article.tags != tags: invalidate_articles_cache = True
            
        article.format = format
        article.title = title
        article.is_public = is_public
        article.tags = tags

        if invalidate_articles_cache: clear_memcache()

        article.put()
        if article.is_public:
            do_sitemap_ping()
        self.redirect("/" + article.permalink)

    def get(self):
        if not users.is_current_user_admin(): return self.redirect("/404.html")

        tags = []
        if self.request.get("note") == "yes": tags.append(NOTE_TAG)

        article = None
        article_id = self.request.get('article_id')
        if article_id: article = db.get(db.Key.from_path('Article', int(article_id)))
        permalink = self.request.get('article_permalink')
        if permalink: article = Article.gql("WHERE permalink = :1", permalink).get()

        if not article:
            vals = {
                'format_textile_checked' : 'selected',
                'private_checkbox_checked' : 'checked',
                'submit_button_text' : 'Post',
                'tags' : ','.join(tags)
            }
            template_out(self.response, "tmpl/edit.html", vals)
            return

        vals = {
            'format_textile_checked' : "",
            'format_markdown_checked' : "",
            'format_html_checked' : "",
            'format_text_checked' : "",
            'article' : article,
            'submit_button_text' : "Update post",            
            'tags' : ", ".join(article.tags),
        }
        vals['format_%s_checked' % article.format] = "selected"
        vals['private_checkbox_checked'] = ("" if article.is_public else "checked")
        template_out(self.response, "tmpl/edit.html", vals)

MONTHS = ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December"]

class Year(object):
    def __init__(self, year):
        self.year = year
        self.months = []
    def name(self):
        return self.year
    def add_month(self, month):
        self.months.append(month)

class Month(object):
    def __init__(self, month):
        self.month = month
        self.articles = []
    def name(self):
        return self.month
    def add_article(self, article):
        self.articles.append(article)

def articles_summary_set_tags_display(articles_summary, to_exclude=[]):
    for a in articles_summary:
        tags = a["tags"]
        for tag in to_exclude:
            if tag in tags: tags.remove(tag)
        if tags or len(tags) == 0:
            tags_urls = [url_for_tag(tag) for tag in tags]
            a['tags_display'] = ", ".join(tags_urls)
        else:
            a['tags_display'] = False

# reused by archives and archives-limited-by-tag pages
def do_archives(response, articles_summary, url, tag_to_display=None):
    curr_year = None
    curr_month = None
    years = []
    posts_count = 0
    for a in articles_summary:
        date = a["published_on"]
        y = date.year
        m = date.month
        a["day"] = date.day
        tags = a["tags"]
        if tags:
            tags_urls = [url_for_tag(tag) for tag in tags]
            a['tags_display'] = ", ".join(tags_urls)
        else:
            a['tags_display'] = False
        monthname = MONTHS[m-1]
        if curr_year is None or curr_year.year != y:
            curr_month = None
            curr_year = Year(y)
            years.append(curr_year)

        if curr_month is None or curr_month.month != monthname:
            curr_month = Month(monthname)
            curr_year.add_month(curr_month)
        curr_month.add_article(a)
        posts_count += 1

    vals = {
        'login_out_url' : get_login_logut_url(url),
        'is_admin' : users.is_current_user_admin(),
        'years' : years,
        'tag' : tag_to_display,
        'posts_count' : posts_count,
    }
    template_out(response, "tmpl/archive.html", vals)


# responds to /archives.html
class ArchivesHandler(webapp.RequestHandler):
    def get(self):
        do_archives(self.response, get_articles_summary(), self.request.path)

class SitemapHandler(webapp.RequestHandler):
    def get(self):
        articles = get_articles_summary()
        if not articles: return
        for article in articles[:1000]:
            article["full_permalink"] = self.request.host_url + "/" + article["permalink"]
            article["rfc3339_published"] = to_rfc339(article["published_on"])

        self.response.headers['Content-Type'] = 'text/xml'
        vals = { 
            'articles' : articles,
            'root_url' : self.request.host_url,
        }
        template_out(self.response, "tmpl/sitemap.xml", vals)

# responds to /app/articlesjson and /djs/
class ArticlesJsonHandler(webapp.RequestHandler):
    def get(self):
        (articles_json, sha1) = get_articles_json()
        #logging.info("len(articles_json)=%d" % len(articles_json))
        vals = { 'json' : articles_json, "articles_js_url" : sha1 }
        template_out(self.response, "tmpl/articlesjson.html", vals)

# responds to /app/showdeleted
class ShowDeletedHandler(webapp.RequestHandler):
    def get(self):
        if not users.is_current_user_admin():
            return self.redirect("/404.html")
        do_archives(self.response, get_articles_summary(ARTICLE_DELETED), self.request.path)

# responds to /app/showprivate
class ShowPrivateHandler(webapp.RequestHandler):
    def get(self):
        if not users.is_current_user_admin():
            return self.redirect("/")
        do_archives(self.response, get_articles_summary(ARTICLE_PRIVATE), self.request.path)

class AtomHandlerBase(webapp.RequestHandler):

    def gen_atom_feed(self, include_notes):
        url_path = "/atom.xml"
        if include_notes: url_path = "/atom-all.xml"
        feed = feedgenerator.Atom1Feed(
            title = "Krzysztof Kowalczyk blog",
            link = self.request.host_url + url_path,
            description = "Krzysztof Kowalczyk blog")

        query = Article.gql("WHERE is_public = True AND is_deleted = False ORDER BY published_on DESC")
        count = 0
        for a in query.fetch(200):
            if not include_notes and NOTE_TAG in a.tags: continue
            title = a.title
            link = self.request.host_url + "/" + a.permalink
            article_gen_html_body(a)
            description = a.html_body
            pubdate = a.published_on
            feed.add_item(title=title, link=link, description=description, pubdate=pubdate)
            count += 1
            if count >= 25: break
        feedtxt = feed.writeString('utf-8')
        return feedtxt

    def do_get(self, include_notes=False):

        # TODO: should I compress it?
        key = ATOM_MEMCACHE_KEY
        if include_notes:
            key = ATOM_ALL_MEMCACHE_KEY
        feedtxt = memcache.get(key)
        if not feedtxt:
            feedtxt = self.gen_atom_feed(include_notes)
            memcache.set(key, feedtxt)

        self.response.headers['Content-Type'] = 'text/xml'
        self.response.out.write(feedtxt)

# responds to /atom-all.xml. Returns atom feed of all items, including notes
class AtomAllHandler(AtomHandlerBase):
    def get(self):
        self.do_get(include_notes=True)

# responds to /atom.xml. Returns atom feed of blog items (doesn't include notes)
class AtomHandler(AtomHandlerBase):
    def get(self):
        self.do_get(include_notes=False)

class RedirectHandler(webapp.RequestHandler):
    def get(self):
        new_path = get_redirect(self.request.path)
        if new_path: return self.redirect(new_path)
        self.response.out.write("<html><body>Unknown redirect for %s</body></html>" % self.request.path)

class NotFoundHandler(webapp.RequestHandler):
    def get(self, url):
        new_path = get_redirect(self.request.path)
        if new_path: return self.redirect(new_path)
        do_404(self.response, url)

class AddIndexHandler(webapp.RequestHandler):
    def get(self, sub=None):
        return self.redirect(self.request.url + "index.html")

class ForumRedirect(webapp.RequestHandler):
    def get(self, path):
        new_url = "http://forums.fofou.org/sumatrapdf/" + path
        return self.redirect(new_url)

class ForumRssRedirect(webapp.RequestHandler):
    def get(self):
        return self.redirect("", True)

def user_is_zeniko():
    return users.get_current_user() and users.get_current_user().email() == "zeniko@gmail.com"

def can_view_crash_reports(app=""):
    if users.is_current_user_admin(): return True
    if app == "SumatraPDF": return user_is_zeniko()

def require_login(handler):
    handler.response.headers['Content-Type'] = 'text/html'
    user = users.get_current_user()
    url = handler.request.url
    if user:
        assert not can_view_crash_reports()
        handler.response.out.write("<html><body>You're logged in as %s but this account doesn't have access. <a href=\"%s\">relogin</a></body></html>" % (user.nickname(), users.create_logout_url(url)))
    else:
        handler.response.out.write("<html><body>You need to <a href=\"%s\">log in</a>. </body></html>" % users.create_login_url(url))

mac_apps = ["VisualAck"]
crash_valid_apps = ["SumatraPDF"] + mac_apps

# Stores crash reports from apps
class CrashReports(db.Model):
    created_on = db.DateTimeProperty(required=True, auto_now_add=True)
    ip_addr = db.StringProperty(required=True)
    app_name = db.StringProperty(required=True)
    app_ver = db.StringProperty()
    crashing_line = db.StringProperty()
    data = db.BlobProperty(required=True) # in utf-8 with signature

EMAIL_FROM = "kkowalczyk@gmail.com"
CRASH_REPORT_NOTIFICATION_EMAIL_TO = ["kkowalczyk@gmail.com"]

def extract_sumatra_crashing_line(s):
    # match for crash reports from SumatraPDF before 1.5.1
    match = re.search("Fault address: (.+)", s)
    if None == match:
        # match for crash reports from SumatraPDF since 1.5.1
        match = re.search("Faulting IP: (.+)", s)
    if match:
        parts = match.group(1).split(" ", 2)
        if len(parts) == 3:
            s = parts[2].strip()
            if len(s) > 0: return s
    return None

def extract_crashing_line(app_name, s):
    ver = None
    if app_name == "SumatraPDF":
        ver = extract_sumatra_crashing_line(s)
    if ver is None: ver = ""
    return ver

def extract_sumatra_version(s):
    match = re.search("Ver: (.+)", s)
    if match:
        v = match.group(1).strip()
        if len(v) > 0: return v
    return None

def extract_mac_version(s):
    match = re.search("Version:(.+)", s)
    if match:
        v = match.group(1).strip()
        if len(v) > 0:
            return v.split(" ", 1)[0]
    return None

def extract_app_ver(app_name, s):
    if app_name == "SumatraPDF":
        ver = extract_sumatra_version(s)
    elif app_name in mac_apps:
        ver = extract_mac_version(s)
    if ver is None: ver = ""
    return ver

def shorten_module(s):
    if s.startswith("libmupdf.dll") or s.startswith("sumatrapdf"):
        parts = s.split("!", 1)
        if len(parts) == 2: return parts[1]
    return s

def shorten_src_line(s):
    for src_top_level_dir in ["baseutils\\", "mupdf\\", "ext\\", "src\\"]:
        pos = s.rfind(src_top_level_dir)
        if -1 != pos:
            return s[pos:]
    return s

# Shortens a fault line in format:
# sumatrapdf.exe!BencDict::Encode+0x74 c:\kjk\src\sumatrapdf-1.5\baseutils\bencutil.cpp+201
# by:
# 1. removing sumatrapdf.exe! part if it's our module (sumatrapdf*.exe or libmupdf.dll)
# 2. removing leading path to source code ("c:\kjk\src\sumatrapdf-1.5\")
def shorten_crashing_line(r):
    s = r.crashing_line
    if r.app_name != "SumatraPDF":
        r.short_crashing_line = s
        return
    parts = s.split(" ", 1)
    if len(parts) != 2:
        r.short_crashing_line = s
        return
    module = shorten_module(parts[0])
    if module != parts[0]:
        r.short_crashing_line = s
    src_line = shorten_src_line(parts[1])
    #logging.info("%s => %s" % (parts[1], src_line))
    r.short_crashing_line = module + " " + src_line

def shorten_version(r):
    s = r.app_ver or ""
    r.short_app_ver = s.replace("pre-release ", "pre")


def shorten_crashing_lines(reports):
    for r in reports:
        shorten_crashing_line(r)
        shorten_version(r)

class CrashSubmit(webapp.RequestHandler):
    def post(self):
        ip_addr = os.environ['REMOTE_ADDR']
        app_name = self.request.get("appname")
        crash_data = self.request.get("file")
        crashreport = CrashReports(ip_addr=ip_addr, app_name=app_name, data=crash_data)
        crashreport.app_ver = extract_app_ver(app_name, crash_data)
        crashreport.crashing_line = extract_crashing_line(app_name, crash_data)
        crashreport.put()
        report_url = my_hostname() + "/app/crashes/" + str(crashreport.key().id())
        self.response.out.write(report_url)
        s = unicode(crash_data, 'utf-8-sig')
        body = report_url + "\n" + s
        subject = "New crash report"
        mail.send_mail(sender=EMAIL_FROM,
            to=CRASH_REPORT_NOTIFICATION_EMAIL_TO,
            subject=subject,
            body=body)

def crash_list_url(app):
    if app and len(app) > 0: return "/app/crashes/" + app
    return "/app/crashes/"

class CrashDelete(webapp.RequestHandler):
    def get(self, key):
        if not can_view_crash_reports():
            return require_login(self)
        report = db.get(db.Key.from_path('CrashReports', int(key)))
        report.delete()
        self.redirect(crash_list_url(report.app_name))

class CrashShow(webapp.RequestHandler):
    def get(self, key):
        report = db.get(db.Key.from_path('CrashReports', int(key.strip())))
        ip_addr = os.environ['REMOTE_ADDR']
        if ip_addr != report.ip_addr and not can_view_crash_reports(report.app_name):
            return require_login(self)
        tvals = {
            'all_url' : crash_list_url(report.app_name),
            'report' : report,
            'report_body' : unicode(report.data, 'utf-8-sig').strip()
        }
        template_out(self.response, "tmpl/crash_report.html", tvals)

MAX_REPORTS = 50

def update_report(r):
    if (r.app_ver is not None) and (r.crashing_line is not None):
        return False
    crash_data = r.data
    r.app_ver = extract_app_ver(r.app_name, crash_data)
    r.crashing_line = extract_crashing_line(r.app_name, crash_data)
    r.put()
    #logging.info("updated report %s with app_ver: '%s', crashing_line: '%s'" % (str(r.key().id()), r.app_ver, r.crashing_line))
    return True

# This should be only needed temporarily, until existing crash reports are converted
def update_app_ver_and_crash_line(reports, app_name):
    any_changed = False
    for r in reports:
        changed = update_report(r)
        if changed:
            any_changed = True

    if any_changed:
        reports = CrashReports.gql("WHERE app_name = '%s' ORDER BY created_on DESC" % app_name).fetch(MAX_REPORTS)
    return reports

class Crashes(webapp.RequestHandler):
    def show_index(self):
        if not can_view_crash_reports(True):
            return require_login(self)
        user_email = None
        user = users.get_current_user()
        if user: user_email = user.email()
        tvals = {
            'user_email' : user_email,
            'logout_url' : users.create_logout_url(self.request.url),
            'apps' : crash_valid_apps
        }
        template_out(self.response, "tmpl/crash_reports_index.html", tvals)

    def list_recent(self, app_name):
        if not can_view_crash_reports(app_name):
            return require_login(self)
        reports = CrashReports.gql("WHERE app_name = '%s' ORDER BY created_on DESC" % app_name).fetch(MAX_REPORTS)
        reports = update_app_ver_and_crash_line(reports, app_name)
        shorten_crashing_lines(reports)
        user_email = None
        user = users.get_current_user()
        if user: user_email = user.email()
        tvals = {
            'reports' : reports,
            'user_email' : user_email,
            'logout_url' : users.create_logout_url(self.request.url),
            'app_name' : app_name
        }
        template_out(self.response, "tmpl/crash_reports_list.html", tvals)

    def get(self, key):
        # redirect the old version of this url
        if -1 != self.request.url.find("/app/sumatracrashes/"):
            return self.redirect("/app/crashes/SumatraPDF")
        app_name = key.strip()
        if app_name not in crash_valid_apps:
            return self.show_index()
        self.list_recent(app_name)

def main():
    mappings = [
        ('/', IndexHandler),
        ('/index.html', IndexHandler),
        ('/archives.html', ArchivesHandler),
        ('/article/(.*)', ArticleHandler),
        ('/notes/(.*)', NotesHandler),
        ('/page/(.*)', PageHandler),
        # /kb/ and /blog/ are for redirects from old website
        ('/kb/(.*)', ArticleHandler),
        ('/blog/(.*)', ArticleHandler),
        ('/tag/(.*)', TagHandler),
        ('/djs/(.*)', JsHandler),
        ('/atom-all.xml', AtomAllHandler),
        ('/feedburner.xml', AtomHandler),
        ('/sitemap.xml', SitemapHandler),
        ('/software/(.+)/', AddIndexHandler),
        ('/forum_sumatra/(.*)', ForumRedirect),
        ('/app/edit', EditHandler),
        ('/app/undelete', DeleteUndeleteHandler),
        ('/app/delete', DeleteUndeleteHandler),
        ('/app/permanentdelete', PermanentDeleteHandler),
        ('/app/showprivate', ShowPrivateHandler),
        ('/app/showdeleted', ShowDeletedHandler),
        #('/app/articlesjson', ArticlesJsonHandler), # for testing
        ('/app/preview', PreviewHandler),
        ('/app/cleanhtml', CleanHtmlHandler),
        ('/app/clearmemcache', ClearMemcacheHandler),
        ('/app/crashsubmit', CrashSubmit),
        ('/app/sumatracrashes/(.*)', Crashes),
        ('/app/crashes/(.*)', Crashes),
        ('/app/crashshow/(.*)', CrashShow),
        ('/app/crashdelete/(.*)', CrashDelete),
        ('/(.*)', NotFoundHandler)
    ]
    app = webapp.WSGIApplication(mappings,debug=True)
    app = redirect_from_appspot(app)
    app = remember_root_url(app)
    wsgiref.handlers.CGIHandler().run(app)

if __name__ == "__main__":
  main()
