# -*- coding: utf-8 -*-

import atexit
from bs4 import BeautifulSoup
import datetime
import gzip
import hashlib
import json
import os
import re
import requests
import sys
import time
from urlparse import urlparse, urljoin
import uuid

from mozscape import Mozscape
import seolinter


html_parser = "lxml"
# html_parser = "html.parser"

TIMEOUT = 16

def crawl(urls, db, internal=False, delay=0, user_agent=None,
    url_associations={}, run_id=None, processed_urls={}, limit=0,
    moz_accessid=None, moz_secretkey=None):

    run_id = run_id or uuid.uuid4()
    print "Starting crawl with run_id: %s" % run_id

    run_count = 0
    limit_reached = False
    while len(urls) > 0:
        run_count += 1
        url = urls[0]

        print "\nProcessing (%d / %d): %s" % (run_count, len(urls), url)
        if not is_full_url(url):
            urls.pop(0)
            processed_urls[url] = 0
            continue
            # raise ValueError('A relative url as provided: %s. Please ensure that all urls are absolute.' % url)

        processed_urls[url] = None

        results = retrieve_url(url, user_agent)

        for res in results:

            lint_errors, page_details, links, sources = process_html(res)
            
            moz_data = retrieve_mozrank(res['url'], moz_accessid, moz_secretkey)

            record = store_results(db, run_id, res, lint_errors, page_details, moz_data)
            processed_urls[url] = record
            url_associations.setdefault(url, {})

            # Process links from the page
            if links and len(links) > 0:
                for link in links:
                    link_url = link['url']

                    if not link['valid']:
                        # Process any malformed links
                        bad_link = store_results(db, run_id, {
                            'url': link_url,
                            'code': 0,
                            }, {}, {}, external=None)
                        processed_urls[link_url] = bad_link
                        associate_link(db, record, bad_link, run_id, 'anchor', link.get('text'), link.get('alt'), link.get('rel'))
                    elif not is_internal_url(link_url, url):
                        # Process all external links and create the
                        if link_url not in processed_urls:
                            link_results = retrieve_url(link_url, user_agent, False)

                            for link_result in link_results:
                                link_store = store_results(db, run_id, link_result, {}, {}, external=True)
                                processed_urls[link_result['url']] = link_store

                                # Associate links
                                associate_link(db, record, link_store, run_id, 'anchor', link.get('text'), link.get('alt'), link.get('rel'))
                        else:
                            associate_link(db, record, processed_urls[link_url], run_id, 'anchor', link.get('text'), link.get('alt'), link.get('rel'))

                    elif internal and is_internal_url(link_url, url) and link_url not in processed_urls and link_url not in urls:
                        if not limit_reached:
                            urls.append(link_url)
                            if limit and len(urls) >= limit:
                                limit_reached = True
                        url_associations[url][link_url] = link

            # Process sources from the page
            if sources and len(sources) > 0:
                for source in sources:
                    source_url = source['url']

                    if source_url not in processed_urls:
                        source_results = retrieve_url(source_url, user_agent, False)

                        for source_result in source_results:
                            source_internal = is_internal_url(source_result['url'], url)
                            source_store = store_results(db, run_id, source_result, {}, {}, external=not source_internal)
                            processed_urls[source_url] = source_store
                            associate_link(db, record, source_store, run_id, 'asset', None, source.get('alt'), None)

                    else:
                        associate_link(db, record, processed_urls[source_url], run_id, 'asset', None, source.get('alt'), None)


        time.sleep(delay / 1000.0)
        urls.pop(0)

    # Process associations
    for url, associations in url_associations.iteritems():
        for association, link in associations.iteritems():
            to_id = processed_urls.get(url)
            from_id = processed_urls.get(association)
            if to_id and from_id and from_id != to_id:
                associate_link(db, to_id, from_id, run_id, 'anchor', link.get('text'), link.get('alt'), link.get('rel'))

    return run_id


def retrieve_mozrank(url, accessid, secret_key):
    # if access id or secret is not provided, don't query Mozscape metrics.
    # https://moz.com/help/guides/moz-api/mozscape/api-reference/url-metrics
    if not accessid or not secret_key:
        return {}
    # If URL is local, skip it too.
    client = Mozscape(accessid, secret_key)
    for i in range(0, 3):
        try:
            return client.urlMetrics([url])[0]
        except Exception as e:
            print("mozscape failed trial %s: %s (%s)" % (i, url, str(e)))
            time.sleep(11)
    return {}


