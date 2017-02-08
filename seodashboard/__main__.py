#!/usr/bin/env python
# -*- coding: utf-8 -*-

# Usage:
# python seodashboard/main.py

from flask import Flask, render_template, request, redirect
from flask_mysqldb import MySQL
import json
import optparse
import yaml

import seolinter


app = Flask(__name__, template_folder='.', static_folder='static', static_url_path='/static')
db = MySQL()

default_page_length = 50

lint_desc = {t[0]: t[1] for t in seolinter.rules}
lint_level = {t[0]: t[2] for t in seolinter.rules}

def delete_run(run_id):
    conn = db.connection
    c = conn.cursor()
    try:
        c.execute('DELETE FROM crawl_urls WHERE run_id = %s', [run_id])
        conn.commit()
    except:
        conn.rollback()
        raise

def fetch_latest_run_id():
    run_id = None
    c = db.connection.cursor()
    c.execute('SELECT run_id FROM crawl_urls ORDER BY timestamp DESC LIMIT 1')
    result = c.fetchone()
    if result:
        run_id = result[0]
    return run_id


def fetch_run(run_id, page=1, page_length=default_page_length, lint=None, order_by=None, order_by_asc=1):
    lint = '%%%s%%' % lint if lint else '%'
    c = db.connection.cursor()
    start = (page - 1) * page_length
    # Define the ordering
    order_by_sql = 'ORDER BY lint_critical DESC, lint_error DESC, lint_warn DESC, lint_info DESC'
    if order_by is not None:
        order_by_sql = 'ORDER BY %s %s' % (order_by, 'ASC' if order_by_asc else 'DESC')
    
    c.execute('SELECT * FROM crawl_urls WHERE run_id = %s AND external = 0 AND lint_results LIKE %s ' + order_by_sql + ' LIMIT %s, %s',
        [run_id, lint, start, page_length])
    return cols_to_props(c)


def fetch_run_stats(run_id):
    c = db.connection.cursor()
    c.execute('SELECT COUNT(id) AS count, SUM(lint_critical) AS lint_critical, SUM(lint_error) AS lint_error, SUM(lint_warn) AS lint_warn, SUM(lint_info) AS lint_info FROM crawl_urls WHERE run_id = %s', [run_id])
    return cols_to_props(c)[0]


def fetch_run_ids():
    c = db.connection.cursor()
    c.execute('SELECT run_id, timestamp, domain FROM crawl_urls GROUP BY run_id ORDER BY timestamp ASC ')
    return cols_to_props(c)


def fetch_url(url_id):
    c = db.connection.cursor()
    c.execute('SELECT * FROM crawl_urls WHERE id = %s', [url_id])
    return cols_to_props(c)


def fetch_from_links(url_id):
    c = db.connection.cursor()
    c.execute('SELECT crawl_links.*,crawl_urls.path as from_url_path FROM crawl_links LEFT JOIN (crawl_urls) ON (crawl_links.from_url_id=crawl_urls.id) WHERE to_url_id = %s;', [url_id])
    return cols_to_props(c)


def fetch_to_links(url_id):
    c = db.connection.cursor()
    c.execute('SELECT crawl_links.*,crawl_urls.path as to_url_path FROM crawl_links LEFT JOIN (crawl_urls) ON (crawl_links.to_url_id=crawl_urls.id) WHERE from_url_id = %s;', [url_id])
    return cols_to_props(c)


def cols_to_props(c):
    output = []
    descriptions = [t[0] for t in c.description]
    for result in c.fetchall():
        url = dict(zip(descriptions, result))
        # unmarshal keywords
        if 'keywords' in url:
            keywords = json.loads(url.get('keywords', '{}')) or {}
            url['keywords'] = sorted(keywords.items(), key=lambda x: x[1].get('total'), reverse=True)
        output.append(url)
    return output

@app.route("/")
def index():
    run_id = request.args.get('run_id', fetch_latest_run_id())
    filter_lint = request.args.get('filter_lint', None)
    order_by = request.args.get('order_by', None)
    order_by_asc = request.args.get('order_by_asc', None) == '1'
    page = int(request.args.get('page', 1))
    page_length = int(request.args.get('page_length', default_page_length))


    crawl_urls = fetch_run(run_id, page, page_length, lint=filter_lint, order_by=order_by, order_by_asc=order_by_asc)
    run_ids = fetch_run_ids()
    crawl_stats = fetch_run_stats(run_id)

    return render_template('index.html',
        run_id=run_id,
        run_ids=run_ids,
        filter_lint=filter_lint,
        lint_desc=lint_desc,
        lint_level=lint_level,
        crawl_urls=crawl_urls,
        crawl_stats=crawl_stats,
        page=page,
        prev_page=(page - 1 if page > 1 else None),
        next_page=(page + 1 if len(crawl_urls) == page_length else None),
        order_by=order_by,
        order_by_asc=order_by_asc,
        page_length=page_length,
        )

@app.route("/url/")
def url_page():
    url_id = request.args.get('url_id', 1)
    # Fetch all run ids.
    run_ids = fetch_run_ids()
    # Fetch details about the url
    crawl_urls = fetch_url(url_id)
    url = crawl_urls[0]
    lint_results = json.loads(url.get('lint_results'))
    # Fetch associated links.
    from_links = fetch_from_links(url_id)
    to_links = fetch_to_links(url_id)
    
    return render_template('url.html',
        run_ids=run_ids,
        run_id=url.get('run_id'),
        url_id=url_id,
        url=url,
        from_links=from_links,
        to_links=to_links,
        lint_results=lint_results,
        lint_desc=lint_desc,
        lint_level=lint_level,
    )

@app.route("/delete/")
def delete():
    run_id = request.args.get('run_id', fetch_latest_run_id())
    delete_run(run_id)
    return redirect('/')


def main():
    global db
    global app

    parser = optparse.OptionParser(description='SEO Dashboard presents crawl data viewable in the browser.')
    parser.add_option('--database', type="string", default='config.yaml',
        help='A yaml configuration file with the database configuration properties.')
    parser.add_option('--host', type="string", default='127.0.0.1',
        help='IP address to listen to. e.g.: 0.0.0.0 to listen to all interfaces. (default t0 127.0.0.1)')
    parser.add_option('--port', type="string", default='5000',
        help='Port to listen to. (default to 5000)')
    args = parser.parse_args()[0]

    # Try to open the config file.
    try:
        with open(args.database) as f:
            env = yaml.load(f)
    except IOError as e:
        print(str(e))
        exit(1)

    # Initialize the database cursor
    db_conf = env.get('db', {})
    app.config['MYSQL_HOST'] = db_conf.get('host')
    app.config['MYSQL_USER'] = db_conf.get('user')
    app.config['MYSQL_PASSWORD'] = db_conf.get('pass')
    app.config['MYSQL_DB'] = db_conf.get('name')
    app.config['MYSQL_USE_UNICODE'] = True
    db.init_app(app)
    
    app.run(host=args.host, port=int(args.port), debug=True)


if __name__ == "__main__":
    main()
