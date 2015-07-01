from __future__ import absolute_import
from __future__ import division
from __future__ import unicode_literals

import codecs
import re
import sys
from twisted.internet import defer, error, protocol

# This code has been adapted from Lib/os.py in the Python source tree (sha1
# 265e36e277f3). The fragment was copied from pyexiftool by Sven Marnach
# released under the GPL and the revised BSD lisence.
# https://github.com/smarnach/pyexiftool
def _fscodec():
    encoding = sys.getfilesystemencoding()
    errors = "strict"
    if encoding != "mbcs":
        try:
            codecs.lookup_error("surrogateescape")
        except LookupError:
            pass
        else:
            errors = "surrogateescape"

    def fsencode(filename):
        """
        Encode filename to the filesystem encoding with 'surrogateescape' error
        handler, return bytes unchanged. On Windows, use 'strict' error handler if
        the file system encoding is 'mbcs' (which is the default encoding).
        """
        if isinstance(filename, bytes):
            return filename
        else:
            return filename.encode(encoding, errors)

    return fsencode

fsencode = _fscodec()
del _fscodec

class ExiftoolProtocol(protocol.Protocol):

    MAX_LENGTH = 2**32
    _buffer = b''
    _pattern = re.compile(r'^{ready([0-9]+)}$', re.MULTILINE)

    def __init__(self, default_args = ()):
        self.default_args = tuple(default_args)
        self._queue = {}
        self._stopped = None
        self._tag = 0


    def dataReceived(self, data):
        """
        Parses chunks of bytes into responses.
        """
        l = len(self._buffer) + len(data)
        if (l > self.MAX_LENGTH):
            self.lengthLimitExceeded(l)
        self._buffer += data

        start = 0
        for match in self._pattern.finditer(self._buffer):
            # The start of the sentinel marks the end of the response.
            end = match.start()
            tag = int(match.group(1))
            self.responseReceived(self._buffer[start:end], tag)

            # Advance start position to the beginning of the next line
            start = match.end() + 1

        if start:
            self._buffer = self._buffer[start:]


    def responseReceived(self, data, tag):
        d = self._queue.pop(tag)
        d.callback(data)


    def lengthLimitExceeded(self, length):
        """
        Callback invoked when the incomming data would exceed the length limit
        appended to the buffer. The default implementation disconnects the
        transport.

        @param length: The total number of bytes
        @type length: C{int}
        """
        self.transport.loseConnection()


    def execute(self, *args):
        self._tag += 1

        safe_args = map(fsencode, self.default_args + tuple(args) + (b'-execute' + str(self._tag), b''))
        self.transport.write(b"\n".join(safe_args))

        d = defer.Deferred()
        self._queue[self._tag] = d

        return d


    def loseConnection(self):
        if self._stopped:
            d = self._stopped
        elif self.connected:
            d = defer.Deferred()
            self._stopped = d
            self.transport.write(b"\n".join((b'-stay_open', b'False', b'')))
            self.transport.loseConnection()
        else:
            d = defer.fail(RuntimeError("not connected"))

        return d


    def connectionLost(self, reason):
        self.connected = 0
        if self._stopped:
            self._stopped.callback(self if reason.check(error.ConnectionDone) else reason)
            self._stopped = None
        else:
            reason.raiseException()
