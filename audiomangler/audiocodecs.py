# -*- coding: utf-8 -*-
###########################################################################
#    Copyright (C) 2008 by Andrew Mahone
#    <andrew.mahone@gmail.com>
#
# Copyright: See COPYING file that comes with this distribution
#
###########################################################################
# pylint: disable=E1101
import os, os.path
import sys
import re
import atexit
try:
    from cStringIO import StringIO
except ImportError:
    from StringIO import StringIO
from tempfile import mkdtemp
from shutil import rmtree
from threading import BoundedSemaphore, RLock
from subprocess import Popen, PIPE
from mutagen import FileType
from audiomangler.config import Config
from audiomangler.tag import NormMetaData
from audiomangler.task import CLITask, CLIPipelineTask, PoolTask, FuncTask, GroupTask, generator_task, reactor
from multiprocessing import cpu_count
from audiomangler.expression import Expr, Format
from audiomangler import util
import errno
from audiomangler.util import ClassInitMeta
from mutagen import File
from collections import deque, namedtuple
from twisted.internet.defer import DeferredList
from twisted.python.failure import Failure
from audiomangler.logging import *
from functools import wraps, partial

codec_map = {}
idexpr = Format("$first(releasetype == 'soundtrack' and 'Soundtrack', albumartist, artist, '[Unknown]')::$first(album, '[Unknown]')[$first('%02d.' % discnumber if discnumber > 0 else '', '')$first('%02d' % tracknumber, '')]")

class Codec(object):
    __metaclass__ = ClassInitMeta

    has_from_wav_multi = False
    has_from_wav_pipe = False
    has_to_wav_pipe = False
    has_replaygain = False
    lossless = False
    @classmethod
    def __classinit__(cls, name__, bases__, cls_dict):
        if 'type_' in cls_dict:
            codec_map[cls_dict['type_']] = cls

    @classmethod
    def _conv_out_filename(cls, filename):
        return ''.join((filename.rsplit('.', 1)[0], '.', cls.ext))

    @classmethod
    def from_wav_multi(cls, outdir, infiles, outfiles):
        if not hasattr(cls, 'from_wav_multi_cmd'):
            return None
        encopts = Config['encopts']
        if not encopts:
            encopts = ()
        else:
            encopts = tuple(encopts.split())
        args = cls.from_wav_multi_cmd.evaluate({
           'outdir':outdir,
           'infiles':tuple(infiles),
           'outfiles':tuple(outfiles),
           'ext':cls.ext,
           'type':cls.type_,
           'encopts':encopts,
           'encoder':cls.encoder
        })
        return CLITask(*args, _id="%s.from_wav_multi(%s)" % (cls.__name__, outdir))

    @classmethod
    def from_wav_pipe(cls, infile, outfile, meta):
        if not hasattr(cls, 'from_wav_pipe_cmd'):
            return None
        encopts = Config['encopts']
        if not encopts:
            encopts = ()
        else:
            encopts = tuple(encopts.split())
        if infile:
            outfile = cls._conv_out_filename(infile)
        env = {
            'infile': infile,
            'outfile': outfile,
            'ext': cls.ext,
            'type': cls.type_,
            'encopts': encopts,
            'encoder': cls.encoder
        }
        args = cls.from_wav_pipe_cmd.evaluate(env)
        stdin = 'w'
        if infile and hasattr(cls, '_from_wav_pipe_stdin'):
            stdin = cls._from_wav_pipe_stdin.evaluate(env)
        return CLITask(*args, stdin=stdin, _id="%s.from_wav_pipe{%s}" % (cls.__name__, idexpr.evaluate(meta.flat())))

    @classmethod
    def to_wav_pipe(cls, infile, outfile, meta):
        if not hasattr(cls, 'to_wav_pipe_cmd'):
            return None
        env = {
           'infile':infile,
           'outfile':outfile,
           'ext':cls.ext,
           'type':cls.type_,
           'decoder':cls.decoder
        }
        args = cls.to_wav_pipe_cmd.evaluate(env)
        stdout = 'r'
        if outfile and hasattr(cls, 'to_wav_pipe_stdout'):
            stdout = 'w:' + cls.to_wav_pipe_stdout.evaluate(env)
        return CLITask(*args, stdout=stdout, _id="%s.to_wav_pipe{%s}" % (cls.__name__, idexpr.evaluate(meta.flat())))

    @classmethod
    @generator_task
    def add_replaygain(cls, files, metas=()):
        env = {
            'replaygain':cls.replaygain,
            'files':tuple(files)
        }
        if hasattr(cls, 'replaygain_cmd') and (not metas or not hasattr(cls, 'calc_replaygain')):
            task = CLITask(*cls.replaygain_cmd.evaluate(env))
            yield task
        elif hasattr(cls, 'calc_replaygain'):
            task = CLITask(*cls.calc_replaygain_cmd.evaluate(env))
            output = yield task
            tracks, album = cls.calc_replaygain(output)
            if metas:
                for meta, track_gain in zip(metas, tracks):
                    meta.update(track_gain + album)
                yield metas
            else:
                file_objs = [File(f) for f in files]
                for file_obj, trackfile, trackgain in zip(file_objs, tracks):
                    meta = NormMetaData(trackgain + album)
                    meta.apply(file_obj)
                    f.save()


