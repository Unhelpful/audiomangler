# -*- coding: utf-8 -*-
###########################################################################
#    Copyright (C) 2008 by Andrew Mahone
#    <andrew.mahone@gmail.com>
#
# Copyright: See COPYING file that comes with this distribution
#
###########################################################################
#pylint: disable=E1101,E1103
import os
import sys
import inspect
from types import FunctionType, GeneratorType
from twisted.internet import defer, protocol, error, fdesc
from twisted.internet.threads import deferToThread
from twisted.python import failure
from functools import wraps
from multiprocessing import cpu_count
from audiomangler.config import Config
from audiomangler.util import ClassInitMeta
from audiomangler.logging import err
from decorator import decorator

if 'twisted.internet.reactor' not in sys.modules:
    for reactor in 'kqreactor', 'epollreactor', 'pollreactor', 'selectreactor':
        try:
            r = __import__('twisted.internet.' + reactor, fromlist=[reactor])
            r.install()
            break
        except ImportError: pass

from twisted.internet import reactor

try:
    from twisted.internet.processes import deferToProcess as callDeferred
except ImportError:
    from twisted.internet.threads import deferToThread as callDeferred

@decorator
def background_task(func, self, *args, **kwargs):
    self._register()
    reactor.callWhenRunning(func, self, *args, **kwargs)
    if not reactor.running:
        reactor.run()

@decorator
def queue_task(func, self, *args, **kwargs):
    self._register()
    reactor.callWhenRunning(func, self, *args, **kwargs)

#def background_task(func):
    #argspec = inspect.getargspec(func)
    #env = {}
    #code = """
#def decorate(func):
    #def proxy%s:
        #self._register()
        #reactor.callWhenRunning(%s)
        #if not reactor.running:
            #reactor.run()
    #return proxy""" % (inspect.formatargspec(*argspec), ', '.join(['func', 'self'] + ['%s=%s' % (arg, arg) for arg in argspec.args[1:]]))
    #exec code in globals(), env
    #return wraps(func)(env['decorate'](func))


def chain(f):
    @wraps(f)
    def proxy(out):
        f(out)
        return out
    return proxy

def chainDeferreds(d1, d2):
    d1.addCallbacks(chain(d2.callback), chain(d2.errback))

class BaseTask(object):
    "Base class for other Task types, providing handling for Task registration and cleanup, and ensuring that the first task is started inside the reactor."
    __metaclass__ = ClassInitMeta
    @classmethod
    def __classinit__(cls, name, bases, cls_dict):
        _run = getattr(cls, 'run', None)
        if _run:
            cls._run = _run
            run = background_task(_run.im_func)
            if not run.__doc__:
                run.__doc__ = "Start the task, returning status via <task>.deferred callbacks when the task completes, and start reactor if not running"
            cls.run = run
            queue = queue_task(_run.im_func)
            if not queue.__doc__:
                queue.__doc__ = "Queue the task to be started by reactor, returning status via <task>.deferred callbacks when the task completes."
            cls.queue = queue


    __slots__ = 'deferred', 'args', 'parent'
    __bg_tasks = set()
    def __init__(self, *args):
        self.args = args
        self.deferred = defer.Deferred()
        self.deferred.addBoth(self._complete)

    def _register(self):
        self.__class__.__bg_tasks.add(self)

    def _complete(self, out):
        if isinstance(out, failure.Failure):
            import traceback
            traceback.print_tb(out.getTracebackObject())
        if self.deferred.callbacks:
            self.deferred.addBoth(self._complete)
            return out
        parent = getattr(self, 'parent', None)
        try:
            if parent:
                parent.complete_sub(out, self)
        finally:
            if self in self.__bg_tasks:
                self.__bg_tasks.remove(self)
            if not self.__bg_tasks:
                reactor.stop()
        return out

class FuncTask(BaseTask):
    "Task that calls a Python function with the specified arguments when run."
    __slots__ = 'func', 'func_deferred', 'kwargs'
    def __init__(self, func, *args, **kwargs):
        self.func = func
        self.kwargs = kwargs
        super(FuncTask, self).__init__(*args) 

    def run(self):
        self.func_deferred = callDeferred(self.func, *self.args, **self.kwargs)
        self.func_deferred.chainDeferred(self.deferred)