def retrieve_url(url, user_agent=None, full=True):

    def _build_payload(response, request_time):
        # Since alot of server doesn't report Content-Type with proper
        # encoding, have a look at content, then use default encoding.
        charset_re = re.compile(r'<meta.*?charset=["\']*(.+?)["\'>]', flags=re.I)
        pragma_re = re.compile(r'<meta.*?content=["\']*;?charset=(.+?)["\'>]', flags=re.I)
        xml_re = re.compile(r'^<\?xml.*?encoding=["\']*(.+?)["\'>]')
        encoding = (charset_re.findall(response.content) or
            pragma_re.findall(response.content) or
            pragma_re.findall(response.content) or
            xml_re.findall(response.content) or 
            [response.encoding])[0]
        response.encoding = encoding 
        
        size = response.headers.get('content-length') or len(response.text)
        content_type = response.headers.get('content-type')
        
        return {
            'url': response.url,
            'url_length': len(response.url),
            'content': response.text,
            'content_type': content_type.split(';')[0] if content_type else None,
            'code': int(response.status_code),
            'reason': response.reason,
            'size': size,
            'encoding': encoding,
            'response_time': request_time,
        }

    headers = {}
    redirects = []
    if user_agent:
        headers['User-Agent'] = user_agent
        if 'Googlebot' in user_agent:
            # TODO: append ?__escaped_fragment__= to the url
            pass

    try:
        sys.stdout.write("\033[K")
        sys.stdout.write(" -> %s\r" % url)
        sys.stdout.flush()

        start = time.time()
        res = requests.head(url, headers=headers, timeout=TIMEOUT)

        if full and res.headers.get('content-type', '').split(';')[0] == 'text/html':
            res = requests.get(url, headers=headers, timeout=TIMEOUT)

        if len(res.history) > 0:
            request_time = 0
            redirects = [_build_payload(redirect, request_time) for redirect in res.history]

    except requests.exceptions.Timeout, e:
        return [{
            'url': url,
            'url_length': len(url),
            'code': 0,
            'reason': 'Timeout %s' % TIMEOUT
            }]
    except requests.exceptions.ConnectionError, e:
        return [{
            'url': url,
            'url_length': len(url),
            'code': 0,
            'reason': 'Connection Error %s' % e
            }]
    except Exception, e:
        print e
        raise
    finally:
        request_time = time.time() - start
        # TODO: Properly handle the failure. reraise?

    return [_build_payload(res, request_time), ] + redirects


def process_html(res):
    
    html = res['content']
    url = res['url']

    lint_errors = seolinter.lint(res)

    page_details = extract_page_details(html, url)

    links = extract_links(html, url)

    sources = extract_sources(html, url)

    return lint_errors, page_details, links, sources


def extract_links(html, url):
    links = []
    soup = BeautifulSoup(html, html_parser)

    for a_tag in soup.find_all('a'):
        valid = True
        try:
            full_url = make_full_url(a_tag.get('href'), url)
        except Exception:
            full_url = a_tag.get('href')
            valid = False

        if full_url and 'mailto:' not in full_url:  # Ignore any a tags that don't have an href
            links.append({
                'url': full_url,
                'valid': valid,
                'text': a_tag.string or a_tag.get_text(),
                'alt': a_tag.get('alt'),
                'rel': a_tag.get('rel'),
                })

    return links


def extract_sources(html, url):
    sources = []

    soup = BeautifulSoup(html, html_parser)
    links = soup.find_all(['img', 'link', 'script', 'style', 'meta'])

    for link in links:
        source_url = link.get('src') or link.get('href')
        if not source_url:
            continue
        source_url = source_url.strip()
        if not is_full_url(source_url):
            full_url = make_full_url(source_url, url)
        else:
            full_url = source_url
        sources.append({
            'url': full_url,
            'alt': link.get('alt'),
            })

    return sources


