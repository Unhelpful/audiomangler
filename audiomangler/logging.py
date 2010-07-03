# -*- coding: utf-8 -*-
from twisted.python import log, failure
from audiomangler import Config
import os, sys, atexit

try:
    from cStringIO import StringIO
except ImportError:
    from StringIO import StringIO

loglevels = dict(ERROR=0, WARNING=1, INFO=2, DEBUG=3)
locals().update(loglevels)
loglevels.update(map(reversed, loglevels.items()))

class FilteredFileLogObserver(log.FileLogObserver):
    def __init__(self, f, loglevel=INFO):
        self.output = f
        if isinstance(loglevel, basestring):
            loglevel = loglevels[loglevel]
        self.loglevel = loglevel

    def emit(self, eventDict):
        if eventDict.get('loglevel',DEBUG) > self.loglevel:
            return
        encoding = sys.stdout.encoding
        if eventDict['isError'] and 'failure' in eventDict:
            text = log.textFromEventDict(eventDict)
        elif eventDict['message']:
            text = ' '.join(s.encode(encoding,'replace') if isinstance(s,unicode) else s for s in eventDict['message'])
        elif 'format' in eventDict or 'consoleformat' in eventDict:
            fmt = eventDict.get('format',eventDict.get('consoleformat'))
            text = (fmt % eventDict).encode(encoding,'replace')
        else:
            text = log.textFromEventDict(eventDict)
        timeStr = self.formatTime(eventDict['time'])
        self.output.write(timeStr + ' [' + loglevels[eventDict['loglevel']].ljust(7) + '] ' + text + '\n')

class FilteredConsoleLogObserver:
    def __init__(self, loglevel=INFO):
        self.loglevel = loglevel

    def start(self):
        log.addObserver(self.emit)

    def stop(self):
        log.removeObserver(self.emit)

    def emit(self, eventDict):
        if eventDict.get('loglevel',DEBUG) > self.loglevel:
            return
        encoding = sys.stdout.encoding
        if eventDict['isError'] and 'failure' in eventDict:
            text = log.textFromEventDict(eventDict)
        elif eventDict['message']:
            text = ''.join(s.encode(encoding,'replace') if isinstance(s,unicode) else s for s in eventDict['message'])
        elif 'format' in eventDict or 'consoleformat' in eventDict:
            fmt = eventDict.get('consoleformat',eventDict.get('format'))
            text = (fmt % eventDict).encode(encoding,'replace')
        else:
            text = log.textFromEventDict(eventDict)
        sys.stdout.write(text + '\n')
        sys.stdout.flush()

collector = None
logfile = None
logout = None

def get_level(x, default=ERROR):
    try:
        return int(x)
    except ValueError:
        pass
    try:
        return loglevels[x]
    except KeyError:
        return default

def err(*msg, **kwargs):
    global collector, logfile
    if 'nologerror' not in kwargs:
        if collector is None:
            try:
                collector = FilteredFileLogObserver(StringIO(), ERROR)
                collector.start()
            except: pass
        if logfile is None:
            try:
                logfile = FilteredFileLogObserver(open(Config.get('logfile','audiomangler-%d.log' % os.getpid()), 'wb'), get_level(Config['loglevel']))
                logfile.start()
            except: pass
    kwargs['loglevel'] = ERROR
    if msg and isinstance(msg[0],(failure.Failure,Exception)):
        log.err(*msg, **kwargs)
    else:
        log.msg(*msg, **kwargs)

def msg(*msg, **kwargs):
    global logfile
    kwargs.setdefault('loglevel',DEBUG)
    if kwargs['loglevel'] == ERROR:
        err(*msg, **kwargs)
    else:
        if Config['logfile'] and logfile is None and kwargs['loglevel'] <= get_level(Config['loglevel']):
            try:
                logfile = FilteredFileLogObserver(open(Config['logfile'], 'wb'), Config['loglevel'])
                logfile.start()
            except: pass
        log.msg(*msg, **kwargs)

def fatal(*msg, **kwargs):
    err(*msg, **kwargs)
    sys.exit()

def cleanup():
    if logout:
        sys.stdout.flush()
        logout.stop()
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

try:
    logout = FilteredConsoleLogObserver(Config['consolelevel'])
    logout.start()
    if log.defaultObserver:
        log.defaultObserver.stop()
        log.defaultObserver = None
except:
    pass

atexit.register(cleanup)

__all__ = ['err','msg','fatal','ERROR','WARNING','INFO','DEBUG']