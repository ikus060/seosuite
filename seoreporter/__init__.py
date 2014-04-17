 # -*- coding: utf-8 -*-

# usage:
# > python seoreporter/__init__.py [type] [format] [run_id]
# example:
# > python seoreporter/__init__.py build junit d09b8571-5c8a-42ff-8ab7-c38f4f8871c4

# todo
# output valid jUnit XML output
# output html files in a folder
# output html pages that show the data
# output json

import yaml
import datetime

import MySQLdb

report_types = ('build', 'editorial')
report_formats = ('junit', 'html')


def build_report(db, run_id):
    output = []

    c = db.cursor()

    urls = fetch_latest_run(db, run_id)

    # 500 errors
    # TODO add other error codes
    c.execute('''SELECT COUNT(id) as count FROM crawl_urls
        WHERE run_id = %s AND (status_code = 500 or status_code = 0)
        ORDER BY timestamp DESC''', [run_id])
    result = c.fetchone()
    output.append({
        'name': '500 errors',
        'value': result[0],
        })

    # 404s
    c.execute('''SELECT COUNT(id) as count FROM crawl_urls
        WHERE run_id = %s AND status_code = 404
        ORDER BY timestamp DESC''', [run_id])
    result = c.fetchone()
    output.append({
        'name': '404s',
        'value': result[0],
        })

    # missing canonicals
    c.execute('''SELECT COUNT(id) as count FROM crawl_urls
        WHERE run_id = %s AND canonical IS NULL
        ORDER BY timestamp DESC''', [run_id])
    result = c.fetchone()
    output.append({
        'name': 'missing canonical',
        'value': result[0],
        })

    # missing titles
    c.execute('''SELECT COUNT(id) as count FROM crawl_urls
        WHERE run_id = %s AND title_1 IS NULL
        ORDER BY timestamp DESC''', [run_id])
    result = c.fetchone()
    output.append({
        'name': 'missing title',
        'value': result[0],
        })

    # missing meta descriptions
    c.execute('''SELECT COUNT(id) as count FROM crawl_urls
        WHERE run_id = %s AND meta_description_1 IS NULL
        ORDER BY timestamp DESC''', [run_id])
    result = c.fetchone()
    output.append({
        'name': 'missing meta_description',
        'value': result[0],
        })

    # lint level critical
    c.execute('''SELECT COUNT(id) as count FROM crawl_urls
        WHERE run_id = %s AND lint_critical > 0
        ORDER BY timestamp DESC''', [run_id])
    result = c.fetchone()
    output.append({
        'name': 'lint level critical',
        'value': result[0],
        })

    # lint level error
    c.execute('''SELECT COUNT(id) as count FROM crawl_urls
        WHERE run_id = %s AND lint_error > 0
        ORDER BY timestamp DESC''', [run_id])
    result = c.fetchone()
    output.append({
        'name': 'lint level error',
        'value': result[0],
        })

    return output

def junit_format(report_type, tests, run_id):
    print tests
    output = '<?xml version="1.0" encoding="UTF-8"?>\n'
    output += '''<testsuite
        name="%s"
        tests="%s"
        timestamp="%s"
        time=""
        disabled=""
        errors="%s"
        failures="%s"
        id="%s"
        package="seoreporter"
        skipped="0">\n''' % (
        report_type,
        len(tests),
        datetime.datetime.utcnow(),
        sum([test['value'] for test in tests if 'value' in test]),
        len([test['value'] for test in tests if 'value' in test and test['value'] > 0]),
        run_id
        )

    for test in tests:
        output += '\t<testcase class="%s" name="%s">\n' % (report_type, test['name'])
        if test['value'] and test['value'] > 0:
            output += '\t\t<failure type="value">%s</failure>\n' % (test['value'])
        output += '\t</testcase>\n'

    output += '</testsuite>'

    return output


def report(db, report_type, report_format, run_id):
    report_data = None

    if report_type == 'build':
        report_data = build_report(db, run_id)

    if report_data and report_format == 'junit':
        return junit_format(report_type, report_data, run_id)


def fetch_latest_run(db, run_id):
    c = db.cursor()
    c.execute('SELECT * FROM crawl_urls WHERE run_id = %s ORDER BY timestamp DESC', [run_id])
    return c.fetchall()


def fetch_latest_run_id(db):
    run_id = None
    c = db.cursor()
    c.execute('SELECT run_id FROM crawl_urls ORDER BY timestamp DESC LIMIT 1')
    result = c.fetchone()
    if result:
        run_id = result[0]
    return run_id


def run():

    env = yaml.load(open('config.yaml'))

    # Initialize the database cursor
    db_conf = env.get('db', {})
    db = MySQLdb.connect(host=db_conf.get('host'), user=db_conf.get('user'),
        passwd=db_conf.get('pass'), db=db_conf.get('name'))

    # get the latest run_id
    run_id = fetch_latest_run_id(db)

    print report(db, 'build', 'junit', run_id)

if __name__ == "__main__":
    run()