def extract_page_details(html, url):
    soup = BeautifulSoup(html, html_parser)

    if not soup.find('head'):
        return {}

    robots = soup.find('head').find('meta', attrs={"name":"robots"})
    rel_next = soup.find('head').find('link', attrs={'rel':'next'})
    rel_prev = soup.find('head').find('link', attrs={'rel':'prev'})
    title = soup.title.get_text() if soup.title else unicode(soup.find('title'))
    meta_description = soup.find('head').find('meta', attrs={"name":"description"})
    canonical = soup.find('head').find('link', attrs={"rel":"canonical"})
    h1_1 = soup.find('h1')
    h1_2 = soup.find_all('h1')[1] if len(soup.find_all('h1')) > 1 else None
    lang = soup.find('html').get('lang', None)
    keywords = extract_all_keywords(soup, url, lang)

    return {
        'size': len(html),
        'canonical': canonical.get("href") if canonical else None,
        'title_1': title,
        'title_length_1': len(title),
        'meta_description_1': meta_description.get("content") if meta_description else None,
        'meta_description_length_1': len(meta_description) if meta_description else 0,
        'h1_1': h1_1.get_text() if h1_1 else None,
        'h1_length_1': len(h1_1.get_text()) if h1_1 else 0,
        'h1_2': h1_2.get_text() if h1_2 else None,
        'h1_length_2': len(h1_2.get_text()) if h1_2 else 0,
        'h1_count': len(soup.find_all('h1')),
        'meta_robots': robots.get("content") if robots else None,
        'rel_next': rel_next.get("href") if rel_next else None,
        'rel_prev': rel_prev.get('href') if rel_prev else None,
        'keywords': keywords,
        'lang': lang,
    }

