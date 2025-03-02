#!/usr/bin/env python
# -*- coding: utf-8 -*-
# Copyright 2025 Matt Martz
# All Rights Reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License"); you may
# not use this file except in compliance with the License. You may obtain
# a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
# WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
# License for the specific language governing permissions and limitations
# under the License.

from __future__ import print_function, unicode_literals
import csv
import datetime
import errno
import math
import os
import platform
import re
import signal
import socket
import sys
import threading
import timeit
import xml.parsers.expat
import gzip
import json
import ssl

# Constants
__version__ = '2.1.4b1'
DEBUG = False
_GLOBAL_DEFAULT_TIMEOUT = object()

# Exception classes
class SpeedtestException(Exception):
    """Base exception for this module"""

class SpeedtestCLIError(SpeedtestException):
    """Generic exception for raising errors during CLI operation"""

class SpeedtestHTTPError(SpeedtestException):
    """Base HTTP exception for this module"""

class ConfigRetrievalError(SpeedtestHTTPError):
    """Could not retrieve config.php"""

class ServersRetrievalError(SpeedtestHTTPError):
    """Could not retrieve speedtest-servers.php"""

# Utility functions
def printer(string, quiet=False, debug=False, error=False, **kwargs):
    """Helper function to print a string with various features"""
    if debug and not DEBUG:
        return

    if debug:
        out = f'\033[1;30mDEBUG: {string}\033[0m' if sys.stdout.isatty() else f'DEBUG: {string}'
    else:
        out = string

    if error:
        kwargs['file'] = sys.stderr

    if not quiet:
        print(out, **kwargs)

def get_exception():
    """Helper function to get the current exception in a try/except block"""
    return sys.exc_info()[1]

def build_request(url, data=None, headers=None, bump='0', secure=False):
    """Build a request object with a User-Agent header"""
    if not headers:
        headers = {}

    scheme = 'https' if secure else 'http'
    final_url = f'{scheme}://{url}?x={int(timeit.default_timer() * 1000)}.{bump}'
    headers.update({'Cache-Control': 'no-cache'})

    return (final_url, data, headers)

def catch_request(request, opener=None):
    """Helper function to catch common exceptions encountered when establishing a connection"""
    try:
        if opener:
            uh = opener.open(request)
        else:
            uh = urlopen(request)
        return uh, None
    except Exception as e:
        return None, e

