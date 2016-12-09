# -*- coding: utf-8 -*-

from bs4 import BeautifulSoup
import re
import robotparser
import sys


CRITICAL = 0
ERROR = 1
WARN = 2
INFO = 3

levels = (
    'critical',
    'error',
    'warning',
    'info',
)

html_parser = "lxml"
# html_parser = "html.parser"

stop_words = {
    'en': ('a', 'an', 'and', 'are', 'as', 'at', 'be', 'by', 'for', 'that',
           'from', 'has', 'he', 'in', 'is', 'it', 'its', 'of', 'on', 'the',
           'to', 'was', 'were', 'will', 'with'),
    'fr': (# determinants
           'un', 'une', 'le', 'la', 'les', 'au', 'aux', 'du', 'des', 'mon',
           'ma', 'mes', 'ton', 'ta', 'tes', 'son', 'sa', 'ses', 'notre',
           'nos', 'votre', 'vos', 'leur', 'leurs', 'ce', 'cet', 'cette', 'ces',
           'aucun', 'chaque', 'nul', 'plusieurs', 'quelques', 'certains',
           # pronoms
           'je', 'tu', 'il', 'elle', 'nous', 'vous', 'ils', 'elles',
           # preposition
           'sur', 'sous', 'entre', 'devant', 'derrière', 'dans', 'chez',
           'avant', 'après', 'vers', 'depuis', 'pendant', 'pour',
           'vers', 'à', 'de', "jusqu'à", "jusqu'au", 'de', 'par', 'plus',
           # verbs
           'est', 'a', 'sont',
           # others
           'que')
}

rules = [
    # for html
    ('C22', 'head is missing', CRITICAL),
    # ('E01', 'is utf8', ERROR),
    ('E02', 'title is missing', ERROR),
    ('E05', 'meta description is missing', ERROR),
    ('E08', 'canonical is missing', ERROR),
    ('E09', 'heading (h1) is missing', ERROR),
    ('E12', 'title matches less then one (1) word of heading (h1)', ERROR),
    ('E13', 'title matches less then one (1) word of meta description', ERROR),
    ('E17', 'too many outlinks on page (more then 1k)', ERROR),
    ('W03', 'title is too long (more then 70 chars)', WARN),
    # ('W04', 'duplicate title', WARN),
    ('W06', 'meta description is too long (more then 150 chars)', WARN),
    # ('W07', 'duplicate meta description', WARN),
    ('W35', 'meta description is too short (less then 50 chars)', WARN),
    ('W14', 'title matches less then three (3) heading (h1) words', WARN),
    ('W15', 'title matches less then three (3) meta description words', WARN),
    ('W16', 'too many outlinks on page (more then 300)', WARN),
    ('W18', 'page size is greater then 200K', WARN),
    ('W19', 'missing `alt` on image tags', WARN),
    ('E34', 'too many heading (h1)', ERROR),
    ('W24', 'heading structure is broken', WARN),
    ('I10', 'missing rel=prev - only needed for paginated archives', INFO),
    ('I11', 'missing rel=next - only needed for paginated archives', INFO),
    ('I20', 'has robots=nofollow', INFO),
    ('I21', 'has robots=noindex', INFO),
    ('C36', 'invalid HTTP response code - broken link', CRITICAL),
    ('E37', 'page moved permanently - original page should use canonical URL', ERROR),
    

    # for robots.txt
    ('C23', 'has sitemap', CRITICAL),
    ('I24', 'has disallow', INFO),
    ('I25', 'has user-agent', INFO),

    # for sitemap index
    ('C26', 'is valid xml', CRITICAL),
    ('C27', 'has locs', CRITICAL),
    ('E33', '<1000 locs in index', ERROR),

    # for sitemap urlset
    ('I30', 'has priority', INFO),
    ('I31', 'has changefreq', INFO),
    ('I32', 'has lastmod', INFO),
]

def get_rules():
    return rules

