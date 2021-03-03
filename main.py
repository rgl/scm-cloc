# TODO use https://github.com/XAMPPRocky/tokei?
import argparse
import codecs
import collections
import csv
import datetime
import jinja2
import json
import logging
import os
import pygit2
import re
import re
import subprocess
import sys
import textwrap
import traceback
import urllib.parse

def fetch_repo(url, credentials):
    logging.info('fetching %s', url)
    repo_callbacks = pygit2.RemoteCallbacks(credentials=credentials)
    path = 'repositories/%s' % re.sub(r'[^a-z0-9]', '-', url.lower())
    repo = pygit2.discover_repository(path)
    if repo:
        repo = pygit2.Repository(repo)
        for remote in repo.remotes:
            remote.fetch(prune=pygit2.GIT_FETCH_PRUNE, callbacks=repo_callbacks)
    else:
        repo = pygit2.clone_repository(url, path, callbacks=repo_callbacks)
    return repo

def visit_repo(url, credentials, visitor):
    repo = fetch_repo(url, credentials)

    # gather all branch names.
    branch_names = [r.split('/', 1) for r in repo.branches.remote if r.startswith('origin/') and r != 'origin/HEAD']

    # make sure we have a local branch for each remote branch.
    for remote_name, branch_name in branch_names:
        branch_reference = repo.lookup_reference('refs/remotes/%s/%s' % (remote_name, branch_name))
        commit = branch_reference.peel(pygit2.Commit)
        commit_id = commit.hex
        commit_date = datetime.datetime.fromtimestamp(commit.commit_time, datetime.timezone(datetime.timedelta(minutes=commit.commit_time_offset)))
        logging.info('synching %s %s %s %s', url, branch_name, commit_id, commit_date.isoformat())
        repo.set_head(branch_reference.target)
        repo.branches.create(branch_name, commit, True)
        repo.set_head('refs/heads/%s' % branch_name)

    # iterate all branches.
    for remote_name, branch_name in branch_names:
        branch_reference = repo.lookup_reference('refs/heads/%s' % branch_name)
        commit = branch_reference.peel(pygit2.Commit)
        commit_id = commit.hex
        commit_date = datetime.datetime.fromtimestamp(commit.commit_time, datetime.timezone(datetime.timedelta(minutes=commit.commit_time_offset)))
        logging.info('checking out %s %s %s %s', url, branch_name, commit_id, commit_date.isoformat())
        repo.set_head('refs/heads/%s' % branch_name)
        repo.reset(repo.head.target, pygit2.GIT_RESET_HARD)
        working_directory = os.path.dirname(repo.path.rstrip('/').rstrip('\\'))
        # TODO test whether this branch is merged into master/develop (see git branch --merged).
        for result in visitor(url, repo, working_directory, branch_name, commit_id, commit_date):
            yield result

