import atexit
from collections import defaultdict, deque
import inspect
import json
import logging
import sys
import schwab


_BUG_REPORT_LOGGING_ACTIVE = 0
_DEFAULT_MAX_TRANSIENT_REDACTIONS = 10_000
_DEFAULT_MAX_LOG_MESSAGES = 10_000
_DEFAULT_MAX_LOG_CHARS = 10 * 1024 * 1024


def get_logger():
    return logging.getLogger(__name__)


class LogRedactor:
    '''
    Collects strings that should not be emitted and replaces them with safe
    placeholders.
    '''

    def __init__(self, *, max_transient_entries=_DEFAULT_MAX_TRANSIENT_REDACTIONS):
        self.redacted_strings = {}
        self.label_counts = defaultdict(int)
        self.max_transient_entries = max_transient_entries
        self._persistent_strings = set()
        self._sorted_redactions = None
        self._transient_limit_reached = False

    def register(self, string, label, *, persistent=True):
        '''
        Registers a string that should not be emitted and the label with with
        which it should be replaced.
        '''
        if string is None:
            return True
        string = str(string)
        if not string:
            return True
        if string in self.redacted_strings:
            if persistent:
                self._persistent_strings.add(string)
            return True

        if (not persistent and
                len(self.redacted_strings) - len(self._persistent_strings) >=
                self.max_transient_entries):
            self._transient_limit_reached = True
            return False

        self.label_counts[label] += 1
        self.redacted_strings[string] = (label, self.label_counts[label])
        if persistent:
            self._persistent_strings.add(string)
        self._sorted_redactions = None
        return True

    @property
    def transient_limit_reached(self):
        return self._transient_limit_reached

    def clear_transient(self):
        self.redacted_strings = {
            string: label
            for string, label in self.redacted_strings.items()
            if string in self._persistent_strings
        }
        self.label_counts = defaultdict(int)
        for label, count in self.redacted_strings.values():
            self.label_counts[label] = max(self.label_counts[label], count)
        self._sorted_redactions = None
        self._transient_limit_reached = False

    def redact(self, msg):
        '''
        Scans the string for secret strings and returns a sanitized version with
        the secrets replaced with placeholders.
        '''
        if self._sorted_redactions is None:
            self._sorted_redactions = sorted(
                    self.redacted_strings.items(),
                    key=lambda item: -len(item[0]))
        for string, label in self._sorted_redactions:
            label, count = label
            msg = msg.replace(string, '<REDACTED {}{}>'.format(
                label, '-{}'.format(count) if
                self.label_counts[label] > 1 else ''))
        return msg


def register_redactions_from_response(resp):
    '''
    Register sensitive values from a response before its body is logged.

    Both successful and error responses are inspected because Schwab may echo
    account identifiers in an error payload. Non-JSON responses are ignored.
    '''
    if not _BUG_REPORT_LOGGING_ACTIVE:
        return None
    if schwab.LOG_REDACTOR.transient_limit_reached:
        return False

    try:
        payload = resp.json()
        if inspect.isawaitable(payload):
            close = getattr(payload, 'close', None)
            if close is not None:
                close()
            return True
        return register_redactions(payload, persistent=False)
    except (json.decoder.JSONDecodeError, UnicodeDecodeError):
        return True


def register_redactions(obj, key_path=None,
                        bad_patterns=(
                            'auth', 'acl', 'displayname', 'id', 'key', 'token',
                            'accountnumber', 'hashvalue', 'firstname',
                            'lastname', 'nickname'),
                        whitelisted=frozenset((
                            'requestid',
                            'token_type',
                            'legid',
                            'bidid',
                            'askid',
                            'lastid',
                            'bidsizeinlong',
                            'bidsizeindouble',
                            'bidpriceindouble')),
                        *, persistent=True):
    '''
    Recursively iterates through the leaf elements of ``obj`` and registers
    elements with keys matching a blacklist with the global ``Redactor``.
    '''
    if key_path is None:
        key_path = []

    if isinstance(obj, list):
        for idx, value in enumerate(obj):
            key_path.append(str(idx))
            success = register_redactions(
                    value, key_path, bad_patterns, whitelisted,
                    persistent=persistent)
            key_path.pop()
            if not success:
                return False
    elif isinstance(obj, dict):
        for key, value in obj.items():
            key_path.append(key)
            success = register_redactions(
                    value, key_path, bad_patterns, whitelisted,
                    persistent=persistent)
            key_path.pop()
            if not success:
                return False
    else:
        if key_path:
            last_key = key_path[-1].lower()
            if last_key in whitelisted:
                return True
            elif any(bad in last_key for bad in bad_patterns):
                return schwab.LOG_REDACTOR.register(
                        obj, '-'.join(key_path), persistent=persistent)
    return True


