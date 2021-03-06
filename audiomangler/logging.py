# -*- coding: utf-8 -*-
from twisted.python import log, failure
from audiomangler.config import Config
import os, sys, atexit

try:
    from cStringIO import StringIO
except ImportError:
    from StringIO import StringIO

loglevels = dict(ERROR=0, WARNING=1, INFO=2, VERBOSE=3, DEBUG=4)
loglevels.update(map(reversed, loglevels.items()))
ERROR, WARNING, INFO, VERBOSE, DEBUG = range(5)

class FilteredFileLogObserver(log.FileLogObserver):
    def __init__(self, f, loglevel=VERBOSE):
        self.output = f
        self.loglevel = get_level(loglevel, VERBOSE)

    def emit(self, eventDict):
        if 'nologerror' in eventDict: return
        if '_noignore' not in eventDict and not eventDict['isError']: return
        if eventDict.get('loglevel', DEBUG) > self.loglevel:
            return
        encoding = sys.stdout.encoding
        if eventDict['isError'] and 'failure' in eventDict:
            text = log.textFromEventDict(eventDict)
        elif eventDict['message']:
            text = ' '.join(s.encode(encoding, 'replace') if isinstance(s, unicode) else s for s in eventDict['message'])
        elif 'format' in eventDict or 'consoleformat' in eventDict:
            fmt = eventDict.get('format', eventDict.get('consoleformat'))
            text = (fmt % eventDict).encode(encoding, 'replace')
        else:
            text = log.textFromEventDict(eventDict)
        timeStr = self.formatTime(eventDict['time'])
        if isinstance(self.output, basestring):
            try:
                self.output = open(self.output, 'wb')
            except:
                pass
        self.output.write(timeStr + ' [' + loglevels[eventDict.get('loglevel', ERROR)].ljust(7) + '] ' + text + '\n')
        self.output.flush()

class FilteredConsoleLogObserver(log.FileLogObserver):
    timeFormat = '[%H:%M:%S] '
    def __init__(self, loglevel=INFO):
        self.loglevel = get_level(loglevel, INFO)

    def start(self):
        log.addObserver(self.emit)

    def stop(self):
        log.removeObserver(self.emit)

    def emit(self, eventDict):
        if '_noignore' not in eventDict and not eventDict['isError']: return

        if eventDict.get('loglevel', DEBUG) > self.loglevel:
            return
        encoding = sys.stdout.encoding
        if eventDict['isError'] and 'failure' in eventDict:
            text = log.textFromEventDict(eventDict)
        elif eventDict['message']:
            text = ''.join(s.encode(encoding, 'replace') if isinstance(s, unicode) else s for s in eventDict['message'])
        elif 'format' in eventDict or 'consoleformat' in eventDict:
            fmt = eventDict.get('consoleformat', eventDict.get('format'))
            text = (fmt % eventDict).encode(encoding, 'replace')
        else:
            text = log.textFromEventDict(eventDict)
        timeStr = self.formatTime(eventDict['time'])
        sys.stdout.write(timeStr + text + '\n')
        sys.stdout.flush()

collector = None
logfile = None
logconsole = None

def get_level(level, default=ERROR):
    try:
        return int(level)
    except ValueError:
        pass
    if isinstance(level, basestring):
        level = level.upper()
        levels = [loglevels[k] for k in loglevels.keys() if isinstance(k, basestring) and k.startswith(level)]
        if len(levels) == 1:
            return levels[0]
    return default

def init_logs():
    global collector, logconsole, logfile
    if logconsole is None:
        logconsole = FilteredConsoleLogObserver(Config['consolelevel'])
        logconsole.start()

    if collector is None:
        collector = FilteredFileLogObserver(StringIO(), ERROR)
        collector.start()

    if logfile is None:
        logfile = FilteredFileLogObserver(Config.get('logfile', 'audiomangler-%d.log' % os.getpid()), get_level(Config['loglevel']))
        logfile.start()

def err(*msg, **kwargs):
    init_logs()
    kwargs['loglevel'] = ERROR
    if msg and isinstance(msg[0], (failure.Failure, Exception)):
        log.err(_noignore=1, *msg, **kwargs)
    else:
        log.msg(_noignore=1, *msg, **kwargs)

def msg(*msg, **kwargs):
    init_logs()
    kwargs.setdefault('loglevel', DEBUG)
    if kwargs['loglevel'] == ERROR:
        err(*msg, **kwargs)
    else:
        log.msg(_noignore=1, *msg, **kwargs)

def fatal(*msg, **kwargs):
    err(*msg, **kwargs)
    sys.exit()

def cleanup():
    if logconsole:
        sys.stdout.flush()
        logconsole.stop()
    if collector:
        collector.output.flush()
        collector.stop()
        text = collector.output.getvalue()
        if text:
            print "The following errors occurred:"
            print text
            print "The above errors may also have been reported during processing."
            if logfile:
                logfile.output.flush()
                logfile.stop()
                print "Errors are also recorded in the logfile '%s'." % os.path.abspath(logfile.output.name)
    sys.stdout.flush()

if log.defaultObserver:
    log.defaultObserver.stop()
    log.defaultObserver = None

atexit.register(cleanup)

__all__ = ['err', 'msg', 'fatal', 'ERROR', 'WARNING', 'INFO', 'VERBOSE', 'DEBUG']