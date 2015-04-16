"""A logger for handling XTF specific log mechanisms.

This file defines a logging.LoggerAdapter and logging.Handler, see below.

Any module can call logging.getLogger('xtf.something') and it will by default
show up in the XTF proto.
"""

import logging
import os
import re
import traceback

from proto import xtf_pb2

# Logging setup
XTF_LOGGER_PREFIX = 'xtf'


class MacAddressLogFilter(logging.Filter):
  """A filter which redacts mac addresses if it sees one."""

  MAC_REPLACE_RE = re.compile(r"""
        ((?:[\dA-F]{2}:){3})       # 3-part prefix, f8:8f:ca means google
        (?:[\dA-F]{2}(:|\b)){3}    # the remaining octets
        """, re.IGNORECASE | re.VERBOSE)
  MAC_REPLACEMENT = r'\1<REDACTED>'

  def __init__(self):
    super(MacAddressLogFilter, self).__init__()

  def filter(self, record):
    if self.MAC_REPLACE_RE.search(record.getMessage()):
      # Update all the things to have no mac address in them
      record.msg = self.MAC_REPLACE_RE.sub(self.MAC_REPLACEMENT, record.msg)
      record.args = tuple([
          self.MAC_REPLACE_RE.sub(self.MAC_REPLACEMENT, str(arg))
          if isinstance(arg, basestring)
          else arg for arg in record.args])
    return True


# We use one shared instance of this, it has no internal state.
MAC_FILTER = MacAddressLogFilter()


class XTFLogger(logging.LoggerAdapter):
  """A standard interface for providing additional logging methods.

  This class is passed to a phase via the 'logger' attribute of the phase_data
  object (the first argument passed to test phases).  It provides standard
  logging methods (debug, info, log, warning, error, critical, exception).  It
  also provides an additional XTF specific logging mechanism for logging
  failure codes.
  """

  def __init__(self, test_run, cell_number, prefix=XTF_LOGGER_PREFIX):
    super(XTFLogger, self).__init__(
        logging.getLogger(prefix).getChild('cells.%s' % cell_number),
        {'cell_number': cell_number})
    self._test_run = test_run
    self._handler = XTFLoggerHandler(test_run)
    self.logger.setLevel(logging.DEBUG)
    self.logger.addFilter(MAC_FILTER)
    self.logger.addHandler(self._handler)

  def __del__(self):
    self.logger.removeHandler(self._handler)

  def __str__(self):
    return '<XTFLogger for cell %s: %s>' % (self.extra['cell_number'],
                                            self._test_run.dut_serial)
  __repr__ = __str__

  def AddFailureCode(self, code, details):
    """Adds a failure code to the proto.

    This is useful if a test is going to return from a phase either via ABORT or
    FAIL so that we can make some sense as to why they bailed.

    Args:
      code: The failure code, should be a single word (no spaces) indicating
          what caused the failure. Something like: NO_WIFI_SIGNAL.
      details: An optional full description of the failure.

    Raises:
      ValueError: If code is not provided.
    """
    if not code:
      raise ValueError('Invalid Failure Code', code)

    fc = self._test_run.failure_codes.add()
    fc.code = code
    fc.details = details


class XTFLoggerHandler(logging.Handler):
  """A handler to save logs to an XTF TestRun proto."""

  def __init__(self, test_run):
    super(XTFLoggerHandler, self).__init__()
    self.setLevel(logging.DEBUG)
    self._test_run = test_run

  def emit(self, record):  # pylint: disable=g-bad-name
    """Save a logging.LogRecord to our test run proto.

    LogRecords carry a significant amount of information with them including the
    logger name and level information.  This allows us to be a little clever
    about what we store so that filtering can occur on the client.

    Args:
      record: A logging.LogRecord to log.
    """
    proto = self._test_run.test_logs.add()
    proto.timestamp_millis = int(record.created * 1000)
    proto.levelno = record.levelno
    proto.logger_name = record.name
    message = record.getMessage()
    if record.exc_info:
      message += '\n' + ''.join(traceback.format_exception(
          *record.exc_info))
    proto.log_message = message.decode('utf8', 'replace')
    proto.log_source = os.path.basename(record.pathname)
    proto.lineno = record.lineno
    proto.level = xtf_pb2.TestRunLogMessage.Level.Value(record.levelname)


# Add our filter to the root loggers we know about, and initialize them.
logging.getLogger().addFilter(MAC_FILTER)
logging.getLogger(XTF_LOGGER_PREFIX).addFilter(MAC_FILTER)
logging.getLogger(XTF_LOGGER_PREFIX).getChild('cells').addFilter(MAC_FILTER)