# Speedtest class
class Speedtest:
    """Class for performing standard speedtest.net testing operations"""

    def __init__(self, config=None, source_address=None, timeout=10, secure=False, shutdown_event=None):
        self.config = {}
        self._source_address = source_address
        self._timeout = timeout
        self._secure = secure
        self._shutdown_event = shutdown_event or threading.Event()
        self.get_config()
        if config is not None:
            self.config.update(config)

    def get_config(self):
        """Download the speedtest.net configuration and return only the data we are interested in"""
        headers = {'Accept-Encoding': 'gzip'} if gzip else {}
        request = build_request('www.speedtest.net/speedtest-config.php', headers=headers, secure=self._secure)
        uh, e = catch_request(request)
        if e:
            raise ConfigRetrievalError(e)
        configxml_list = []

        stream = get_response_stream(uh)

        while 1:
            try:
                configxml_list.append(stream.read(1024))
            except (OSError, EOFError):
                raise ConfigRetrievalError(get_exception())
            if len(configxml_list[-1]) == 0:
                break
        stream.close()
        uh.close()

        if int(uh.code) != 200:
            return None

        configxml = ''.encode().join(configxml_list)

        printer('Config XML:\n%s' % configxml, debug=True)

        try:
            try:
                root = ET.fromstring(configxml)
            except ET.ParseError:
                e = get_exception()
                raise SpeedtestConfigError(
                    'Malformed speedtest.net configuration: %s' % e
                )
            server_config = root.find('server-config').attrib
            download = root.find('download').attrib
            upload = root.find('upload').attrib
            # times = root.find('times').attrib
            client = root.find('client').attrib

        except AttributeError:
            try:
                root = DOM.parseString(configxml)
            except ExpatError:
                e = get_exception()
                raise SpeedtestConfigError(
                    'Malformed speedtest.net configuration: %s' % e
                )
            server_config = get_attributes_by_tag_name(root, 'server-config')
            download = get_attributes_by_tag_name(root, 'download')
            upload = get_attributes_by_tag_name(root, 'upload')
            # times = get_attributes_by_tag_name(root, 'times')
            client = get_attributes_by_tag_name(root, 'client')

        ignore_servers = [
            int(i) for i in server_config['ignoreids'].split(',') if i
        ]

        ratio = int(upload['ratio'])
        upload_max = int(upload['maxchunkcount'])
        up_sizes = [32768, 65536, 131072, 262144, 524288, 1048576, 7340032]
        sizes = {
            'upload': up_sizes[ratio - 1:],
            'download': [350, 500, 750, 1000, 1500, 2000, 2500,
                         3000, 3500, 4000]
        }

        size_count = len(sizes['upload'])

        upload_count = int(math.ceil(upload_max / size_count))

        counts = {
            'upload': upload_count,
            'download': int(download['threadsperurl'])
        }

        threads = {
            'upload': int(upload['threads']),
            'download': int(server_config['threadcount']) * 2
        }

        length = {
            'upload': int(upload['testlength']),
            'download': int(download['testlength'])
        }

        self.config.update({
            'client': client,
            'ignore_servers': ignore_servers,
            'sizes': sizes,
            'counts': counts,
            'threads': threads,
            'length': length,
            'upload_max': upload_count * size_count
        })

        try:
            self.lat_lon = (float(client['lat']), float(client['lon']))
        except ValueError:
            raise SpeedtestConfigError(
                'Unknown location: lat=%r lon=%r' %
                (client.get('lat'), client.get('lon'))
            )

        printer('Config:\n%r' % self.config, debug=True)

        return self.config

    def get_servers(self, servers=None, exclude=None):
        """Retrieve a the list of speedtest.net servers, optionally filtered
        to servers matching those specified in the ``servers`` argument
        """
        if servers is None:
            servers = []

        if exclude is None:
            exclude = []

        self.servers.clear()

        for server_list in (servers, exclude):
            for i, s in enumerate(server_list):
                try:
                    server_list[i] = int(s)
                except ValueError:
                    raise InvalidServerIDType(
                        '%s is an invalid server type, must be int' % s
                    )

        urls = [
            '://www.speedtest.net/speedtest-servers-static.php',
            'http://c.speedtest.net/speedtest-servers-static.php',
            '://www.speedtest.net/speedtest-servers.php',
            'http://c.speedtest.net/speedtest-servers.php',
        ]

        headers = {}
        if gzip:
            headers['Accept-Encoding'] = 'gzip'

        errors = []
        for url in urls:
            try:
                request = build_request(
                    '%s?threads=%s' % (url,
                                       self.config['threads']['download']),
                    headers=headers,
                    secure=self._secure
                )
                uh, e = catch_request(request, opener=self._opener)
                if e:
                    errors.append('%s' % e)
                    raise ServersRetrievalError()

                stream = get_response_stream(uh)

                serversxml_list = []
                while 1:
                    try:
                        serversxml_list.append(stream.read(1024))
                    except (OSError, EOFError):
                        raise ServersRetrievalError(get_exception())
                    if len(serversxml_list[-1]) == 0:
                        break

                stream.close()
                uh.close()

                if int(uh.code) != 200:
                    raise ServersRetrievalError()

                serversxml = ''.encode().join(serversxml_list)

                printer('Servers XML:\n%s' % serversxml, debug=True)

                try:
                    try:
                        try:
                            root = ET.fromstring(serversxml)
                        except ET.ParseError:
                            e = get_exception()
                            raise SpeedtestServersError(
                                'Malformed speedtest.net server list: %s' % e
                            )
                        elements = etree_iter(root, 'server')
                    except AttributeError:
                        try:
                            root = DOM.parseString(serversxml)
                        except ExpatError:
                            e = get_exception()
                            raise SpeedtestServersError(
                                'Malformed speedtest.net server list: %s' % e
                            )
                        elements = root.getElementsByTagName('server')
                except (SyntaxError, xml.parsers.expat.ExpatError):
                    raise ServersRetrievalError()

                for server in elements:
                    try:
                        attrib = server.attrib
                    except AttributeError:
                        attrib = dict(list(server.attributes.items()))

                    if servers and int(attrib.get('id')) not in servers:
                        continue

                    if (int(attrib.get('id')) in self.config['ignore_servers']
                            or int(attrib.get('id')) in exclude):
                        continue

                    try:
                        d = distance(self.lat_lon,
                                     (float(attrib.get('lat')),
                                      float(attrib.get('lon'))))
                    except Exception:
                        continue

                    attrib['d'] = d

                    try:
                        self.servers[d].append(attrib)
                    except KeyError:
                        self.servers[d] = [attrib]

                break

            except ServersRetrievalError:
                continue

        if (servers or exclude) and not self.servers:
            raise NoMatchedServers()

        return self.servers

    def set_mini_server(self, server):
        """Instead of querying for a list of servers, set a link to a
        speedtest mini server
        """

        urlparts = urlparse(server)

        name, ext = os.path.splitext(urlparts[2])
        if ext:
            url = os.path.dirname(server)
        else:
            url = server

        request = build_request(url)
        uh, e = catch_request(request, opener=self._opener)
        if e:
            raise SpeedtestMiniConnectFailure('Failed to connect to %s' %
                                              server)
        else:
            text = uh.read()
            uh.close()

        extension = re.findall('upload_?[Ee]xtension: "([^"]+)"',
                               text.decode())
        if not extension:
            for ext in ['php', 'asp', 'aspx', 'jsp']:
                try:
                    f = self._opener.open(
                        '%s/speedtest/upload.%s' % (url, ext)
                    )
                except Exception:
                    pass
                else:
                    data = f.read().strip().decode()
                    if (f.code == 200 and
                            len(data.splitlines()) == 1 and
                            re.match('size=[0-9]', data)):
                        extension = [ext]
                        break
        if not urlparts or not extension:
            raise InvalidSpeedtestMiniServer('Invalid Speedtest Mini Server: '
                                             '%s' % server)

        self.servers = [{
            'sponsor': 'Speedtest Mini',
            'name': urlparts[1],
            'd': 0,
            'url': '%s/speedtest/upload.%s' % (url.rstrip('/'), extension[0]),
            'latency': 0,
            'id': 0
        }]

        return self.servers

    def get_closest_servers(self, limit=5):
        """Limit servers to the closest speedtest.net servers based on
        geographic distance
        """

        if not self.servers:
            self.get_servers()

        for d in sorted(self.servers.keys()):
            for s in self.servers[d]:
                self.closest.append(s)
                if len(self.closest) == limit:
                    break
            else:
                continue
            break

        printer('Closest Servers:\n%r' % self.closest, debug=True)
        return self.closest

    def get_best_server(self, servers=None):
        """Perform a speedtest.net "ping" to determine which speedtest.net
        server has the lowest latency
        """

        if not servers:
            if not self.closest:
                servers = self.get_closest_servers()
            servers = self.closest

        if self._source_address:
            source_address_tuple = (self._source_address, 0)
        else:
            source_address_tuple = None

        user_agent = build_user_agent()

        results = {}
        for server in servers:
            cum = []
            url = os.path.dirname(server['url'])
            stamp = int(timeit.time.time() * 1000)
            latency_url = '%s/latency.txt?x=%s' % (url, stamp)
            for i in range(0, 3):
                this_latency_url = '%s.%s' % (latency_url, i)
                printer('%s %s' % ('GET', this_latency_url),
                        debug=True)
                urlparts = urlparse(latency_url)
                try:
                    if urlparts[0] == 'https':
                        h = SpeedtestHTTPSConnection(
                            urlparts[1],
                            source_address=source_address_tuple
                        )
                    else:
                        h = SpeedtestHTTPConnection(
                            urlparts[1],
                            source_address=source_address_tuple
                        )
                    headers = {'User-Agent': user_agent}
                    path = '%s?%s' % (urlparts[2], urlparts[4])
                    start = timeit.default_timer()
                    h.request("GET", path, headers=headers)
                    r = h.getresponse()
                    total = (timeit.default_timer() - start)
                except HTTP_ERRORS:
                    e = get_exception()
                    printer('ERROR: %r' % e, debug=True)
                    cum.append(3600)
                    continue

                text = r.read(9)
                if int(r.status) == 200 and text == 'test=test'.encode():
                    cum.append(total)
                else:
                    cum.append(3600)
                h.close()

            avg = round((sum(cum) / 6) * 1000.0, 3)
            results[avg] = server

        try:
            fastest = sorted(results.keys())[0]
        except IndexError:
            raise SpeedtestBestServerFailure('Unable to connect to servers to '
                                             'test latency.')
        best = results[fastest]
        best['latency'] = fastest

        self.results.ping = fastest
        self.results.server = best

        self._best.update(best)
        printer('Best Server:\n%r' % best, debug=True)
        return best

    def download(self, callback=do_nothing, threads=None):
        """Test download speed against speedtest.net

        A ``threads`` value of ``None`` will fall back to those dictated
        by the speedtest.net configuration
        """

        urls = []
        for size in self.config['sizes']['download']:
            for _ in range(0, self.config['counts']['download']):
                urls.append('%s/random%sx%s.jpg' %
                            (os.path.dirname(self.best['url']), size, size))

        request_count = len(urls)
        requests = []
        for i, url in enumerate(urls):
            requests.append(
                build_request(url, bump=i, secure=self._secure)
            )

        max_threads = threads or self.config['threads']['download']
        in_flight = {'threads': 0}

        def producer(q, requests, request_count):
            for i, request in enumerate(requests):
                thread = HTTPDownloader(
                    i,
                    request,
                    start,
                    self.config['length']['download'],
                    opener=self._opener,
                    shutdown_event=self._shutdown_event
                )
                while in_flight['threads'] >= max_threads:
                    timeit.time.sleep(0.001)
                thread.start()
                q.put(thread, True)
                in_flight['threads'] += 1
                callback(i, request_count, start=True)

        finished = []

        def consumer(q, request_count):
            _is_alive = thread_is_alive
            while len(finished) < request_count:
                thread = q.get(True)
                while _is_alive(thread):
                    thread.join(timeout=0.001)
                in_flight['threads'] -= 1
                finished.append(sum(thread.result))
                callback(thread.i, request_count, end=True)

        q = Queue(max_threads)
        prod_thread = threading.Thread(target=producer,
                                       args=(q, requests, request_count))
        cons_thread = threading.Thread(target=consumer,
                                       args=(q, request_count))
        start = timeit.default_timer()
        prod_thread.start()
        cons_thread.start()
        _is_alive = thread_is_alive
        while _is_alive(prod_thread):
            prod_thread.join(timeout=0.001)
        while _is_alive(cons_thread):
            cons_thread.join(timeout=0.001)

        stop = timeit.default_timer()
        self.results.bytes_received = sum(finished)
        self.results.download = (
            (self.results.bytes_received / (stop - start)) * 8.0
        )
        if self.results.download > 100000:
            self.config['threads']['upload'] = 8
        return self.results.download

    def upload(self, callback=do_nothing, pre_allocate=True, threads=None):
        """Test upload speed against speedtest.net

        A ``threads`` value of ``None`` will fall back to those dictated
        by the speedtest.net configuration
        """

        sizes = []

        for size in self.config['sizes']['upload']:
            for _ in range(0, self.config['counts']['upload']):
                sizes.append(size)

        # request_count = len(sizes)
        request_count = self.config['upload_max']

        requests = []
        for i, size in enumerate(sizes):
            # We set ``0`` for ``start`` and handle setting the actual
            # ``start`` in ``HTTPUploader`` to get better measurements
            data = HTTPUploaderData(
                size,
                0,
                self.config['length']['upload'],
                shutdown_event=self._shutdown_event
            )
            if pre_allocate:
                data.pre_allocate()

            headers = {'Content-length': size}
            requests.append(
                (
                    build_request(self.best['url'], data, secure=self._secure,
                                  headers=headers),
                    size
                )
            )

        max_threads = threads or self.config['threads']['upload']
        in_flight = {'threads': 0}

        def producer(q, requests, request_count):
            for i, request in enumerate(requests[:request_count]):
                thread = HTTPUploader(
                    i,
                    request[0],
                    start,
                    request[1],
                    self.config['length']['upload'],
                    opener=self._opener,
                    shutdown_event=self._shutdown_event
                )
                while in_flight['threads'] >= max_threads:
                    timeit.time.sleep(0.001)
                thread.start()
                q.put(thread, True)
                in_flight['threads'] += 1
                callback(i, request_count, start=True)

        finished = []

        def consumer(q, request_count):
            _is_alive = thread_is_alive
            while len(finished) < request_count:
                thread = q.get(True)
                while _is_alive(thread):
                    thread.join(timeout=0.001)
                in_flight['threads'] -= 1
                finished.append(thread.result)
                callback(thread.i, request_count, end=True)

        q = Queue(threads or self.config['threads']['upload'])
        prod_thread = threading.Thread(target=producer,
                                       args=(q, requests, request_count))
        cons_thread = threading.Thread(target=consumer,
                                       args=(q, request_count))
        start = timeit.default_timer()
        prod_thread.start()
        cons_thread.start()
        _is_alive = thread_is_alive
        while _is_alive(prod_thread):
            prod_thread.join(timeout=0.1)
        while _is_alive(cons_thread):
            cons_thread.join(timeout=0.1)

        stop = timeit.default_timer()
        self.results.bytes_sent = sum(finished)
        self.results.upload = (
            (self.results.bytes_sent / (stop - start)) * 8.0
        )
        return self.results.upload