class CLIProcessProtocol(protocol.ProcessProtocol):
    "Support class for CLITask, saving output from the spawned process and triggering task callbacks on exit."
    def __init__(self, task):
        self._out = []
        self._err = []
        self.task = task

    def outReceived(self, data):
        self._out.append(data)

    def errReceived(self, data):
        self._err.append(data)

    def processEnded(self, reason):
        (self.task.out, self.task.err) = map(''.join, (self._out, self._err))
        if reason.check(error.ProcessDone) and not (reason.value.status or reason.value.signal):
            self.task.deferred.callback((self.task.out, self.task.err))
        else:
            self.task.deferred.errback(reason)

class CLITask(BaseTask):
    "Task subclass to spawn subprocesses, with the executable and arguments passed on initialization. The keyword arguments stdin, stdout, and stderr may be used to provide a file or file descriptor for the stdin of the first process in the pipeline, or the stdout and stderr of the last process."
    __slots__ = 'proc', 'out', 'err', 'exit', 'stdin', 'stdout', 'stderr'
    def __init__(self, *args, **kwargs):
        for arg in 'stdin', 'stdout', 'stderr':
            if arg in kwargs:
                setattr(self, arg, kwargs[arg])
        super(CLITask, self).__init__(*args)

    def run(self, stdin=None, stdout=None, stderr=None):
        "Start the task, returning status via <task>.deferred callbacks when the task completes. The keyword arguments stdin, stdout, and stderr may be used to override the ones provided at initialization."
        childFDs = {}
        if stdin is not None:
            childFDs[0] = stdin
        else:
            childFDs[0] = getattr(self, 'stdin', 'w')
        if stdout is not None:
            childFDs[1] = stdout
        else:
            childFDs[1] = getattr(self, 'stdout', 'r')
        if stderr is not None:
            childFDs[2] = stderr
        else:
            childFDs[2] = getattr(self, 'stderr', 'r')
        d = deferToThread(self._setup, childFDs)
        d.addCallback(self._spawn)
        d.addErrback(self._fail)

    def _setup(self, childFDs):
        closeFDs = []
        for key, value in childFDs.items():
            if isinstance(value, basestring) and (value.startswith('w:') or value.startswith('r:')):
                mode, path = value.split(':', 1)
                mode = os.O_WRONLY|os.O_CREAT if mode == 'w' else os.O_RDONLY
                closeFDs.append(os.open(path, mode))
                childFDs[key] = closeFDs[-1]
        return (childFDs, closeFDs)

    def _fail(self, failure):
        err(failure)

    def _spawn(self, FDs):
        childFDs, closeFDs = FDs
        self.proc = reactor.spawnProcess(CLIProcessProtocol(self), executable=self.args[0], args=self.args, childFDs = childFDs)
        for fd in closeFDs:
            os.close(fd)

class BaseSetTask(BaseTask):
    "Base class for Tasks that run a set of other Tasks."
    slots = 'subs', 'main'
    def __init__(self, tasks, **kwargs):
        super(BaseSetTask, self).__init__()
        self.subs = set()
        if 'main' in kwargs:
            main = kwargs.pop('main')
            assert isinstance(main, (int, BaseTask))
            if isinstance(main, int):
                main = tasks[main]
            self.main = main
        self.args = tasks

    def run_sub(self, sub, *args, **kwargs):
        self.subs.add(sub)
        sub.parent = self
        sub.run(*args, **kwargs)

    def complete_sub(self, out, sub):
        self.subs.remove(sub)
        return out