class MP3Codec(Codec):
    ext = 'mp3'
    type_ = 'mp3'
    encoder = 'lame'
    replaygain = 'mp3gain'
    has_from_wav_multi = True
    has_replaygain = True
    from_wav_multi_cmd = Expr("(encoder, '--quiet') + encopts + ('--noreplaygain', '--nogapout', outdir, '--nogaptags', '--nogap') + infiles")
    calc_replaygain_cmd = Expr("(replaygain, '-q', '-o', '-s', 's')+files")

    @staticmethod
    def calc_replaygain(out):
        (out, err__) = out
        out = [l.split('\t')[2:4] for l in out.splitlines()[1:]]
        tracks = []
        for i in out[:-1]:
            gain = ' '.join((i[0], 'dB'))
            peak = '%.8f'% (float(i[1]) / 32768)
            tracks.append((('replaygain_track_gain', gain), ('replaygain_track_peak', peak)))
        gain = ' '.join((out[-1][0], 'dB'))
        peak = '%.8f'% (float(out[-1][1]) / 32768)
        album = (('replaygain_album_gain', gain), ('replaygain_album_peak', peak))
        return tracks, album

class WavPackCodec(Codec):
    ext = 'wv'
    type_ = 'wavpack'
    encoder = 'wavpack'
    decoder = 'wvunpack'
    replaygain = 'wvgain'
    has_to_wav_pipe = True
    has_from_wav_pipe = True
    has_replaygain = True
    lossless = True
    to_wav_pipe_cmd = Expr("(decoder, '-q', '-w', infile, '-o', '-')")
    to_wav_pipe_stdout = Expr("outfile")
    from_wav_pipe_cmd = Expr("(encoder, '-q')+encopts+(infile, '-o', outfile)")
    replaygain_cmd = Expr("(replaygain, '-a')+files")

class FLACCodec(Codec):
    ext = 'flac'
    type_ = 'flac'
    encoder = 'flac'
    decoder = 'flac'
    replaygain = 'metaflac'
    has_to_wav_pipe = True
    has_from_wav_pipe = True
    has_replaygain = True
    lossless = True
    to_wav_pipe_cmd = Expr("(decoder, '-s', '-c', '-d', infile)")
    to_wav_pipe_stdout = Expr("outfile")
    from_wav_pipe_cmd = Expr("(encoder, '-s')+encopts+(infile, )")
    replaygain_cmd = Expr("(replaygain, '--add-replay-gain')+files")