def ctrl_c(shutdown_event):
    """Catch Ctrl-C key sequence and set a SHUTDOWN_EVENT for our threaded
    operations
    """
    def inner(signum, frame):
        shutdown_event.set()
        printer('\nCancelling...', error=True)
        sys.exit(0)
    return inner


def version():
    """Print the version"""

    printer('speedtest-cli %s' % __version__)
    printer('Python %s' % sys.version.replace('\n', ''))
    sys.exit(0)


def csv_header(delimiter=','):
    """Print the CSV Headers"""

    printer(SpeedtestResults.csv_header(delimiter=delimiter))
    sys.exit(0)


def parse_args():
    """Function to handle building and parsing of command line arguments"""
    description = (
        'Command line interface for testing internet bandwidth using '
        'speedtest.net.\n'
        '------------------------------------------------------------'
        '--------------\n'
        'https://github.com/sivel/speedtest-cli')

    parser = ArgParser(description=description)
    # Give optparse.OptionParser an `add_argument` method for
    # compatibility with argparse.ArgumentParser
    try:
        parser.add_argument = parser.add_option
    except AttributeError:
        pass
    parser.add_argument('--no-download', dest='download', default=True,
                        action='store_const', const=False,
                        help='Do not perform download test')
    parser.add_argument('--no-upload', dest='upload', default=True,
                        action='store_const', const=False,
                        help='Do not perform upload test')
    parser.add_argument('--single', default=False, action='store_true',
                        help='Only use a single connection instead of '
                             'multiple. This simulates a typical file '
                             'transfer.')
    parser.add_argument('--bytes', dest='units', action='store_const',
                        const=('byte', 8), default=('bit', 1),
                        help='Display values in bytes instead of bits. Does '
                             'not affect the image generated by --share, nor '
                             'output from --json or --csv')
    parser.add_argument('--share', action='store_true',
                        help='Generate and provide a URL to the speedtest.net '
                             'share results image, not displayed with --csv')
    parser.add_argument('--simple', action='store_true', default=False,
                        help='Suppress verbose output, only show basic '
                             'information')
    parser.add_argument('--csv', action='store_true', default=False,
                        help='Suppress verbose output, only show basic '
                             'information in CSV format. Speeds listed in '
                             'bit/s and not affected by --bytes')
    parser.add_argument('--csv-delimiter', default=',', type=PARSER_TYPE_STR,
                        help='Single character delimiter to use in CSV '
                             'output. Default ","')
    parser.add_argument('--csv-header', action='store_true', default=False,
                        help='Print CSV headers')
    parser.add_argument('--json', action='store_true', default=False,
                        help='Suppress verbose output, only show basic '
                             'information in JSON format. Speeds listed in '
                             'bit/s and not affected by --bytes')
    parser.add_argument('--list', action='store_true',
                        help='Display a list of speedtest.net servers '
                             'sorted by distance')
    parser.add_argument('--server', type=PARSER_TYPE_INT, action='append',
                        help='Specify a server ID to test against. Can be '
                             'supplied multiple times')
    parser.add_argument('--exclude', type=PARSER_TYPE_INT, action='append',
                        help='Exclude a server from selection. Can be '
                             'supplied multiple times')
    parser.add_argument('--mini', help='URL of the Speedtest Mini server')
    parser.add_argument('--source', help='Source IP address to bind to')
    parser.add_argument('--timeout', default=10, type=PARSER_TYPE_FLOAT,
                        help='HTTP timeout in seconds. Default 10')
    parser.add_argument('--secure', action='store_true',
                        help='Use HTTPS instead of HTTP when communicating '
                             'with speedtest.net operated servers')
    parser.add_argument('--no-pre-allocate', dest='pre_allocate',
                        action='store_const', default=True, const=False,
                        help='Do not pre allocate upload data. Pre allocation '
                             'is enabled by default to improve upload '
                             'performance. To support systems with '
                             'insufficient memory, use this option to avoid a '
                             'MemoryError')
    parser.add_argument('--version', action='store_true',
                        help='Show the version number and exit')
    parser.add_argument('--debug', action='store_true',
                        help=ARG_SUPPRESS, default=ARG_SUPPRESS)

    options = parser.parse_args()
    if isinstance(options, tuple):
        args = options[0]
    else:
        args = options
    return args