def extract_all_keywords(soup, url, lang):
    
    def visible(element):
        if element.parent.name in ['style', 'script']:
            return False
        elif element.__class__.__name__ in ['Comment']:
            return False
        elif not unicode(element).strip():
            return False
        return True
    
    def parent_tag(element):
        important_tags = ['title', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6', 'footer', 'a', 'b', 'img']
        while element.parent is not None:
            if element.parent.name in important_tags:
                return element.parent.name
            element = element.parent
        return 'default'
    
    def append_keywords(keywords, loc, text, lang):
        for word in seolinter.extract_keywords(text, lang=lang):
            count = keywords.setdefault(word, {}).setdefault(loc, 0)
            keywords[word][loc] = count + 1
    
    # Include keyword from all text
    keywords = {}
    for element in filter(visible, soup.findAll(text=True)):
        tag = parent_tag(element)
        append_keywords(keywords, tag, element, lang)

    # Include keyword from meta description
    meta_description = soup.find('head').find('meta', attrs={"name":"description"})
    append_keywords(keywords, 'meta.description', meta_description, lang)
    
    # Include keyword from meta keywords
    meta_keywords = soup.find('head').find('meta', attrs={"name":"keywords"})
    append_keywords(keywords, 'meta.keywords', meta_keywords, lang)
    
    # Include keyword from img:alt
    for img in soup.findAll("img"):
        if img.alt:
            append_keywords(keywords, 'img', img.alt, lang)
    
    # Include keyword in URL.
    append_keywords(keywords, 'url', url, lang)
    
    # Sum
    for word in keywords.keys():
        keywords[word]['total'] = sum(keywords[word].values())    
    
    return keywords


def store_results(db, run_id, stats, lint_errors, page_details, moz_data={}, external=False, valid=True):
    cur = db.cursor()

    def prepare_sql(param):
        fields = ', '.join(['`%s`' % k for k in param.keys()])
        values = ', '.join(['%s'] * len(param))
        return 'INSERT INTO `crawl_urls` ( `level`, `timestamp`, %s) VALUES ( 0, NOW(), %s)' % (fields, values) 

    try:
        url = stats.get('url')
        content = stats.get('content', '')
        content_hash = hashlib.sha256(content.encode('ascii', 'ignore')).hexdigest()
        lint_keys = [k.upper() for k in lint_errors.keys()]
        try:
            lint_res = json.dumps(lint_errors)
        except:
            lint_res = '[]'
        s = int(stats.get('size', 0))
        param = {
            'run_id': run_id,
            'content_hash': content_hash if content else None,

            # request data
            'address': stats.get('url'),
            'domain': _get_base_url(url) if valid else None,
            'path': _get_path(url) if valid else None,
            'external': 1 if external else 0,
            'status_code': stats.get('code'),
            'status': stats.get('reason'),
            'body': stats.get('content', ''),
            'size': s if s >= 0 else 0,
            'address_length': len(url),
            'encoding': stats.get('encoding'),
            'content_type': stats.get('content_type'),
            'response_time': stats.get('response_time'),
            'redirect_uri': None,
            'canonical': page_details.get('canonical'),

            # parse data
            'title_1': page_details.get('title_1'),
            'title_length_1': page_details.get('title_length_1'),
            'title_occurences_1': page_details.get('title_occurences_1'),
            'meta_description_1': page_details.get('meta_description_1'),
            'meta_description_length_1': page_details.get('meta_description_length_1'),
            'meta_description_occurrences_1': page_details.get('meta_description_occurrences_1'),
            'h1_1': page_details.get('h1_1'),
            'h1_length_1': page_details.get('h1_length_1'),
            'h1_2': page_details.get('h1_2'),
            'h1_length_2': page_details.get('h1_length_2'),
            'h1_count': page_details.get('h1_count'),
            'meta_robots': page_details.get('meta_robots'),
            'rel_next': page_details.get('rel_next'),
            'rel_prev': page_details.get('rel_prev'),
            'lang': page_details.get('lang'),
            'keywords': json.dumps(page_details.get('keywords')),

            # lint data
            'lint_critical': len([l for l in lint_keys if l[0] == 'C']),
            'lint_error': len([l for l in lint_keys if l[0] == 'E']),
            'lint_warn': len([l for l in lint_keys if l[0] == 'W']),
            'lint_info': len([l for l in lint_keys if l[0] == 'I']),
            'lint_results': json.dumps(lint_errors),
            
            # moz data
            'moz_upa': moz_data.get('upa', 0),
            'moz_pda': moz_data.get('pda', 0),
            'moz_ulc': datetime.datetime.fromtimestamp(moz_data.get('ulc', 0)),
            'moz_umrp': moz_data.get('umrp', 0),
            'moz_ueid': moz_data.get('ueid', 0),
            'moz_uid': moz_data.get('uid', 0),
        }
        cur.execute(prepare_sql(param), param.values())
        db.commit()
    except:
        db.rollback()
        raise

    return cur.lastrowid


def is_internal_url(url, source_url):
    if is_full_url(url):
        base_url = _get_base_url(url)
        base_source_url = _get_base_url(source_url)
        return (
            base_url == base_source_url
            or (len(base_url) > len(base_source_url) and base_source_url == base_url[-len(base_source_url):])
            or (len(base_source_url) > len(base_url) and base_url == base_source_url[-len(base_url):])
            )
    else:
        return True

def is_full_url(url):
    """Check if the url is valid."""
    link_re = re.compile(r'^(http(s)?:\/\/[a-zA-Z0-9\-_]+)+')
    return True if link_re.match(url) else False


def make_full_url(url, source_url):
    full = urljoin(source_url, url)
    return full.split('#')[0]


def associate_link(db, from_url_id, to_url_id, run_id, link_type, text, alt, rel):
    if not from_url_id or not to_url_id or not run_id:
        print "Failed to save association (From:", from_url_id, "To:", to_url_id, ")"
        return False

    cur = db.cursor()

    association = '''
INSERT INTO `crawl_links` (
  `run_id`, `type`, `from_url_id`, `to_url_id`, `link_text`, `alt_text`, `rel`)
 VALUES (%s, %s, %s, %s, %s, %s, %s)
    '''

    try:
        cur.execute(association, (
            run_id,
            link_type,
            from_url_id,
            to_url_id,
            text.encode('ascii', 'ignore') if text else None,
            alt.encode('ascii', 'ignore') if alt else None,
            rel,
            ))
        db.commit()
    except:
        db.rollback()
        raise

    return db.insert_id()

def _get_base_url(url):
    try:
        res = urlparse(url)
        return res.netloc
    except:
        return None

def _get_path(url):
    base = _get_base_url(url)
    parts = url.split(base)
    return parts[-1]