class OggVorbisCodec(Codec):
    ext = 'ogg'
    type_ = 'oggvorbis'
    encoder = 'oggenc'
    decoder = 'oggdec'
    replaygain = 'vorbisgain'
    has_to_wav_pipe = True
    has_from_wav_pipe = True
    has_replaygain = True
    to_wav_pipe_cmd = Expr("(decoder, '-Q', '-o', '-', infile)")
    to_wav_pipe_stdout = Expr("outfile")
    from_wav_pipe_cmd = Expr("(encoder, '-Q')+encopts+('-o', outfile, infile or '-')")
    replaygain_cmd = Expr("(replaygain, '-q', '-a')+files")
    calc_replaygain_cmd = Expr("(replaygain, '-a', '-n', '-d')+files")

    @staticmethod
    def calc_replaygain(out):
        out, err = out
        tracks = []
        apeak = 0.0
        for match in re.finditer('^\s*(\S+ dB)\s*\|\s*([0-9]+)\s*\|', out,
            re.M):
            gain = match.group(1)
            peak = float(match.group(2)) / 32768
            apeak = max(apeak, peak)
            peak = "%.8f" % peak
            tracks.append((('replaygain_track_gain', gain), ('replaygain_track_peak', peak)))
        again = re.search('^Recommended Album Gain:\s*(\S+ dB)', err, re.M)
        if again:
            album = (('replaygain_album_gain', again.group(1)), ('replaygain_album_peak', "%.8f" % apeak))
        else:
            album = (('replaygain_album_peak', apeak),)
        return tracks, album

class PipeManager(object):
    __slots__ = 'pipes', 'pipedir', 'count', 'prefix', 'suffix'
    def __init__(self, prefix='', suffix=''):
        self.pipedir = None
        self.prefix = prefix
        self.suffix = suffix
        self.pipes = set()
        self.count = 0

    def create_dir(self):
        if self.pipedir is None:
            self.pipedir = os.path.abspath(Config['workdir'] or Config['base'])
            self.pipedir = mkdtemp(prefix='audiomangler_work_', dir=self.pipedir)
            atexit.register(self.cleanup)

    def get_pipes(self, count=1):
        result = []
        prefix=self.prefix
        suffix=self.suffix
        if not self.count:
            self.create_dir()
        for idx in xrange(count):
            if not self.pipes:
                newpath = os.path.join(self.pipedir,'%s%08x%s' % (prefix, self.count, suffix))
                self.count += 1
                os.mkfifo(newpath)
                self.pipes.add(newpath)
            result.append(self.pipes.pop())
        result.sort()
        msg(consoleformat=u"%(obj)r allocating pipes %(pipes)r", obj=self, pipes=result)
        return result

    def free_pipes(self, pipes):
        if isinstance(pipes, basestring):
            pipes = (pipes,)
        msg(consoleformat=u"%(obj)r freeing pipes %(pipes)r", obj=self, pipes=pipes)
        self.pipes.update(pipes)

    def cleanup(self):
        rmtree(self.pipedir, ignore_errors=True)

class FileManager(object):
    __slots__ = 'files', 'filedir', 'count', 'prefix', 'suffix'
    def __init__(self, prefix='', suffix=''):
        self.filedir = None
        self.prefix = prefix
        self.suffix = suffix
        self.files = set()
        self.count = 0

    def create_dir(self):
        if self.filedir is None:
            workdir = Config['workdir']
            if workdir:
                workdir = os.path.abspath(workdir)
            basedir = Config['base']
            if basedir:
                basedir = os.path.abspath(basedir)
            if workdir is None or workdir == basedir:
                global pipe_manager
                pipe_manager.create_dir()
                self.filedir = pipe_manager.pipedir
                return
            elif not workdir:
                workdir = basedir
            self.filedir = workdir
            self.filedir = mkdtemp(prefix='audiomangler_work_', dir=self.filedir)
            atexit.register(self.cleanup)

    def get_files(self, count=1):
        result = []
        prefix=self.prefix
        suffix=self.suffix
        if not self.count:
            self.create_dir()
        for idx in xrange(count):
            if not self.files:
                newpath = os.path.join(self.filedir,'%s%08x%s' % (prefix, self.count, suffix))
                self.count += 1
                self.files.add(newpath)
            result.append(self.files.pop())
        result.sort()
        msg(consoleformat=u"%(obj)r allocating files %(files)r", obj=self, files=result)
        return result

    def free_files(self, files):
        if isinstance(files, basestring):
            files = (files,)
        msg(consoleformat=u"%(obj)r freeing files %(files)r", obj=self, files=files)
        self.files.update(files)

    def cleanup(self):
        rmtree(self.filedir, ignore_errors=True)

