#!/usr/bin/env python
# coding=utf-8
# Contributor:
#      Phus Lu        <phus.lu@gmail.com>

__version__ = '3.0.7'
__password__ = ''
__hostsdeny__ = ()  # __hostsdeny__ = ('.youtube.com', '.youku.com')

import sys
import os
import re
import time
import struct
import zlib
import base64
import logging
import httplib
import urlparse
import errno
import string
try:
    from io import BytesIO
except ImportError:
    from cStringIO import StringIO as BytesIO
try:
    from google.appengine.api import urlfetch
    from google.appengine.runtime import apiproxy_errors
except ImportError:
    urlfetch = None
try:
    import sae
except ImportError:
    sae = None
try:
    import bae.core.wsgi
except ImportError:
    bae = None
try:
    import socket
    import select
except ImportError:
    socket = None
try:
    import OpenSSL
except ImportError:
    OpenSSL = None

URLFETCH_MAX = 2
URLFETCH_MAXSIZE = 4*1024*1024
URLFETCH_DEFLATE_MAXSIZE = 4*1024*1024
URLFETCH_TIMEOUT = 60

def message_html(title, banner, detail=''):
    MESSAGE_TEMPLATE = '''
    <html><head>
    <meta http-equiv="content-type" content="text/html;charset=utf-8">
    <title>$title</title>
    <style><!--
    body {font-family: arial,sans-serif}
    div.nav {margin-top: 1ex}
    div.nav A {font-size: 10pt; font-family: arial,sans-serif}
    span.nav {font-size: 10pt; font-family: arial,sans-serif; font-weight: bold}
    div.nav A,span.big {font-size: 12pt; color: #0000cc}
    div.nav A {font-size: 10pt; color: black}
    A.l:link {color: #6f6f6f}
    A.u:link {color: green}
    //--></style>
    </head>
    <body text=#000000 bgcolor=#ffffff>
    <table border=0 cellpadding=2 cellspacing=0 width=100%>
    <tr><td bgcolor=#3366cc><font face=arial,sans-serif color=#ffffff><b>Message</b></td></tr>
    <tr><td> </td></tr></table>
    <blockquote>
    <H1>$banner</H1>
    $detail
    <p>
    </blockquote>
    <table width=100% cellpadding=0 cellspacing=0><tr><td bgcolor=#3366cc><img alt="" width=1 height=4></td></tr></table>
    </body></html>
    '''
    return string.Template(MESSAGE_TEMPLATE).substitute(title=title, banner=banner, detail=detail)


def rc4crypt(data, key):
    """RC4 algorithm"""
    if not key or not data:
        return data
    x = 0
    box = range(256)
    for i, y in enumerate(box):
        x = (x + y + ord(key[i % len(key)])) & 0xff
        box[i], box[x] = box[x], y
    x = y = 0
    out = []
    out_append = out.append
    for char in data:
        x = (x + 1) & 0xff
        y = (y + box[x]) & 0xff
        box[x], box[y] = box[y], box[x]
        out_append(chr(ord(char) ^ box[(box[x] + box[y]) & 0xff]))
    return ''.join(out)


class RC4FileObject(object):
    """fileobj for rc4"""
    def __init__(self, stream, key):
        self.__stream = stream
        x = 0
        box = range(256)
        for i, y in enumerate(box):
            x = (x + y + ord(key[i % len(key)])) & 0xff
            box[i], box[x] = box[x], y
        self.__box = box
        self.__x = 0
        self.__y = 0

    def __getattr__(self, attr):
        if attr not in ('__stream', '__box', '__x', '__y'):
            return getattr(self.__stream, attr)

    def read(self, size=-1):
        out = []
        out_append = out.append
        x = self.__x
        y = self.__y
        box = self.__box
        data = self.__stream.read(size)
        for char in data:
            x = (x + 1) & 0xff
            y = (y + box[x]) & 0xff
            box[x], box[y] = box[y], box[x]
            out_append(chr(ord(char) ^ box[(box[x] + box[y]) & 0xff]))
        self.__x = x
        self.__y = y
        return ''.join(out)


