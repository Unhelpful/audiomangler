# -*- coding: utf-8 -*-
###########################################################################
#    Copyright (C) 2008 by Andrew Mahone                                      
#    <andrew.mahone@gmail.com>                                                             
#
# Copyright: See COPYING file that comes with this distribution
#
###########################################################################
import os
import sys
import atexit
from types import FunctionType, GeneratorType
from twisted.internet import threads, defer
from twisted.python import failure

if 'twisted.internet.reactor' not in sys.modules:
    for reactor in ('kqreactor','epollreactor','pollreactor','selectreactor'):
        try:
            r = __import__('twisted.internet.' + reactor, fromlist=[reactor])
            r.install()
            break
        except ImportError: pass

from twisted.internet import reactor

def cleanup():
    if reactor.running: reactor.stop()

atexit.register(cleanup)

threadpool = None

class Clear(object):
    def __new__(cls,*args,**kw):
        return cls

class BaseTask(object):
    def __init__(self, target=None, args=(), kwargs=(), background=True):
        self.started = False
        self.target = target
        self.args=list(args)
        self.kwargs = dict(kwargs)
        self.background = background

    def run(self):
        self.started = True
        if self.background:
            return self.runbg()
        else:
            return self.runfg()

class FuncTask(BaseTask):
    def __init__(self, target=None, args=(), kwargs=(), background=True):
        BaseTask.__init__(self, target, args, kwargs, background)

    def runfg(self):
        try:
            self.target(*self.args, **self.kwargs)
            self.deferred =  defer.succeed(self)
            return self.deferred
        except:
            self.deferred = defer.failure(failure.Failure())
            return self.deferred

    def runbg(self):
        self.deferred = threads.deferToThread(self.target, *self.args, **self.kwargs)
        return self.deferred

class CLITask(BaseTask):
    def __init__(self, target=None, args=(), stdin=None, stdout=None, stderr=None, kwargs=(), background=True):
        args = list(args)
        if target:
            args.insert(0,target)
        BaseTask.__init__(self, target, args, background=background)
        self.stdin = stdin
        self.stdout = stdout
        self.stderr = stderr

    def runbg(self):
        if isinstance(self.stdin, basestring):
            self.stdin = file(self.stdin, 'rb')
        if isinstance(self.stdout, basestring):
            self.stdout = file(self.stdout, 'wb')
        if isinstance(self.stderr, basestring):
            self.stderr = file(self.stderr, 'wb')
        self.proc = Popen(executable=self.target, args=self.args, stdin=self.stdin, stderr=self.stderr, stdout=self.stdout)

    def runfg(self):
        self.runbg()
        self.wait()

    def wait(self):
        try:
            if not self.started:
                return False
            if not hasattr(self,'proc'):
                return False
            ret = self.proc.wait()
            if ret != 0:
                raise CalledProcessError(ret,self.args)
        finally:
            for f in (self.stdin, self.stdout, self.stderr):
                if isinstance(f,int) and f >2:
                    os.close(f)
                if isinstance(f,file) and f not in (sys.stdin, sys.stdout, sys.stderr):
                    f.close()

    def poll(self):
        if not self.started:
            return False
        if not hasattr(self,'proc'):
            return False
        ret = self.proc.poll()
        if ret is None:
            return False
        elif ret != 0:
            raise CalledProcessError(ret)

class TaskSet(FuncTask):
    def __init__(self, tasks=(), background=True):
        FuncTask.__init__(self, background=background)
        self.tasks = list(tasks)

    def clear(self):
        while self.bgprocs:
            t = self.bgprocs.pop()
            t.wait()

    def runfg(self):
        self.bgprocs = set()
        for t in self.tasks:
            if isinstance(t, BaseTask):
                t = t.run()
                if isinstance(t, BaseTask):
                    self.bgprocs.add(t)
            elif t is Clear:
                self.clear()
        self.clear()

__all__ = ['FuncTask','CLITask','TaskSet','reactor']
