###########################################################################
#    Copyright (C) 2008 by Andrew Mahone                                      
#    <andrew.mahone@gmail.com>                                                             
#
# Copyright: See COPYING file that comes with this distribution
#
###########################################################################
import os
import sys
from subprocess import Popen, CalledProcessError
from threading import Thread, RLock
from types import FunctionType, GeneratorType
threadpool = None

def synchronized(*locks):
    def decorator(func):
        def proxy(self, *args, **kw):
            for lock in locks:
                lock = getattr(self,lock,None)
                if lock is not None:
                    lock.acquire()
            try:
                return func(self, *args, **kw)
            finally:
                for lock in locks:
                    lock = getattr(self,lock,None)
                    if lock is not None:
                        lock.release()
        return proxy
    return decorator

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
            self.runbg()
            return self
        else:
            self.runfg()

class FuncTask(BaseTask):
    def __init__(self, target=None, args=(), kwargs=(), background=True):
        self._lock = RLock()
        BaseTask.__init__(self, target, args, kwargs, background)

    run = synchronized('_lock')(BaseTask.run)

    def runfg(self):
        self.target(*self.args, **self.kwargs)

    @synchronized('_lock')
    def runbg(self):
        self.thread = Thread(target=self.runsaveexc)
        self.thread.start()

    def runsaveexc(self):
        try:
            self.runfg()
        except Exception:
            self.exc_info = sys.exc_info()

    @synchronized('_lock')
    def wait(self):
        if not self.started:
            return False
        elif not hasattr(self,'thread'):
            return False
        self.thread.join()
        if hasattr(self, 'exc_info'):
            sys.excepthook(*exc_info)
        return True

    @synchronized('_lock')
    def poll(self):
        if not self.started:
            return False
        elif not hasattr(self,'thread'):
            return False
        elif self.thread.isAlive():
            return False
        elif hasattr(self, 'exc_info'):
            sys.excepthook(*exc_info)
        return True

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

__all__ = ['FuncTask','CLITask','TaskSet']