def parse_html(html):
    soup = BeautifulSoup(html, html_parser)

    if not soup.find('head'):
        return {
            'head': False
        }

    robots = soup.find('head').find('meta', attrs={"name":"robots"})
    title = soup.title.get_text() if soup.title else unicode(soup.find('title'))
    h1s = soup.find_all('h1')
    h = [bool(soup.find('h%s' % i)) for i in range(1, 7)]
    meta_description = soup.find('head').find('meta', attrs={"name":"description"})

    return {
        'head': soup.find('head'),
        'title': title,
        'title_keywords': extract_keywords(title),
        'canonical': soup.find('head').find('link', attrs={"rel":"canonical"}),
        'next': soup.find('head').find('link', attrs={"rel":"next"}),
        'prev': soup.find('head').find('link', attrs={"rel":"prev"}),
        'robots': robots.get("content") if robots else None,
        'meta_description': meta_description,
        'meta_description_keywords':
            extract_keywords(meta_description.get('content')) if meta_description else [],
        'h1s': h1s,
        'h1_count': len(h1s),
        'h1_keywords': extract_keywords(h1s[0].get_text()) if h1s else [],
        'h1': h[0],
        'h2': h[1],
        'h3': h[2],
        'h4': h[3],
        'h5': h[4],
        'h6': h[5],
        # 'text_only': soup.get_text(),
        'links': soup.find_all('a'),
        'link_count': len(soup.find_all('a')),
        'meta_tags': soup.find('head').find_all('meta'),
        'images': soup.find_all('img'),
        'size': len(html),
    }

def parse_sitemap(xml):
    soup = BeautifulSoup(xml, html_parser)

    if soup.find('sitemapindex'):
        return ('index', _parse_sitemapindex(soup))
    elif soup.find('urlset'):
        return ('urlset', _parse_sitemapurlset(soup))
    else:
        raise Exception('invalid sitemap')

def _parse_sitemapurlset(soup):
    # find all the <url> tags in the document
    urls = soup.findAll('url')

    # no urls? bail
    if not urls:
        return False

    # storage for later...
    out = []

    # extract what we need from the url
    for u in urls:
        out.append({
            'loc': u.find('loc').string if u.find('loc') else None,
            'priority': u.find('priority').string if u.find('priority') else None,
            'changefreq': u.find('changefreq').string if u.find('changefreq') else None,
            'lastmod': u.find('lastmod').string if u.find('lastmod') else None,
            })
    return out

def _parse_sitemapindex(soup):
    # find all the <url> tags in the document
    sitemaps = soup.findAll('sitemap')

    # no sitemaps? bail
    if not sitemaps:
        return False

    # storage for later...
    out = []

    # extract what we need from the url
    for u in sitemaps:
        out.append({
            'loc': u.find('loc').string if u.find('loc') else None
            })
    return out

# Example sitemap
'''
# Tempest - biography

User-agent: *
Disallow: /search

Sitemap: http://www.biography.com/sitemaps.xml
'''
def parse_robots_txt(txt):
    # TODO: handle disallows per user agent
    sitemap = re.compile("Sitemap:\s+(.+)").findall(txt)
    disallow = re.compile("Disallow:\s+(.+)").findall(txt)
    user_agent = re.compile("User-agent:\s+(.+)").findall(txt)
    return {
        'sitemap': sitemap,
        'disallow': disallow,
        'user_agent': user_agent
    }

def extract_keywords(text, min_word_size=3, lang='en'):
    # We probably don't care about words shorter than 3 letters
    pattern = re.compile(u'\W', re.UNICODE)
    text = unicode(text)
    if text:
        return [kw.lower()
            for kw in pattern.sub(u' ', text).split()
            if kw not in stop_words.get(lang, []) and len(kw) >= min_word_size]
    else:
        return []

def word_match_count(a, b):
    count = 0
    for word1 in a:
        for word2 in b:
            if word1 == word2:
                count = count + 1
    return count


def lint(resp):
    """
    Run lint on HTTP Response.
    """
    # Run html lint on html content
    if resp['content_type'] == 'text/html':
        return lint_html(resp)
    
    return {}
    