try:
    from Crypto.Cipher.ARC4 import new as _Crypto_Cipher_ARC4_new
    def rc4crypt(data, key):
        return _Crypto_Cipher_ARC4_new(key).encrypt(data) if key else data
    class RC4FileObject(object):
        """fileobj for rc4"""
        def __init__(self, stream, key):
            self.__stream = stream
            self.__cipher = _Crypto_Cipher_ARC4_new(key) if key else lambda x:x
        def __getattr__(self, attr):
            if attr not in ('__stream', '__cipher'):
                return getattr(self.__stream, attr)
        def read(self, size=-1):
            return self.__cipher.encrypt(self.__stream.read(size))
except ImportError:
    pass


def gae_application(environ, start_response):
    cookie = environ.get('HTTP_COOKIE', '')
    options = environ.get('HTTP_X_GOA_OPTIONS', '')
    rc4_key = environ.get('HTTP_X_GOA_OPTIONS_KEY', '')
    if environ['REQUEST_METHOD'] == 'GET' and not cookie:
        if '204' in environ['QUERY_STRING']:
            start_response('204 No Content', [])
            yield ''
        else:
            timestamp = long(os.environ['CURRENT_VERSION_ID'].split('.')[1])/2**28
            ctime = time.strftime('%Y-%m-%d %H:%M:%S', time.gmtime(timestamp+8*3600))
            html = u'GoAgent Python Server %s \u5df2\u7ecf\u5728\u5de5\u4f5c\u4e86\uff0c\u90e8\u7f72\u65f6\u95f4 %s\n' % (__version__, ctime)
            start_response('200 OK', [('Content-Type', 'text/plain; charset=utf-8')])
            yield html.encode('utf8')
        raise StopIteration

    # inflate = lambda x:zlib.decompress(x, -zlib.MAX_WBITS)
    wsgi_input = environ['wsgi.input']
    input_data = wsgi_input.read()
    
    rc4_key = __password__
    if 'rc4' in options and rc4_key and __RSA_KEY__:
        #logging.info(rc4_key)
        from Crypto.PublicKey import RSA
        from Crypto.Cipher import PKCS1_OAEP
        rsakey = RSA.importKey(__RSA_KEY__.strip())
        rsakey = PKCS1_OAEP.new(rsakey)
        rc4_key = rsakey.decrypt(base64.b64decode(rc4_key))
        #logging.info(rc4_key)

    try:
        if cookie:
            if 'rc4' not in options:
                metadata = zlib.decompress(base64.b64decode(cookie), -zlib.MAX_WBITS)
                payload = input_data or ''
            else:
                metadata = zlib.decompress(rc4crypt(base64.b64decode(cookie), rc4_key), -zlib.MAX_WBITS)
                payload = rc4crypt(input_data, rc4_key) if input_data else ''
        else:
            if 'rc4' in options:
                input_data = rc4crypt(input_data, rc4_key)
            metadata_length, = struct.unpack('!h', input_data[:2])
            metadata = zlib.decompress(input_data[2:2+metadata_length], -zlib.MAX_WBITS)
            payload = input_data[2+metadata_length:]
        headers = dict(x.split(':', 1) for x in metadata.splitlines() if x)
        method = headers.pop('G-Method')
        url = headers.pop('G-Url')
    except (zlib.error, KeyError, ValueError):
        import traceback
        start_response('500 Internal Server Error', [('Content-Type', 'text/html')])
        yield message_html('500 Internal Server Error', 'Bad Request (metadata) - Possible Wrong Password', '<pre>%s</pre>' % traceback.format_exc())
        raise StopIteration

    kwargs = {}
    any(kwargs.__setitem__(x[2:].lower(), headers.pop(x)) for x in headers.keys() if x.startswith('G-'))

    if 'Content-Encoding' in headers:
        if headers['Content-Encoding'] == 'deflate':
            payload = zlib.decompress(payload, -zlib.MAX_WBITS)
            headers['Content-Length'] = str(len(payload))
            del headers['Content-Encoding']

    logging.info('%s "%s %s %s" - -', environ['REMOTE_ADDR'], method, url, 'HTTP/1.1')
    #logging.info('request headers=%s', headers)

    if __password__ and __password__ != kwargs.get('password', ''):
        start_response('403 Forbidden', [('Content-Type', 'text/html')])
        yield message_html('403 Wrong password', 'Wrong password(%r)' % kwargs.get('password', ''), 'GoAgent proxy.ini password is wrong!')
        raise StopIteration

    netloc = urlparse.urlparse(url).netloc

    if __hostsdeny__ and netloc.endswith(__hostsdeny__):
        start_response('403 Forbidden', [('Content-Type', 'text/html')])
        yield message_html('403 Hosts Deny', 'Hosts Deny(%r)' % netloc, detail='url=%r' % url)
        raise StopIteration

    if netloc.startswith(('127.0.0.', '::1', 'localhost')):
        start_response('400 Bad Request', [('Content-Type', 'text/html')])
        html = ''.join('<a href="https://%s/">%s</a><br/>' % (x, x) for x in ('google.com', 'mail.google.com'))
        yield message_html('GoAgent %s is Running' % __version__, 'Now you can visit some websites', html)
        raise StopIteration

    fetchmethod = getattr(urlfetch, method, None)
    if not fetchmethod:
        start_response('405 Method Not Allowed', [('Content-Type', 'text/html')])
        yield message_html('405 Method Not Allowed', 'Method Not Allowed: %r' % method, detail='Method Not Allowed URL=%r' % url)
        raise StopIteration

    deadline = URLFETCH_TIMEOUT
    validate_certificate = bool(int(kwargs.get('validate', 0)))
    accept_encoding = headers.get('Accept-Encoding', '')
    errors = []
    for i in xrange(int(kwargs.get('fetchmax', URLFETCH_MAX))):
        try:
            response = urlfetch.fetch(url, payload, fetchmethod, headers, allow_truncated=False, follow_redirects=False, deadline=deadline, validate_certificate=validate_certificate)
            break
        except apiproxy_errors.OverQuotaError as e:
            time.sleep(5)
        except urlfetch.DeadlineExceededError as e:
            errors.append('%r, deadline=%s' % (e, deadline))
            logging.error('DeadlineExceededError(deadline=%s, url=%r)', deadline, url)
            time.sleep(1)
            deadline = URLFETCH_TIMEOUT * 2
        except urlfetch.DownloadError as e:
            errors.append('%r, deadline=%s' % (e, deadline))
            logging.error('DownloadError(deadline=%s, url=%r)', deadline, url)
            time.sleep(1)
            deadline = URLFETCH_TIMEOUT * 2
        except urlfetch.ResponseTooLargeError as e:
            errors.append('%r, deadline=%s' % (e, deadline))
            response = e.response
            logging.error('ResponseTooLargeError(deadline=%s, url=%r) response(%r)', deadline, url, response)
            m = re.search(r'=\s*(\d+)-', headers.get('Range') or headers.get('range') or '')
            if m is None:
                headers['Range'] = 'bytes=0-%d' % int(kwargs.get('fetchmaxsize', URLFETCH_MAXSIZE))
            else:
                headers.pop('Range', '')
                headers.pop('range', '')
                start = int(m.group(1))
                headers['Range'] = 'bytes=%s-%d' % (start, start+int(kwargs.get('fetchmaxsize', URLFETCH_MAXSIZE)))
            deadline = URLFETCH_TIMEOUT * 2
        except urlfetch.SSLCertificateError as e:
            errors.append('%r, should validate=0 ?' % e)
            logging.error('%r, deadline=%s', e, deadline)
        except Exception as e:
            errors.append(str(e))
            if i == 0 and method == 'GET':
                deadline = URLFETCH_TIMEOUT * 2
    else:
        start_response('500 Internal Server Error', [('Content-Type', 'text/html')])
        error_string = '<br />\n'.join(errors)
        if not error_string:
            logurl = 'https://appengine.google.com/logs?&app_id=%s' % os.environ['APPLICATION_ID']
            error_string = 'Internal Server Error. <p/>try <a href="javascript:window.location.reload(true);">refresh</a> or goto <a href="%s" target="_blank">appengine.google.com</a> for details' % logurl
        yield message_html('502 Urlfetch Error', 'Python Urlfetch Error: %r' % method,  error_string)
        raise StopIteration

    #logging.debug('url=%r response.status_code=%r response.headers=%r response.content[:1024]=%r', url, response.status_code, dict(response.headers), response.content[:1024])

    data = response.content
    response_headers = response.headers
    if 'content-encoding' not in response_headers and len(response.content) < URLFETCH_DEFLATE_MAXSIZE and response_headers.get('content-type', '').startswith(('text/', 'application/json', 'application/javascript')):
        if 'gzip' in accept_encoding:
            response_headers['Content-Encoding'] = 'gzip'
            compressobj = zlib.compressobj(zlib.Z_DEFAULT_COMPRESSION, zlib.DEFLATED, -zlib.MAX_WBITS, zlib.DEF_MEM_LEVEL, 0)
            dataio = BytesIO()
            dataio.write('\x1f\x8b\x08\x00\x00\x00\x00\x00\x02\xff')
            dataio.write(compressobj.compress(data))
            dataio.write(compressobj.flush())
            dataio.write(struct.pack('<LL', zlib.crc32(data) & 0xFFFFFFFFL, len(data) & 0xFFFFFFFFL))
            data = dataio.getvalue()
        elif 'deflate' in accept_encoding:
            response_headers['Content-Encoding'] = 'deflate'
            data = zlib.compress(data)[2:-4]
    if data:
         response_headers['Content-Length'] = str(len(data))
    response_headers_data = zlib.compress('\n'.join('%s:%s' % (k.title(), v) for k, v in response_headers.items() if not k.startswith('x-google-')))[2:-4]
    if 'rc4' not in options:
        start_response('200 OK', [('Content-Type', 'image/gif')])
        yield struct.pack('!hh', int(response.status_code), len(response_headers_data))+response_headers_data
        yield data
    else:
        start_response('200 OK', [('Content-Type', 'image/gif'), ('X-GOA-Options', 'rc4')])
        yield struct.pack('!hh', int(response.status_code), len(response_headers_data))
        yield rc4crypt(response_headers_data, rc4_key)
        yield rc4crypt(data, rc4_key)


