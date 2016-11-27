#!/usr/bin/env python
# -*- coding: utf-8 -*-

# Usage:
# python seodashboard/main.py

import MySQLdb
from flask import Flask, render_template, request
import json
import yaml

import seolinter


app = Flask(__name__, template_folder='.', static_folder='static', static_url_path='/static')
db = None

default_page_length = 50


def fetch_latest_run_id():
    run_id = None
    c = db.cursor()
    c.execute('SELECT run_id FROM crawl_urls ORDER BY timestamp DESC LIMIT 1')
    result = c.fetchone()
    if result:
        run_id = result[0]
    return run_id


def fetch_run(run_id, page=1, page_length=default_page_length):
    c = db.cursor()
    start = (page - 1) * page_length
    c.execute('SELECT * FROM crawl_urls WHERE run_id = %s AND external = 0 ORDER BY lint_critical DESC, lint_error DESC, lint_warn DESC LIMIT %s, %s',
        [run_id, start, page_length])
    return cols_to_props(c)


def fetch_run_count(run_id):
    c = db.cursor()
    c.execute('SELECT COUNT(id) as count FROM crawl_urls WHERE run_id = %s', [run_id])
    result = c.fetchone()
    return int(result[0]) if result else 0


def fetch_run_ids():
    c = db.cursor()
    c.execute('SELECT run_id, timestamp, domain FROM crawl_urls GROUP BY run_id ORDER BY timestamp ASC ')
    return cols_to_props(c)

def fetch_url(url_id):
    c = db.cursor()
    c.execute('SELECT * FROM crawl_urls WHERE id = %s', [url_id])
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
def hello():
    run_id = request.args.get('run_id', fetch_latest_run_id())
    page = int(request.args.get('page', 1))
    page_length = int(request.args.get('page_length', default_page_length))


    crawl_urls = fetch_run(run_id, page, page_length)
    crawl_url_count = fetch_run_count(run_id)
    run_ids = fetch_run_ids()

    print [page, crawl_url_count, page_length]

    return render_template('index.html',
        run_id=run_id,
        run_ids=run_ids,
        crawl_urls=crawl_urls,
        prev_page=(page - 1 if page > 1 else None),
        next_page=(page + 1 if page < crawl_url_count / page_length else None),
        )

@app.route("/url")
def url_page():
    url_id = request.args.get('url_id', 1)
    crawl_urls = fetch_url(url_id)
    run_ids = fetch_run_ids()
    
    print [url_id]
    
    url = crawl_urls[0]
    lint_results = json.loads(url.get('lint_results'))
    lint_desc = {t[0]: t[1] for t in seolinter.rules}
    lint_level = {t[0]: t[2] for t in seolinter.rules}

    return render_template('url.html',
        run_ids=run_ids,
        url_id=url_id,
        url=url,
        lint_results=lint_results,
        lint_desc=lint_desc,
        lint_level=lint_level,
        )


def main():
    global db
    global app
    env = yaml.load(open('config.yaml'))

    # Initialize the database cursor
    db_conf = env.get('db', {})
    db = MySQLdb.connect(host=db_conf.get('host'), user=db_conf.get('user'),
        passwd=db_conf.get('pass'), db=db_conf.get('name'), use_unicode=True,
        charset='utf8')

    app.run(debug=True)


if __name__ == "__main__":
    main()