pipe_manager = PipeManager(prefix='pipe', suffix='.wav')
file_manager = FileManager(prefix='out')

rg_keys = 'replaygain_track_gain', 'replaygain_track_peak', 'replaygain_album_gain', 'replaygain_album_peak'

def check_output(outfile):
    assert os.path.exists(outfile), "Expected output file %r is missing" % outfile

@generator_task
def complete_album(fileset, targetcodec, outfiles):
    newreplaygain = False
    metas = []
    for file in fileset:
        meta = file.meta.copy()
        if not (file.lossless and targetcodec.lossless):
            for key in rg_keys:
                if key in meta:
                    del meta[key]
        for key in rg_keys:
            if key not in meta:
                newreplaygain = True
                break
        metas.append(meta)
    if targetcodec.has_replaygain:
        metas = (yield targetcodec.add_replaygain(outfiles, metas)) or metas
    outfile_objs = []
    fromdir = set()
    sourcefiles = set()
    sourcepaths = []
    for meta, outfile in zip(metas, outfiles):
        fromdir.add(meta['dir'])
        sourcefiles.add(meta['name'])
        sourcepaths.append(meta['path'])
        outfile_obj = File(outfile)
        meta.apply(outfile_obj)
        outfile_obj.save()
        outfile_objs.append(outfile_obj)
    if len(fromdir) == 1:
        fromdir = fromdir.pop()
        ignorefiles = frozenset(sourcefiles)
    else:
        fromdir = False
        ignorefiles = False
    copy_rename_files(outfile_objs, fromdir, ignorefiles, sourcepaths, 'move')
    for outfile in outfiles:
        if os.path.exists(outfile):
            err(consoleformat="Temporary file %(file)r still exists after it should have been renamed.", file=outfile)

@generator_task
def album_transcode_one(fileset, targetcodec):
    file_manager.create_dir()
    pipes = pipe_manager.get_pipes(len(fileset))
    outfiles = [os.path.join(file_manager.filedir, targetcodec._conv_out_filename(os.path.split(pipe)[1])) for pipe in pipes]
    tasks = [targetcodec.from_wav_multi(file_manager.filedir, pipes, ())]
    for file_, pipe in zip(fileset, pipes):
        tasks.append(get_codec(file_).to_wav_pipe(file_.filename, pipe, file_.meta))
    yield GroupTask(tasks)
    complete_task = complete_album(fileset, targetcodec, outfiles)
    complete_task.deferred.addBoth(lambda dummy: pipe_manager.free_pipes(pipes))
    yield complete_task

def deque_queue(d):
    while len(d):
        yield d.popleft()

