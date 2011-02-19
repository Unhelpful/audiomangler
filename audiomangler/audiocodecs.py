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
import Image
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
from audiomangler.task import CLITask, generator_task
from audiomangler.expression import Expr, Format
from audiomangler import util
from audiomangler.util import ClassInitMeta
from mutagen import File
from audiomangler.logging import *

codec_map = {}

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
        if not hasattr('from_wav_multi_cmd'):
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
        return CLITask(args=args, stderr=sys.stderr, background=True)

    @classmethod
    def from_wav_pipe(cls, infile, outfile):
        if not hasattr(cls, 'from_wav_pipe_cmd'):
            return None
        encopts = Config['encopts']
        if not encopts:
            encopts = ()
        else:
            encopts = tuple(encopts.split())
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
        print args
        stdin = '/dev/null'
        if hasattr(cls, '_from_wav_pipe_stdin'):
            stdin = cls._from_wav_pipe_stdin.evaluate(env)
            print args
        return CLITask(*args, stdin=stdin)

    @classmethod
    def to_wav_pipe(cls, infile, outfile):
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
        stdout = '/dev/null'
        if hasattr(cls, 'to_wav_pipe_stdout'):
            stdout = 'w:' + cls.to_wav_pipe_stdout.evaluate(env)
        return CLITask(args=args, stdout=stdout)

    @classmethod
    @generator_task
    def add_replaygain(cls, files, metas=()):
        env = {
            'replaygain':cls.replaygain,
            'files':tuple(files)
        }
        if hasattr(cls, 'replaygain_cmd') and (not metas or not hasattr(cls, calc_replaygain)):
            task = CLITask(*cls.replaygain_cmd.evaluate(env))
            yield task
        elif hasattr(cls, 'calc_replaygain'):
            task = CLITask(*cls.calc_replaygain_cmd.evaluate(env))
            output = yield task
            tracks, album = cls.calc_replaygain(output)
            if metas:
                for meta, track_gain in zip(metas, tracks):
                    NormMetaData(track_gain + album).apply(meta)
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
    from_wav_pipe_cmd = Expr("(encoder, '-Q')+encopts+('-o', outfile, infile)")
    replaygain_cmd = Expr("(replaygain, '-q', '-a')+files")
    calc_replaygain_cmd = Expr("(replaygain, '-a', '-n', '-d')+files")

    @classmethod
    def calc_replaygain(cls, files):
        tracks = []
        args = [cls.replaygain, '-and']
        args.extend(files)
        p = Popen(args=args, stdout=PIPE, stderr=PIPE)
        (out, err) = p.communicate()
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
        return result

    def free_pipes(self, pipes):
        if isinstance(pipes, basestring):
            pipes = (pipes,)
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
            print "%r, %r" % (workdir, basedir)
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
                newpath = os.path.join(self.pipedir,'%s%08x%s' % (prefix, self.count, suffix))
                self.count += 1
                self.files.add(newpath)
            result.append(self.files.pop())
        result.sort()
        return result

    def free_files(self, files):
        if isinstance(files, basestring):
            files = (files,)
        self.files.update(files)

    def cleanup(self):
        rmtree(self.filedir, ignore_errors=True)

pipe_manager = PipeManager(prefix='pipe', suffix='.wav')
file_manager = FileManager(prefix='out')


def transcode_track(dtask, etask, sem):
    etask.run()
    dtask.run()
    etask.wait()
    if sem:
        sem.release()

def check_and_copy_cover(fileset, targetfiles):
    cover_sizes = Config['cover_sizes']
    if not cover_sizes:
        return
    cover_out_filename = Config['cover_out_filename']
    if not cover_out_filename:
        return
    cover_out_filename = Format(cover_out_filename)
    cover_sizes = cover_sizes.split(',')
    covers_loaded = {}
    covers_written = {}
    outdirs = set()
    cover_filenames = Config['cover_filenames']
    if cover_filenames:
        cover_filenames = cover_filenames.split(',')
    else:
        cover_filenames = ()
    cover_out_filenames = [cover_out_filename.evaluate({'size':s}) for s in cover_sizes]
    for (infile, targetfile) in zip(fileset, targetfiles):
        outdir = os.path.split(targetfile)[0]
        if outdir in outdirs: continue
        if all(os.path.isfile(os.path.join(outdir, filename) for filename in cover_out_filenames)):
            outdirs.add(outdir)
            continue
        i = None
        for filename in (os.path.join(infile.meta['dir'], file_) for file_ in cover_filenames):
            try:
                d = open(filename).read()
                i = Image.open(StringIO(d))
                i.load()
            except Exception:
                continue
            if i: break
        if not i:
            tags = [(value.type, value) for key, value in infile.tags.items()
                if key.startswith('APIC') and hasattr(value, 'type')
                and value.type in (0, 3)]
            tags.sort(None, None, True)
            for t, value in tags:
                i = None
                try:
                    d = value.data
                    i = Image.open(StringIO(d))
                    i.load()
                    break
                except Exception:
                    continue
        if not i: continue
        for s in cover_sizes:
            try:
                s = int(s)
            except Exception:
                continue
            w, h = i.size
            sc = 1.0*s/max(w, h)
            w = int(w*sc+0.5)
            h = int(h*sc+0.5)
            iw = i.resize((w, h), Image.ADAPTIVE)
            filename = os.path.join(
               outdir, cover_out_filename.evaluate({'size':s})
            )
            print "save cover %s" % filename
            iw.save(filename)
        outdirs.add(outdir)