class LegacyHandler(object):
    """GoAgent 1.x GAE Fetch Server"""
    @classmethod
    def application(cls, environ, start_response):
        return cls()(environ, start_response)

    def __call__(self, environ, start_response):
        self.environ = environ
        self.start_response = start_response
        return self.process_request()

    def send_response(self, status, headers, content, content_type='image/gif'):
        headers['Content-Length'] = str(len(content))
        strheaders = '&'.join('%s=%s' % (k, v.encode('hex')) for k, v in headers.iteritems() if v)
        #logging.debug('response status=%s, headers=%s, content length=%d', status, headers, len(content))
        if headers.get('content-type', '').startswith(('text/', 'application/json', 'application/javascript')):
            data = '1' + zlib.compress('%s%s%s' % (struct.pack('>3I', status, len(strheaders), len(content)), strheaders, content))
        else:
            data = '0%s%s%s' % (struct.pack('>3I', status, len(strheaders), len(content)), strheaders, content)
        self.start_response('200 OK', [('Content-type', content_type)])
        return [data]

    def send_notify(self, method, url, status, content):
        logging.warning('%r Failed: url=%r, status=%r', method, url, status)
        content = '<h2>Python Server Fetch Info</h2><hr noshade="noshade"><p>%s %r</p><p>Return Code: %d</p><p>Message: %s</p>' % (method, url, status, content)
        return self.send_response(status, {'content-type': 'text/html'}, content)

    def process_request(self):
        environ = self.environ
        if environ['REQUEST_METHOD'] == 'GET':
            redirect_url = 'https://%s/2' % environ['HTTP_HOST']
            self.start_response('302 Redirect', [('Location', redirect_url)])
            return [redirect_url]

        data = zlib.decompress(environ['wsgi.input'].read(int(environ['CONTENT_LENGTH'])))
        request = dict((k, v.decode('hex')) for k, _, v in (x.partition('=') for x in data.split('&')))

        method = request['method']
        url = request['url']
        payload = request['payload']

        if __password__ and __password__ != request.get('password', ''):
            return self.send_notify(method, url, 403, 'Wrong password.')

        if __hostsdeny__ and urlparse.urlparse(url).netloc.endswith(__hostsdeny__):
            return self.send_notify(method, url, 403, 'Hosts Deny: url=%r' % url)

        fetchmethod = getattr(urlfetch, method, '')
        if not fetchmethod:
            return self.send_notify(method, url, 501, 'Invalid Method')

        deadline = URLFETCH_TIMEOUT

        headers = dict((k.title(), v.lstrip()) for k, _, v in (line.partition(':') for line in request['headers'].splitlines()))
        headers['Connection'] = 'close'

        errors = []
        for i in xrange(URLFETCH_MAX if 'fetchmax' not in request else int(request['fetchmax'])):
            try:
                response = urlfetch.fetch(url, payload, fetchmethod, headers, False, False, deadline, False)
                break
            except apiproxy_errors.OverQuotaError as e:
                time.sleep(4)
            except urlfetch.DeadlineExceededError as e:
                errors.append('DeadlineExceededError %s(deadline=%s)' % (e, deadline))
                logging.error('DeadlineExceededError(deadline=%s, url=%r)', deadline, url)
                time.sleep(1)
            except urlfetch.DownloadError as e:
                errors.append('DownloadError %s(deadline=%s)' % (e, deadline))
                logging.error('DownloadError(deadline=%s, url=%r)', deadline, url)
                time.sleep(1)
            except urlfetch.InvalidURLError as e:
                return self.send_notify(method, url, 501, 'Invalid URL: %s' % e)
            except urlfetch.ResponseTooLargeError as e:
                response = e.response
                logging.error('ResponseTooLargeError(deadline=%s, url=%r) response(%r)', deadline, url, response)
                m = re.search(r'=\s*(\d+)-', headers.get('Range') or headers.get('range') or '')
                if m is None:
                    headers['Range'] = 'bytes=0-%d' % URLFETCH_MAXSIZE
                else:
                    headers.pop('Range', '')
                    headers.pop('range', '')
                    start = int(m.group(1))
                    headers['Range'] = 'bytes=%s-%d' % (start, start+URLFETCH_MAXSIZE)
                deadline = URLFETCH_TIMEOUT * 2
            except Exception as e:
                errors.append('Exception %s(deadline=%s)' % (e, deadline))
        else:
            return self.send_notify(method, url, 500, 'Python Server: Urlfetch error: %s' % errors)

        headers = response.headers
        if 'content-length' not in headers:
            headers['content-length'] = str(len(response.content))
        headers['connection'] = 'close'
        return self.send_response(response.status_code, headers, response.content)