def track_transcode_generator(sets, targettids, allowedcodecs, targetcodec):
    class album_(object):
        __slots__ = [ 'task_count', 'album', 'outfiles' ]
    copy_task = None
    copy_queue = deque()
    completions = deque()

    def wrap(f):
        @wraps(getattr(f, 'func', f))
        def proxy(out):
            f()
            return out
        return proxy
    for album in sets:
        if all(t.type_ in allowedcodecs and t.has_replaygain() for t in album):
            copy_queue.append(FuncTask(copy_rename_files, album, op='copy'))
            if (copy_task and copy_task.deferred.called):
                copy_task = None
            if (copy_task is None):
                copy_task = PoolTask(deque_queue(copy_queue), jobs=1)
                copy_task.queue()
        else:
            file_manager.create_dir()
            tasks = []
            outfiles = []
            outfiles_ext = []
            for track in album:
                outfile, = file_manager.get_files(1)
                outfile_ext = targetcodec._conv_out_filename(outfile)
                decoder = get_codec(track).to_wav_pipe(track.filename, None, track.meta)
                encoder = targetcodec.from_wav_pipe(None, outfile_ext, track.meta)
                task = CLIPipelineTask([decoder, encoder])
                task.deferred.addCallback(wrap(partial(check_output, outfile_ext)))
                if os.path.exists(outfile_ext):
                    err(consoleformat="Output file %(file)r already exists!", file=outfile_ext)
                tasks.append(task)
                outfiles.append(outfile)
                outfiles_ext.append(outfile_ext)
                yield task
            complete_task = complete_album(album, targetcodec, outfiles_ext)
            complete_task.deferred.addBoth(wrap(partial(file_manager.free_files,outfiles)))
            DeferredList([t.deferred for t in tasks], fireOnOneErrback=True).addCallback(wrap(complete_task.run))

def album_transcode_generator(sets, targettids, allowedcodecs, targetcodec):
    copy_task = None
    copy_queue = deque()
    for album in sets:
        if all(t.type_ in allowedcodecs and t.has_replaygain() for t in album):
            copy_queue.append(FuncTask(copy_rename_files, album, op='copy'))
            if (copy_task and copy_task.deferred.called):
                copy_task = None
            if (copy_task is None):
                copy_task = PoolTask(deque_queue(copy_queue), jobs=1)
                copy_task.queue()
        else:
            yield album_transcode_one(album, targetcodec)

def copy_rename_files(files, fromdir=None, ignorefiles=None, sourcepaths=None, op='move'):
    track_op_func = getattr(util, op)
    op_func = util.copy if sourcepaths else getattr(util, op)
    op_track = 'transcode' if sourcepaths else op
    if fromdir is None:
        fromdir = set(f.meta['dir'] for f in files)
        if len(fromdir) == 1:
            fromdir = fromdir.pop()
            sourcefiles = frozenset(f.meta['name'] for f in files)
        else:
            fromdir = None
    if not sourcepaths:
        sourcepaths = [file_obj.meta['path'] for file_obj in files]
    if ignorefiles is None:
        ignorefiles = frozenset([file_obj.meta['name'] for file_obj in files])
    dstdirs = set()
    for file_obj, src in zip(files, sourcepaths):
        dst = util.fsencode(file_obj.format())
        if 'type' in file_obj:
            dst = '%s.%s' % (dst, file_obj['type'])
        src_p = util.fsdecode(src)
        dst_p = util.fsdecode(dst)
        if src == dst:
            msg(consoleformat=u"  skipping %(src_p)s, already named correctly",
                format="skip: %(src)r",
                src_p=srcp_p, src=src, loglevel=INFO)
            continue
        dstdir = os.path.split(dst)[0]
        if dstdir not in dstdirs and dstdir != file_obj.meta['dir']:
            try:
                os.makedirs(dstdir)
            except OSError, e:
                if e.errno != errno.EEXIST or not os.path.isdir(dstdir):
                    raise
            dstdirs.add(dstdir)
        if op_track == 'transcode':
            src = file_obj.meta['path']
        msg(consoleformat=u"  %(src_p)s -> %(dst_p)s",
            format="%(op)s: %(src)r, %(dst)r",
            src=src, dst=dst, src_p=src_p, dst_p=dst_p, op=op_track, loglevel=INFO)
        track_op_func(src, dst)
    if fromdir and len(dstdirs) == 1:
        dstdir = dstdirs.pop()
        for file in os.listdir(fromdir):
            src = os.path.join(fromdir, file)
            dst = os.path.join(dstdir, file)
            src_p = util.fsdecode(src)
            dst_p = util.fsdecode(dst)
            if file in ignorefiles: continue
            msg(consoleformat=u"  %(src_p)s -> %(dst_p)s",
                format="%(op)s: %(src)r, %(dst)r", src=src, dst=dst,
                src_p=src_p, dst_p=dst_p, op=op, loglevel=INFO)
            op_func(src, dst)
            if(op == 'move'):
                while len(os.listdir(fromdir)) == 0:
                    fromdirp = util.fsdecode(fromdir)
                    msg(consoleformat=u"  remove empty directory: %(fromdirp)s",
                        format="rmdir: %(fromdir)r",
                        fromdir=fromdir, fromdirp=fromdirp, loglevel=INFO)
                    try:
                        os.rmdir(fromdir)
                    except Exception:
                        break
                    newdir = os.path.split(fromdir)[0]
                    if newdir != fromdir:
                        fromdir = newdir
                    else:
                        break
    else:
        if onsplit == 'warn':
            msg(consoleformat=u"WARNING: tracks in %(dir_p)s were placed in or %(op)s from different directories, other files may be left in the source directory",
                format="split: %(dir_)r",
                dir_=dir_, dir_p=dir_p, op={'move':'moved', 'copy':'copied'}, loglevel=WARNING)