def validate_optional_args(args):
    """Check if an argument was provided that depends on a module that may
    not be part of the Python standard library.

    If such an argument is supplied, and the module does not exist, exit
    with an error stating which module is missing.
    """
    optional_args = {
        'json': ('json/simplejson python module', json),
        'secure': ('SSL support', HTTPSConnection),
    }

    for arg, info in optional_args.items():
        if getattr(args, arg, False) and info[1] is None:
            raise SystemExit('%s is not installed. --%s is '
                             'unavailable' % (info[0], arg))


def printer(string, quiet=False, debug=False, error=False, **kwargs):
    """Helper function print a string with various features"""

    if debug and not DEBUG:
        return

    if debug:
        if sys.stdout.isatty():
            out = '\033[1;30mDEBUG: %s\033[0m' % string
        else:
            out = 'DEBUG: %s' % string
    else:
        out = string

    if error:
        kwargs['file'] = sys.stderr

    if not quiet:
        print_(out, **kwargs)


def shell():
    """Run the full speedtest.net test"""

    global DEBUG
    shutdown_event = threading.Event()

    signal.signal(signal.SIGINT, ctrl_c(shutdown_event))

    args = parse_args()

    # Print the version and exit
    if args.version:
        version()

    if not args.download and not args.upload:
        raise SpeedtestCLIError('Cannot supply both --no-download and '
                                '--no-upload')

    if len(args.csv_delimiter) != 1:
        raise SpeedtestCLIError('--csv-delimiter must be a single character')

    if args.csv_header:
        csv_header(args.csv_delimiter)

    validate_optional_args(args)

    debug = getattr(args, 'debug', False)
    if debug == 'SUPPRESSHELP':
        debug = False
    if debug:
        DEBUG = True

    if args.simple or args.csv or args.json:
        quiet = True
    else:
        quiet = False

    if args.csv or args.json:
        machine_format = True
    else:
        machine_format = False

    # Don't set a callback if we are running quietly
    if quiet or debug:
        callback = do_nothing
    else:
        callback = print_dots(shutdown_event)

    printer('Retrieving speedtest.net configuration...', quiet)
    try:
        speedtest = Speedtest(
            source_address=args.source,
            timeout=args.timeout,
            secure=args.secure
        )
    except (ConfigRetrievalError,) + HTTP_ERRORS:
        printer('Cannot retrieve speedtest configuration', error=True)
        raise SpeedtestCLIError(get_exception())

    if args.list:
        try:
            speedtest.get_servers()
        except (ServersRetrievalError,) + HTTP_ERRORS:
            printer('Cannot retrieve speedtest server list', error=True)
            raise SpeedtestCLIError(get_exception())

        for _, servers in sorted(speedtest.servers.items()):
            for server in servers:
                line = ('%(id)5s) %(sponsor)s (%(name)s, %(country)s) '
                        '[%(d)0.2f km]' % server)
                try:
                    printer(line)
                except IOError:
                    e = get_exception()
                    if e.errno != errno.EPIPE:
                        raise
        sys.exit(0)

    printer('Testing from %(isp)s (%(ip)s)...' % speedtest.config['client'],
            quiet)

    if not args.mini:
        printer('Retrieving speedtest.net server list...', quiet)
        try:
            speedtest.get_servers(servers=args.server, exclude=args.exclude)
        except NoMatchedServers:
            raise SpeedtestCLIError(
                'No matched servers: %s' %
                ', '.join('%s' % s for s in args.server)
            )
        except (ServersRetrievalError,) + HTTP_ERRORS:
            printer('Cannot retrieve speedtest server list', error=True)
            raise SpeedtestCLIError(get_exception())
        except InvalidServerIDType:
            raise SpeedtestCLIError(
                '%s is an invalid server type, must '
                'be an int' % ', '.join('%s' % s for s in args.server)
            )

        if args.server and len(args.server) == 1:
            printer('Retrieving information for the selected server...', quiet)
        else:
            printer('Selecting best server based on ping...', quiet)
        speedtest.get_best_server()
    elif args.mini:
        speedtest.get_best_server(speedtest.set_mini_server(args.mini))

    results = speedtest.results

    printer('Hosted by %(sponsor)s (%(name)s) [%(d)0.2f km]: '
            '%(latency)s ms' % results.server, quiet)

    if args.download:
        printer('Testing download speed', quiet,
                end=('', '\n')[bool(debug)])
        speedtest.download(
            callback=callback,
            threads=(None, 1)[args.single]
        )
        printer('Download: %0.2f M%s/s' %
                ((results.download / 1000.0 / 1000.0) / args.units[1],
                 args.units[0]),
                quiet)
    else:
        printer('Skipping download test', quiet)

    if args.upload:
        printer('Testing upload speed', quiet,
                end=('', '\n')[bool(debug)])
        speedtest.upload(
            callback=callback,
            pre_allocate=args.pre_allocate,
            threads=(None, 1)[args.single]
        )
        printer('Upload: %0.2f M%s/s' %
                ((results.upload / 1000.0 / 1000.0) / args.units[1],
                 args.units[0]),
                quiet)
    else:
        printer('Skipping upload test', quiet)

    printer('Results:\n%r' % results.dict(), debug=True)

    if not args.simple and args.share:
        results.share()

    if args.simple:
        printer('Ping: %s ms\nDownload: %0.2f M%s/s\nUpload: %0.2f M%s/s' %
                (results.ping,
                 (results.download / 1000.0 / 1000.0) / args.units[1],
                 args.units[0],
                 (results.upload / 1000.0 / 1000.0) / args.units[1],
                 args.units[0]))
    elif args.csv:
        printer(results.csv(delimiter=args.csv_delimiter))
    elif args.json:
        printer(results.json())

    if args.share and not machine_format:
        printer('Share results: %s' % results.share())

# Main function
def main():
    try:
        shell()
    except KeyboardInterrupt:
        printer('\nCancelling...', error=True)
    except (SpeedtestException, SystemExit):
        e = get_exception()
        if getattr(e, 'code', 1) not in (0, 2):
            msg = f'ERROR: {e}' if str(e) else f'ERROR: {repr(e)}'
            raise SystemExit(msg)

if __name__ == '__main__':
    main()