def cloc(url, credentials, output):
    def __cloc_visitor(url, repo, working_directory, branch, commit_id, commit_date):
        logging.info('executing cloc %s %s %s %s in %s', url, branch, commit_id, commit_date.isoformat(), working_directory)
        #input('press ENTER to continue')
        result = subprocess.run(
            [
                'perl',
                'cloc.pl',
                '--quiet',
                #'--verbose=2',
                '--json',
                '--skip-uniqueness',
                #'--timeout=5',
                #'--by-file-by-lang',
                working_directory
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE
        )
        errors = result.stderr.decode('utf-8')
        report = json.loads(result.stdout.decode('utf-8'))
        yield (url, branch, commit_id, commit_date, errors, report)
    for url, branch, commit_id, commit_date, errors, report in visit_repo(url, credentials, __cloc_visitor):
        result = {
            'url': url,
            'branch': branch,
            'commit_id': commit_id,
            'commit_date': commit_date.isoformat(),
            'errors': errors,
            'report': report,
        }
        json.dump(result, output)
        output.write("\n")

def loc_main(args):
    if args.input == '-':
        input = sys.stdin
    else:
        input = codecs.open(args.input, 'r', 'utf-8')

    if args.output == '-':
        output = sys.stdout
    else:
        output = codecs.open(args.output, 'w', 'utf-8')

    credentials = pygit2.UserPass(
        args.username or os.environ.get('GIT_USERNAME', None),
        args.password or os.environ.get('GIT_PASSWORD', None))
    if not credentials.credential_tuple[0] or not credentials.credential_tuple[1]:
        # NB the user must supply both or none.
        credentials = None

    with input, output:
        for line in input:
            url = line.strip()
            if url == '' or url.startswith('#'):
                continue
            cloc(url, credentials, output)

def __filter_repo_url(value):
    # normalizes an ssh or http(s) url to https.
    # e.g. transform git@github.com:rgl/youtube-converter.git into https://github.com/rgl/youtube-converter
    # e.g. transform https://github.com/rgl/youtube-converter.git into https://github.com/rgl/youtube-converter
    m = re.match(r'(?P<username>\w+)@(?P<domain>[\w\-\.]):(?P<path>.+)', value)
    if m:
        value = f"https://{m.group('domain')}/{m.group('path')}"
    return value.replace('.git', '')

def __filter_repo_short_url(value):
    return urllib.parse.urlparse(__filter_repo_url(value)).path.lstrip('/')

def __filter_repo_branch_url(value, url):
    # e.g. transform master and https://github.com/rgl/youtube-converter.git into https://github.com/rgl/youtube-converter/tree/master
    return f'{__filter_repo_url(url)}/tree/{value}'

def __filter_repo_date(value):
    #                                   subtract this offset to transform local time into UTC time.
    #                                   vvvvvv
    # e.g. transform 2017-11-03T21:40:46+08:00 into 2017-11-03 21:40:46 +08:00.
    #                ^^^^^^^^^^ ^^^^^^^^
    #                local date and time
    #
    # NB this always returns the local time of the commit.
    m = re.match(r'(?P<date>\d+-\d+-\d+)T(?P<time>\d+:\d+:\d+)(?P<offset>[+\-]\d+:\d+)', value)
    return f"{m.group('date')} {m.group('time')} {m.group('offset')}"

def html_main(args):
    if args.input == '-':
        input = sys.stdin
    else:
        input = codecs.open(args.input, 'r', 'utf-8')

    if args.output == '-':
        output = sys.stdout
    else:
        output = codecs.open(args.output, 'w', 'utf-8')

    with input, output:
        repositories = collections.defaultdict(list)
        for repo in (json.loads(line) for line in input):
            repositories[repo['url']].append(repo)
        env = jinja2.Environment(
            loader=jinja2.FileSystemLoader(searchpath=os.path.join(os.path.dirname(os.path.abspath(__file__)), 'templates')),
            autoescape=jinja2.select_autoescape(['html', 'xml']))
        env.filters['repo_url'] = __filter_repo_url
        env.filters['repo_short_url'] = __filter_repo_short_url
        env.filters['repo_branch_url'] = __filter_repo_branch_url
        env.filters['repo_date'] = __filter_repo_date
        template = env.get_template('repositories.html')
        output.write(template.render(repositories=repositories))

def csv_main(args):
    if args.input == '-':
        input = sys.stdin
    else:
        input = codecs.open(args.input, 'r', 'utf-8')

    if args.output == '-':
        output = sys.stdout
    else:
        output = codecs.open(args.output, 'w', 'utf-16')

    with input, output:
        field_names = (
            'url',
            'branch',
            'commit_id',
            'commit_date',
            'language',
            'code'
        )
        w = csv.DictWriter(output, field_names, dialect='excel-tab')
        w.writeheader()

        for line in input:
            report = json.loads(line)
            url = report['url']
            branch = report['branch']
            commit_id = report['commit_id']
            commit_date = report['commit_date']
            for language, loc in report['report'].items():
                if language == 'header':
                    continue
                row = {
                    'url': url,
                    'branch': branch,
                    'commit_id': commit_id,
                    'commit_date': commit_date,
                    'language': language,
                    'code': loc['code'],
                }
                w.writerow(row)

if __name__ == '__main__':
    parser = argparse.ArgumentParser(
        formatter_class=argparse.RawDescriptionHelpFormatter,
        description=textwrap.dedent('''\
            iterate all git branches of a given repository list and output its cloc results

            example:

                python3 %%(prog)s -v loc -o loc.json <<'EOF'
                https://github.com/rgl/packer-provisioner-windows-update.git
                https://github.com/rgl/dotnet-core-single-file-console-app.git
                https://github.com/rgl/tls-dump-clienthello.git
                https://github.com/rgl/youtube-converter.git
                https://github.com/rgl/PowerShellExporter.git
                https://github.com/rgl/debian-live-builder-vagrant.git
                https://github.com/go-gitea/gitea.git
                EOF

                python3 %%(prog)s -v csv -i loc.json -o loc.csv

            info:
                libgit2 version %s
                libgit2 ssl_cert_dir %s
                libgit2 ssl_cert_file %s
            ''' % (pygit2.LIBGIT2_VERSION, pygit2.settings.ssl_cert_dir, pygit2.settings.ssl_cert_file)))
    parser.set_defaults(sub_command=None)
    parser.add_argument(
        '--verbose',
        '-v',
        default=0,
        action='count',
        help='verbosity level. specify multiple to increase logging.')
    subparsers = parser.add_subparsers(help='sub-command help')
    loc_parser = subparsers.add_parser('loc', help='calculate lines of code')
    loc_parser.set_defaults(sub_command=loc_main)
    loc_parser.add_argument(
        '--username',
        '-u',
        default='',
        help='git username. this also reads from the GIT_USERNAME environment variable.')
    loc_parser.add_argument(
        '--password',
        '-p',
        default='',
        help='git password. this also reads from the GIT_PASSWORD environment variable.')
    loc_parser.add_argument(
        '--input',
        '-i',
        default='-',
        help='input file. use \'-\' to read from stdin.')
    loc_parser.add_argument(
        '--output',
        '-o',
        default='-',
        help='output file. use \'-\' to send to stdout.')
    csv_parser = subparsers.add_parser('csv', help='generate a csv report from a loc result')
    csv_parser.set_defaults(sub_command=csv_main)
    csv_parser.add_argument(
        '--input',
        '-i',
        default='-',
        help='input file. use \'-\' to read from stdin.')
    csv_parser.add_argument(
        '--output',
        '-o',
        default='-',
        help='output file. use \'-\' to send to stdout.')
    html_parser = subparsers.add_parser('html', help='generate a html report from a loc result')
    html_parser.set_defaults(sub_command=html_main)
    html_parser.add_argument(
        '--input',
        '-i',
        default='-',
        help='input file. use \'-\' to read from stdin.')
    html_parser.add_argument(
        '--output',
        '-o',
        default='-',
        help='output file. use \'-\' to send to stdout.')
    args = parser.parse_args()

    LOGGING_FORMAT = '%(asctime)-15s %(levelname)s %(name)s: %(message)s'
    if args.verbose >= 3:
        logging.basicConfig(level=logging.DEBUG, format=LOGGING_FORMAT)
        from http.client import HTTPConnection
        HTTPConnection.debuglevel = 1
    elif args.verbose >= 2:
        logging.basicConfig(level=logging.DEBUG, format=LOGGING_FORMAT)
    elif args.verbose >= 1:
        logging.basicConfig(level=logging.INFO, format=LOGGING_FORMAT)

    if args.sub_command:
        args.sub_command(args)
    else:
        parser.print_help()