def lint_html(html_string, level=INFO):
    # First parameter may be a HTTP response. Try to get it.
    try:
        resp = html_string
        html_string = html_string.get('content')
    except:
        resp = None
        pass
        
    output = {}

    p = parse_html(html_string)

    # stop and return on critical errors
    if not p['head']:
        output['C22'] = True
        return output

    if resp and resp['code'] == 301:
        output['E37'] = True
        return output

    # Dont' parse 302 pages
    if resp and resp['code'] == 302:
        return output

    if resp and resp['code'] not in [200, 302]:
        output['C36'] = resp['code']
        return output

    if not p['title']:
        output['E02'] = True
    elif len(p['title']) > 70:
        output['W03'] = len(p['title'])

    if not p['meta_description'] or not p['meta_description'].get("content"):
        output['E05'] = True
    elif len(p['meta_description'].get('content')) > 150:
        output['W06'] = len(p['meta_description'].get('content'))
    elif len(p['meta_description'].get('content')) < 50:
        output['W35'] = len(p['meta_description'].get('content'))

    if not p['canonical']:
        output['E08'] = True

    if not p['h1']:
        output['E09'] = True

    # Disable rel=next and rel=prev verification since we cannot detect pagination.
    #if not p['next']:
    #    output['I10'] = True
    #if not p['prev']:
    #    output['I11'] = True

    if p['link_count'] >= 300:
        output['W16'] = p['link_count']

    if p['link_count'] >= 1000:
        output['E17'] = p['link_count']

    if p['size'] >= 200 * 1024:
        output['E18'] = p['size']

    if p['robots'] and "nofollow" in p['robots']:
        output['I20'] = p['robots']

    if p['robots'] and "noindex" in p['robots']:
        output['I21'] = p['robots']

    if p['h1_count'] > 1:
        output['E34'] = p['h1_count']
        
    if (p['h1'] < p['h2'] or
            p['h2'] < p['h3'] or
            p['h3'] < p['h4'] or
            p['h4'] < p['h5'] or
            p['h5'] < p['h6']):
        output['W24'] = [p['h1'], p['h2'], p['h3'], p['h4'], p['h5'], p['h6']]

    if word_match_count(p['title_keywords'], p['h1_keywords']) < 1:
        output['E12'] = (word_match_count(p['title_keywords'], p['h1_keywords']), p['title_keywords'], p['h1_keywords'])

    if word_match_count(p['title_keywords'], p['meta_description_keywords']) < 1:
        output['E13'] = (word_match_count(p['title_keywords'], p['meta_description_keywords']), p['title_keywords'], p['meta_description_keywords'])

    if len(p['title_keywords']) >= 3 and word_match_count(p['title_keywords'], p['h1_keywords']) < 3:
        output['W14'] = (word_match_count(p['title_keywords'], p['h1_keywords']), p['title_keywords'], p['h1_keywords'])

    if len(p['title_keywords']) >= 3 and word_match_count(p['title_keywords'], p['meta_description_keywords']) < 3:
        output['W15'] = (word_match_count(p['title_keywords'], p['meta_description_keywords']), p['title_keywords'], p['meta_description_keywords'])

    images_missing_alt = []
    for image in p['images']:
        if not image.get("alt"):
            images_missing_alt.append(image)

    if len(images_missing_alt) > 0:
        output['W19'] = len(images_missing_alt)

    # remove rules below level requested
    if level < INFO:
        for rule in rules:
            for key, value in output.iteritems():
                if rule[2] < level:
                    output[key].remove()

    return output

def lint_sitemap(xml_string, level=INFO):
    output = {}

    try:
        p = parse_sitemap(xml_string)
    except Exception, e:
        output['C26'] = True
        return output

    if p[0] == 'index':
        output = _lint_sitemapindex(p[1])
    elif p[0] == 'urlset':
        output = _lint_sitemapurlset(p[1])
    else:
        output['C26'] = True
        return output

    # remove rules below level requested
    if level < INFO:
        for rule in rules:
            for key, value in output.iteritems():
                if rule[2] < level:
                    output[key].remove()

    return output

def _lint_sitemapindex(p):
    output = {}

    if not p or len(p) == 0:
        output['C27'] = True
        return output

    if not len(p) < 10000:
        output['E33'] = True

    return output

def _lint_sitemapurlset(p):
    output = {}

    if not p or len(p) == 0:
        output['C27'] = True
        return output

    if not len(p) < 10000:
        output['E33'] = True

    for url in p:
        if url['priority']:
            output['I30'] = True
        if url['changefreq']:
            output['I31'] = True
        if url['lastmod']:
            output['I32'] = True

    return output

def lint_robots_txt(txt_string, level=INFO):
    output = {}

    p = parse_robots_txt(txt_string)

    # stop and return on critical errors
    if not p['sitemap']:
        output['C23'] = True
        return output

    if not p['disallow']:
        output['I24'] = True

    if not p['user_agent']:
        output['I25'] = True

    # remove rules below level requested
    if level < INFO:
        for rule in rules:
            for key, value in output.iteritems():
                if rule[2] < level:
                    output[key].remove()

    return output