def sync_sets(sets=[], targettids=()):
    tidexpr = Expr(Config['trackid'])
    targetcodec = Config['type']
    if ',' in targetcodec:
        allowedcodecs = targetcodec.split(',')
        targetcodec = allowedcodecs[0]
        allowedcodecs = set(allowedcodecs)
    else:
        allowedcodecs = set((targetcodec,))
    targetcodec = get_codec(targetcodec)
    postadd = {'type':targetcodec.type_, 'ext':targetcodec.ext}
    dstdirs = set()
    onsplit = Config['onsplit']
    newsets = []
    while sets:
        fileset = sets.pop()
        srcs = set(file.meta['dir'] for file in fileset)
        dsts = set(os.path.split(file.format(postadd=() if file.type_ in allowedcodecs else postadd))[0] for file in fileset)
        dsts = tuple(dsts)
        if onsplit == 'abort':
            if len(dsts) > 1:
                fatal(consoleformat=u"tracks in %(src)s would be placed in different target directories, aborting\nset onsplit to 'warn' or 'ignore' to proceed anyway",
                    format="split: {src:%(src)r", src=srcs.pop(), nologerror=1)
            if len(srcs) > 1:
                fatal(consoleformat=u"tracks in from directories %(src)s would be placed in target directory %(dst)r, aborting\nset onsplit to 'warn' or 'ignore' to proceed anyway",
                    format="split: %(src)r", src=tuple(srcs), dst=dsts[0], nologerror=1)
            if dsts[0] in dstdirs:
                fatal(consoleformat=u"tracks in %(src)s would be placed in %(dst)s, which is already the target for other tracks, aborting\nset onsplit to 'warn' or 'ignore' to proceed anyway",
                    format="split: %(src)r", src=tuple(srcs), dst=dsts[0], nologerror=1)
        dstdirs.add(dsts[0])
        if any(file.meta.evaluate(tidexpr) not in targettids for file in fileset):
            newsets.append(fileset)
    sets = newsets
    if targetcodec.has_from_wav_pipe:
        task_generator = track_transcode_generator
    elif targetcodec.has_from_wav_multi:
        task_generator = album_transcode_generator
    reactor.suggestThreadPoolSize(max(len(alb) for alb in sets) * (2 + int(Config.get('jobs', cpu_count()))))
    PoolTask(task_generator(sets, targettids, allowedcodecs, targetcodec)).run()
    return