def enable_bug_report_logging():
    '''
    Turns on bug report logging. Will collect all logged output, redact out
    anything that should be kept secret, and emit the result at program exit.

    Notes:
     * This method does a best effort redaction. Never share its output
       without verifying that all secret information is properly redacted.
     * Because this function records all logged output, it has a performance
       penalty. It should not be called in production code.
     * Capture is bounded. If the limits are reached, older messages are
       discarded and response bodies that cannot be safely redacted are
       omitted.
    '''
    _enable_bug_report_logging()


def _enable_bug_report_logging(
        output=sys.stderr, loggers=None,
        max_log_messages=_DEFAULT_MAX_LOG_MESSAGES,
        max_log_chars=_DEFAULT_MAX_LOG_CHARS):
    '''
    Module-internal version of :func:`enable_bug_report_logging`, intended for
    use in tests.
    '''
    if loggers is None:
        loggers = (
            schwab.auth.get_logger(),
            schwab.client.base.get_logger(),
            schwab.streaming.get_logger(),
            get_logger())

    class RecordingHandler(logging.Handler):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            self.messages = deque()
            self.total_chars = 0
            self.dropped_messages = 0

        def emit(self, record):
            message = self.format(record)
            if len(message) > max_log_chars:
                message = message[:max_log_chars]

            while self.messages and (
                    len(self.messages) >= max_log_messages or
                    self.total_chars + len(message) > max_log_chars):
                removed = self.messages.popleft()
                self.total_chars -= len(removed)
                self.dropped_messages += 1

            if max_log_messages <= 0 or max_log_chars <= 0:
                self.dropped_messages += 1
                return

            self.messages.append(message)
            self.total_chars += len(message)

    handler = RecordingHandler()
    handler.setFormatter(logging.Formatter(
        '[%(filename)s:%(lineno)s:%(funcName)s] %(message)s'))

    logger_levels = {logger: logger.level for logger in loggers}
    for logger in loggers:
        logger.setLevel(logging.DEBUG)
        logger.addHandler(handler)

    global _BUG_REPORT_LOGGING_ACTIVE
    _BUG_REPORT_LOGGING_ACTIVE += 1

    logs_written = False

    def write_logs():
        nonlocal logs_written
        if logs_written:
            return
        logs_written = True

        try:
            for logger in loggers:
                logger.removeHandler(handler)
                logger.setLevel(logger_levels[logger])

            if getattr(output, 'closed', False):
                return

            print(file=output)
            print(' ### BEGIN REDACTED LOGS ###', file=output)
            print(file=output)

            if handler.dropped_messages:
                print('<{} older log messages omitted>'.format(
                        handler.dropped_messages), file=output)
            for msg in handler.messages:
                msg = schwab.LOG_REDACTOR.redact(msg)
                print(msg, file=output)
        except BrokenPipeError:
            # Bug-report output is best-effort, especially from an atexit
            # callback whose output may be connected to a closed pipe.
            pass
        finally:
            global _BUG_REPORT_LOGGING_ACTIVE
            _BUG_REPORT_LOGGING_ACTIVE -= 1
            if not _BUG_REPORT_LOGGING_ACTIVE:
                schwab.LOG_REDACTOR.clear_transient()
    atexit.register(write_logs)

    get_logger().debug('schwab-api version %s', schwab.__version__)

    return write_logs