def forward_socket(local, remote, timeout=60, tick=2, bufsize=8192, maxping=None, maxpong=None, pongcallback=None, trans=None):
    try:
        timecount = timeout
        while 1:
            timecount -= tick
            if timecount <= 0:
                break
            (ins, _, errors) = select.select([local, remote], [], [local, remote], tick)
            if errors:
                break
            if ins:
                for sock in ins:
                    data = sock.recv(bufsize)
                    if trans:
                        data = data.translate(trans)
                    if data:
                        if sock is remote:
                            local.sendall(data)
                            timecount = maxpong or timeout
                            if pongcallback:
                                try:
                                    #remote_addr = '%s:%s'%remote.getpeername()[:2]
                                    #logging.debug('call remote=%s pongcallback=%s', remote_addr, pongcallback)
                                    pongcallback()
                                except Exception as e:
                                    logging.warning('remote=%s pongcallback=%s failed: %s', remote, pongcallback, e)
                                finally:
                                    pongcallback = None
                        else:
                            remote.sendall(data)
                            timecount = maxping or timeout
                    else:
                        return
    except socket.error as e:
        if e[0] not in (10053, 10054, 10057, errno.EPIPE):
            raise
    finally:
        if local:
            local.close()
        if remote:
            remote.close()


def paas_application(environ, start_response):
    if environ['REQUEST_METHOD'] == 'GET':
        start_response('302 Found', [('Location', 'https://www.google.com')])
        raise StopIteration

    wsgi_input = environ['wsgi.input']
    data = wsgi_input.read(2)
    metadata_length, = struct.unpack('!h', data)
    metadata = wsgi_input.read(metadata_length)

    metadata = zlib.decompress(metadata, -zlib.MAX_WBITS)
    headers = {}
    for line in metadata.splitlines():
        if line:
            keyword, value = line.split(':', 1)
            headers[keyword.title()] = value.strip()
    method = headers.pop('G-Method')
    url = headers.pop('G-Url')
    timeout = URLFETCH_TIMEOUT

    kwargs = {}
    any(kwargs.__setitem__(x[2:].lower(), headers.pop(x)) for x in headers.keys() if x.startswith('G-'))

    if __password__ and __password__ != kwargs.get('password'):
        random_host = 'g%d%s' % (int(time.time()*100), environ['HTTP_HOST'])
        conn = httplib.HTTPConnection(random_host, timeout=timeout)
        conn.request('GET', '/')
        response = conn.getresponse(True)
        status_line = '%s %s' % (response.status, httplib.responses.get(response.status, 'OK'))
        start_response(status_line, response.getheaders())
        yield response.read()
        raise StopIteration

    if __hostsdeny__ and urlparse.urlparse(url).netloc.endswith(__hostsdeny__):
        start_response('403 Forbidden', [('Content-Type', 'text/html')])
        yield message_html('403 Forbidden Host', 'Hosts Deny(%s)' % url, detail='url=%r' % url)
        raise StopIteration

    headers['Connection'] = 'close'
    payload = environ['wsgi.input'].read() if 'Content-Length' in headers else None
    if 'Content-Encoding' in headers:
        if headers['Content-Encoding'] == 'deflate':
            payload = zlib.decompress(payload, -zlib.MAX_WBITS)
            headers['Content-Length'] = str(len(payload))
            del headers['Content-Encoding']

    logging.info('%s "%s %s %s" - -', environ['REMOTE_ADDR'], method, url, 'HTTP/1.1')

    if method == 'CONNECT':
        if not socket:
            start_response('403 Forbidden', [('Content-Type', 'text/html')])
            yield message_html('403 Forbidden CONNECT', 'socket not available', detail='`import socket` raised ImportError')
            raise StopIteration
        rfile = wsgi_input.rfile
        sock = rfile._sock
        host, _, port = url.rpartition(':')
        port = int(port)
        remote_sock = socket.create_connection((host, port), timeout=timeout)
        start_response('200 OK', [])
        forward_socket(sock, remote_sock)
        yield 'out'
    else:
        try:
            scheme, netloc, path, params, query, fragment = urlparse.urlparse(url)
            HTTPConnection = httplib.HTTPSConnection if scheme == 'https' else httplib.HTTPConnection
            if params:
                path += ';' + params
            if query:
                path += '?' + query
            conn = HTTPConnection(netloc, timeout=timeout)
            conn.request(method, path, body=payload, headers=headers)
            response = conn.getresponse()

            headers_data = zlib.compress('\n'.join('%s:%s' % (k.title(), v) for k, v in response.getheaders()))[2:-4]
            start_response('200 OK', [('Content-Type', 'image/gif')])
            yield struct.pack('!hh', int(response.status), len(headers_data))+headers_data
            while 1:
                data = response.read(8192)
                if not data:
                    response.close()
                    break
                yield data
        except httplib.HTTPException:
            raise


app = gae_application if urlfetch else paas_application
if bae:
    application = bae.core.wsgi.WSGIApplication(app)
elif sae:
    application = sae.create_wsgi_app(app)
else:
    application = app

if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO, format='%(levelname)s - - %(asctime)s %(message)s', datefmt='[%b %d %H:%M:%S]')
    import gevent
    import gevent.server
    import gevent.wsgi
    import gevent.monkey
    gevent.monkey.patch_all(dns=gevent.version_info[0] >= 1)

    server = gevent.wsgi.WSGIServer(('', int(sys.argv[1])), application)
    logging.info('local paas_application serving at %s:%s', server.address[0], server.address[1])
    server.serve_forever()