rg_keys = 'replaygain_track_gain', 'replaygain_track_peak', 'replaygain_album_gain', 'replaygain_album_peak'
def transcode_set(targetcodec, fileset, targetfiles, alsem, trsem, workdirs, workdirs_l):
    try:
        if not fileset:
            workdirs_l = None
            return
        workdirs_l.acquire()
        workdir, pipefiles = workdirs.pop()
        workdirs_l.release()
        outfiles = map(targetcodec._conv_out_filename, pipefiles[:len(fileset)])
        if targetcodec._from_wav_pipe:
            for i, p, o in zip(fileset, pipefiles, outfiles):
                bgprocs = set()
                dtask = get_codec(i).to_wav_pipe(i.meta['path'], p)
                etask = targetcodec.from_wav_pipe(p, o)
                # FuncTask removed
                #ttask = FuncTask(background=True, target=transcode_track,
                   #args=(dtask, etask, trsem)
                #)
                if trsem:
                    trsem.acquire()
                    bgprocs.add(ttask.run())
                else:
                    ttask.runfg()
            for task in bgprocs:
                task.wait()
        elif targetcodec._from_wav_multi:
            etask = targetcodec.from_wav_multi(
               workdir, pipefiles[:len(fileset)], outfiles
            )
            etask.run()
            for i, o in zip(fileset, pipefiles):
                task = get_codec(i).to_wav_pipe(i.meta['path'], o)
                task.run()
            etask.wait()
        dirs = set()
        metas = []
        newreplaygain = False
        for i, o in zip(fileset, outfiles):
            meta = i.meta.copy()
            if not (i.lossless and targetcodec.lossless):
                for key in rg_keys:
                    if key in meta:
                        del meta[key]
                newreplaygain = True
            if not newreplaygain:
                for key in rg_keys:
                    if key not in meta:
                        newreplaygain=True
                        break
            metas.append(meta)
        if newreplaygain and targetcodec._replaygain:
            targetcodec.add_replaygain(outfiles, metas)
        for i, m, o, t in zip(fileset, metas, outfiles, targetfiles):
            o = File(o)
            m.apply(o)
            o.save()
            targetdir = os.path.split(t)[0]
            if targetdir not in dirs:
                dirs.add(targetdir)
                if not os.path.isdir(targetdir):
                    os.makedirs(targetdir)
            print "%s -> %s" %(i.filename, t)
            util.move(o.filename, t)
        check_and_copy_cover(fileset, targetfiles)
    finally:
        if workdirs_l:
            workdirs_l.acquire()
            workdirs.add((workdir, pipefiles))
            workdirs_l.release()
        if alsem:
            alsem.release()

@generator_task
def album_transcode_one(fileset, targetcodec, ignorefiles):
    pipes = pipe_manager.get_pipes(len(fileset))
    outfiles = [os.path.join(file_manager.filedir, targetcodec._conv_out_filename(os.path.split(pipe)[0])) for pipe in pipes]
    tasks = []
    for file_, pipe in zip(fileset, pipes):
        tasks.append(get_codec(f).to_wav_pipe(file_.filename, pipe))
    tasks.append(targetcodec.from_wav_multi(file_manager.filedir, pipes, ()))
    yield GroupTask(tasks)
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
        fromdirs.add(metas['dir'])
        sourcefiles.add(metas['name'])
        sourcepaths.append(metas['path'])
        outfile_obj = File(outfile)
        meta.apply(file_obj)
        outfile_obj.save()
        outfile_objs.append(outfile_obj)
    if len(fromdir) == 1:
        fromdir = fromdir.pop()
    else:
        fromdir = False
    rename_files(outfile_objs, fromdir, ignorefiles, sourcepaths, 'copy')