dirmap_entry = namedtuple('dirmap_entry',('dirs','srcfiles'))
def check_rename_sync(albums, dirs, mode='rename', targettids = ()):
    targettids = frozenset(targettids)
    if targettids:
        tidexpr = Expr(Config['trackid'])
    else:
        tidexpr = None
    dirmap = {}
    dstpaths = {}
    wassplit = False
    wasconflict = False
    onsplit = Config['onsplit']
    onconflict = Config['onconflict']
    if mode != 'rename':
        targetcodec = Config['type']
        if ',' in targetcodec:
            allowedcodecs = targetcodec.split(',')
            targetcodec = allowedcodecs[0]
            allowedcodecs = set(allowedcodecs)
        else:
            allowedcodecs = set((targetcodec,))
        targetcodec = get_codec(targetcodec)
        postadd = {'type':targetcodec.type_, 'ext':targetcodec.ext}
    else:
        postadd = ()
        allowedcodecs = None
    for album in albums.values():
        if all(track.meta.evaluate(tidexpr) in targettids for track in album):
            continue
        dsts = [util.fsencode(file.format(postadd=() if allowedcodecs and file.type_ in allowedcodecs else postadd)) for file in album]
        for src, dst in zip(album, dsts):
            srcdir = src.meta['dir']
            dstdir = os.path.split(dst)[0]
            curdirmap = dirmap.setdefault(srcdir, dirmap_entry(set(),set()))
            curdirmap.dirs.add(dstdir)
            curdirmap.srcfiles.add(src.meta['name'])
            dstpaths.setdefault(dst, []).append(src.meta['path'])
    for srcdir, entry in dirmap.items():
        srcdir_p = util.fsdecode(srcdir)
        if len(entry.dirs) > 1:
            if onsplit == 'error':
                err(consoleformat=u"tracks in %(src_p)s would be placed in different target directories",
                        format="split: src:%(src)r", src_p=srcdir_p, src=srcdir)
                wassplit = True
        else:
            skip = frozenset(entry.srcfiles)
            dstdir = list(entry.dirs)[0]
            for file_ in os.listdir(srcdir):
                if file_ in skip: continue
                src = os.path.join(srcdir, file_)
                dst = os.path.join(dstdir, file_)
                src_p = util.fsdecode(src)
                dsp_p = util.fsdecode(dst)
                dstpaths.setdefault(dst, []).append(src)
    for dst,srcs in dstpaths.items():
        if onconflict == 'error':
            if len(srcs) > 1:
                srcs_p = u', '.join(util.fsdecode(s) for s in srcs)
                dst_p = util.fsdecode(dst)
                err(consoleformat=u"files %(srcs_p)s would be copied or moved to same file %(dst_p)s",
                        format="conflict: src: %(srcs)r, dst: %(dst)r", srcs_p=srcs_p, dst_p=dst_p, srcs=srcs, dst=dst)
                wasconflict = True
            elif dst == srcs[0]:
                continue
            if (os.path.exists(dst)):
                srcs_p = u', '.join(util.fsdecode(s) for s in srcs)
                dst_p = util.fsdecode(dst)
                srcs = srcs[0] if len(srcs) == 1 else srcs
                err(consoleformat=u"file(s) %(srcs_p)s would be copied or moved to file %(dst_p)s, which already exists",
                        format="conflict: src: %(srcs)r, dst: %(dst)r", srcs_p=srcs_p, dst_p=dst_p, srcs=srcs, dst=dst)
                wasconflict = True
    if wassplit:
        err(consoleformat="some existing directories would be split, set onsplit to 'warn' or 'ignore' to proceed anyway", nologerror=1)
    if wasconflict:
        err(consoleformat="some files would conflict with each other or with existing files, set onconflict to 'warn' or 'ignore' to proceed anyway", nologerror=1)
    if wassplit or wasconflict:
        sys.exit(1)

def get_codec(item):
    if isinstance(item, FileType):
        item = getattr(item, 'type_')
    return codec_map[item]

__all__ = ['sync_sets', 'get_codec']