class CLIPipelineTask(BaseSetTask):
    "Task comprised of a series of subprocesses, with stdout of each connected to stdin of the previous one. The keyword arguments stdin, stdout, and stderr may be used to provide a file or file descriptor for the stdin of the first process in the pipeline, or the stdout and stderr of the last process."
    __slots__ = 'tasks', 'stdin', 'stdout', 'stderr'
    def __init__(self, tasks, **kwargs):
        self.tasks = []
        for arg in 'stdin', 'stdout', 'stderr':
            if arg in kwargs:
                setattr(self, arg, kwargs[arg])
        super(CLIPipelineTask, self).__init__(tasks)

    def run(self, stdin=None, stdout=None, stderr=None):
        "Start the task, returning status via <task>.deferred callbacks when the task completes. The keyword arguments stdin, stdout, and stderr may be used to override the ones provided at initialization."
        if stdin is None:
            stdin = getattr(self, 'stdin', None)
        if stdout is None:
            stdout = getattr(self, 'stdout', None)
        if stderr is None:
            stderr = getattr(self, 'stderr', None)
        fd = stdin
        prev = None
        for task in self.args:
            if prev:
                self.run_sub(prev, stdin=fd)
                fd = prev.proc.pipes.pop(1)
                fdesc.setBlocking(fd)
                fd.stopReading()
                fd = fd.fileno()
            prev = task
        if prev:
            self.run_sub(prev, stdin=fd, stdout=stdout, stderr=stderr)
        else:
            self.deferred.callback(None)

    def complete_sub(self, out, sub):
        super(CLIPipelineTask, self).complete_sub(out, sub)
        if not self.subs:
            task = getattr(self, 'main', self.tasks[-1])
            chainDeferreds(task.deferred, self.deferred)

    def run_sub(self, sub, *args, **kwargs):
        super(CLIPipelineTask, self).run_sub(sub, *args, **kwargs)
        self.tasks.append(sub)

@decorator
def generator_task(func, *args, **kwargs):
    "Decorator function wrapping a generator that yields Tasks in a GeneratorTask."
    gen = func(*args, **kwargs)
    return GeneratorTask(gen)

class GeneratorTask(BaseSetTask):
    "Task that runs subtasks produced by a generator, passing their output back via the generator's send method. If the generator yields a value that is not a Task, that value will be passed to the GeneratorTask's callback."
    def __init__(self, gen):
        assert(isinstance(gen, GeneratorType))
        super(GeneratorTask, self).__init__(gen)

    def run(self):
        assert(isinstance(self.args, GeneratorType))
        try:
            task = self.args.next()
            self.run_sub(task)
        except StopIteration:
            self.deferred.callback(None)
        except:
            err(failure.Failure())

    def complete_sub(self, out, sub):
        super(GeneratorTask, self).complete_sub(out, sub)
        try:
            newout = self.args.send(out)
            if isinstance(newout, BaseTask):
                self.run_sub(newout)
            else:
                self.deferred.callback(newout)
        except StopIteration:
            self.deferred.callback(None)
        except:
            err(failure.Failure())

class GroupTask(BaseSetTask):
    "Task that starts a group of tasks and waits for them to complete before firing its callback."
    def run(self):
        for task in self.args:
            self.run_sub(task)
        if not self.subs:
            self.deferred.callback(None)

    def complete_sub(self, out, sub):
        out = super(GroupTask, self).complete_sub(out, sub)
        if not(self.subs):
            self.deferred.callback(None)

class PoolTask(BaseSetTask):
    "Task that runs at most Config['jobs'] tasks at a time from its arguments until out of tasks, then fires its callback with None. A suitable number of jobs will be chosen if Config does not specify one, and the sub-Tasks are not connected to each other in any way."
    __slots__ = 'max_tasks'
    def __init__(self, tasks, **kwargs):
        self.max_tasks = kwargs.get('jobs') or int(Config.get('jobs', cpu_count()))
        tasks = iter(tasks)
        super(PoolTask, self).__init__(tasks)

    def run(self):
        try:
            while len(self.subs) < self.max_tasks:
                next_task = self.args.next()
                self.run_sub(next_task)
        except StopIteration:
            pass
        if not self.subs:
            self.deferred.callback(None)

    def complete_sub(self, out, sub):
        out = super(PoolTask, self).complete_sub(out, sub)
        args = self.args
        send = getattr(args, 'send', None)
        try:
            if send:
                next = send((out, sub))
            else:
                next = args.next()
        except StopIteration:
            next = None
        if isinstance(next, BaseTask):
            self.run_sub(next)
        if not self.subs:
            self.deferred.callback(None)
        return out


TaskSet=None
__all__ = []