def album_transcode_generator(sets, targettids, allowedcodecs, targetcodec):
    print allowedcodecs
    ignorefiles = frozenset(reduce(set.__or__, (set(f.meta['path'] for f in s) for s in sets), set()))
    bg_tasks = set()
    copy_queue = set()
    for album in sets:
        if all(t.type_ in allowedcodecs and t.has_replaygain() for t in album):
            print album
            raise StopIteration

def copy_rename_files(files, fromdir=None, ignorefiles=None, sourcepaths=None, op='move'):
    op_func = globals()[op]
    track_op_func = globals()[op] if sourcepaths else move
    op_track = 'move' if op == 'move' else 'transcode' if sourcepaths else 'copy'
    if fromdir is None:
        fromdir = set(file.meta['dir'] for file in files)
        if len(fromdir) == 1:
            fromdir = fromdir.pop()
            sourcefiles = frozenset(f['name'] for f in files)
        else:
            fromdir = None
    if not sourcepaths:
        sourcepaths = (None,) * len(files)
    dstdirs = set()
    for file_obj, src_path in zip(files, sourcepaths):
        src = file_obj.filename
        dst = util.fsencode(file_obj.format())
        if 'type' in file_obj:
            dst = '%s.%s' % (dst, file_obj['type'])
        src_p = util.fsdecode(src_path or src)
        dst_p = util.fsdecode(dst)
        if src == dst:
            msg(consoleformat=u"  skipping %(src_p)s, already named correctly",
                format="skip: %(src)r",
                src_p=srcp_p, src=src_path or src, loglevel=INFO)
            continue
        dstdir = os.path.split(dst)[0]
        if dstdir not in dstdirs and dstdir != file_obj.meta['dir']:
            try:
                os.makedirs(dstdir)
            except OSError, e:
                if e.errno != errno.EEXIST or not os.path.isdir(dstdir):
                    raise
            dstdirs.add(dstdir)
        msg(consoleformat=u"  %(src_p)s -> %(dst_p)s",
            format="%(op)s: %(src)r, %(dst)r",
            src=src_path or src, dst=dst, src_p=src_p, dst_p=dst_p, op=op_track, loglevel=INFO)
        op_track_func(src, dst)
        if fromdir and len(dstdirs) == 1:
            dstdir = dstdirs.pop()
            for file in os.listdir(fromdir):
                src = os.path.join(fromdir, file)
                dst = os.path.join(dstdir, file)
                src_p = util.fsdecode(src)
                dst_p = util.fsdecode(dst)
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
        generator = track_transcode_generator(sets, targettids, allowedcodecs, targetcodec)
    elif targetcodec.has_from_wav_multi:
        generator = album_transcode_generator(sets, targettids, allowedcodecs, targetcodec)
    return PoolTask(generator(sets, targettids, allowedcodecs, targetcodec))
    
    for fileset in sets:
        if all(file_.type_ in allowedcodecs for file_ in fileset):
            targetfiles = [f.format() for f in fileset]
            if not all(file_.tid in targettids for file_ in fileset):
                print "copying files"
                dirs = set()
                for i in fileset:
                    t = i.format()
                    targetdir = os.path.split(t)[0]
                    if targetdir not in dirs:
                        dirs.add(targetdir)
                        if not os.path.isdir(targetdir):
                            os.makedirs(targetdir)
                    print "%s -> %s" % (i.filename, t)
                    util.copy(i.filename, t)
                codecs = set((get_codec(f) for f in fileset))
                codec = codecs.pop()
                if codec and not codecs and codec._replaygain:
                    codec.add_replaygain(targetfiles)
            check_and_copy_cover(fileset, targetfiles)
            continue
        postadd = {'type':targetcodec.type_, 'ext':targetcodec.ext}
        targetfiles = [f.format(postadd=postadd)for f in fileset]
        if all(file_.tid in targettids for file_ in fileset):
            check_and_copy_cover(fileset, targetfiles)
            continue
        if alsem:
            alsem.acquire()
            for task in list(bgtasks):
                if task.poll():
                    bgtasks.remove(task)
        # FuncTask use needs rewrite
        #task = FuncTask(
           #background=True, target=transcode_set, args=(
              #targetcodec, fileset, targetfiles, alsem, trsem, workdirs,
              #workdirs_l
        #))
        if alsem:
            bgtasks.add(task.run())
        else:
            task.runfg()
    for task in bgtasks:
        task.wait()
    for w, ps in workdirs:
        for p in ps:
            os.unlink(p)
        os.rmdir(w)
    os.rmdir(workdir)

def get_codec(item):
    if isinstance(item, FileType):
        item = getattr(item, 'type_')
    return codec_map[item]

__all__ = ['sync_sets', 'get_codec']