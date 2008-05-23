###########################################################################
#    Copyright (C) 2008 by Andrew Mahone                                      
#    <andrew.mahone@gmail.com>                                                             
#
# Copyright: See COPYING file that comes with this distribution
#
###########################################################################
import os, os.path
import sys
import Image
try:
    from cStringIO import StringIO
except ImportError:
    from StringIO import StringIO
from tempfile import mkdtemp
from threading import BoundedSemaphore, RLock
from mutagen import FileType
from audiomangler import Config, from_config, FuncTask, CLITask, TaskSet, Expr, File, util

class CodecMeta(type):
    def __new__(cls, name, bases, cls_dict):
        class_init = cls_dict.get('__classinit__',None)
        if class_init:
            cls_dict['__classinit__'] = staticmethod(class_init)
        return super(CodecMeta,cls).__new__(cls, name, bases, cls_dict)

    def __init__(self, name, bases, cls_dict):
        if callable(getattr(self,'__classinit__',None)):
            self.__classinit__(self, name, bases, cls_dict)

codec_map = {}

class Codec(object):
    __metaclass__ = CodecMeta

    def __classinit__(cls, name, bases, cls_dict):
        if 'type_' in cls_dict:
            codec_map[cls_dict['type_']] = cls

    @classmethod
    def _conv_out_filename(cls, filename):
        return ''.join((filename.rsplit('.',1)[0],'.',cls.ext))

    @classmethod
    def from_wav_multi(cls,indir,infiles,outfiles):
        if not getattr(cls,'_from_wav_multi_cmd',None):
            return None
        encopts = Config['encopts']
        if not encopts:
            encopts = ()
        else:
            encopts = tuple(encopts.split())
        args = cls._from_wav_multi_cmd.evaluate({
           'indir':indir,
           'infiles':tuple(infiles),
           'outfiles':tuple(outfiles),
           'ext':cls.ext,
           'type':cls.type_,
           'encopts':encopts,
           'encoder':cls.encoder
        })
        return (CLITask(args=args,stdin='/dev/null',stdout='/dev/null',stderr=sys.stderr,background=True))

    @classmethod
    def from_wav_pipe(cls, infile, outfile):
        if not getattr(cls,'_from_wav_pipe_cmd',None):
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
        args = cls._from_wav_pipe_cmd.evaluate(env)
        stdin = '/dev/null'
        if hasattr(cls,'_from_wav_pipe_stdin'):
            stdin = cls._from_wav_pipe_stdin.evaluate(env)
        return CLITask(args=args,stdin=stdin,stdout='/dev/null',stderr=sys.stderr,background=True)

    @classmethod
    def to_wav_pipe(cls, infile, outfile):
        if not getattr(cls,'_to_wav_pipe_cmd',None):
            return None
        env = {
           'infile': infile,
           'outfile': outfile,
           'ext':cls.ext,
           'type':cls.type_,
           'decoder':cls.decoder
        }
        args = cls._to_wav_pipe_cmd.evaluate(env)
        stdout = '/dev/null'
        if hasattr(cls,'_to_wav_pipe_stdout'):
            stdout = cls._to_wav_pipe_stdout.evaluate(env)
        return CLITask(args=args,stdin='/dev/null',stdout=stdout,stderr=sys.stderr,background=False)

    @classmethod
    def add_replaygain(files):
        env = {
           'replaygain':cls.replaygain,
           'files':tuple(files)
        }
        args = cls._replaygain_cmd.evaluate(env)
        return CLITask(args=args,stdin='/dev/null',stdout='/dev/null',stderr=sys.stderr,background=False)

class MP3Codec(Codec):
    ext = 'mp3'
    type_ = 'mp3'
    encoder = 'lame'
    replaygain = 'mp3gain'
    _from_wav_multi_cmd = Expr("(encoder,'--quiet')+encopts+('--noreplaygain','--nogapout',indir,'--nogaptags','--nogap')+infiles")

class WavPackCodec(Codec):
    ext = 'wv'
    type_ = 'wavpack'
    encoder = 'wavpack'
    decoder = 'wvunpack'
    replaygain = 'wvgain'
    _to_wav_pipe_cmd = Expr("(decoder,'-q','-w',infile,'-o','-')")
    _to_wav_pipe_stdout = Expr("outfile")
    _from_wav_pipe_cmd = Expr("(encoder,'-q')+encopts+(infile,'-o',outfile)")

class FLACCodec(Codec):
    ext = 'flac'
    type_ = 'flac'
    encoder = 'flac'
    decoder = 'flac'
    replaygain = 'metaflac'
    _to_wav_pipe_cmd = Expr("(decoder,'-s','-c','-d',infile)")
    _to_wav_pipe_stdout = Expr("outfile")
    _from_wav_pipe_cmd = Expr("(encoder,'-s')+encopts+(infile,)")

class OggVorbisCodec(Codec):
    ext = 'ogg'
    type_ = 'oggvorbis'
    encoder = 'oggenc'
    decoder = 'oggdec'
    replaygain = 'vorbisgain'
    _to_wav_pipe_cmd = Expr("(decoder,'-Q','-o','-',infile)")
    _to_wav_pipe_stdout = Expr("outfile")
    _from_wav_pipe_cmd = Expr("(encoder,'-Q')+encopts+('-o',outfile,infile)")
    _replaygain_cmd = Expr("(replaygain,'-q','-a')+files)")

def transcode_track(dtask, etask, sem):
    etask.run()
    dtask.run()
    etask.wait()
    if sem:
        sem.release()

def check_and_copy_cover(fileset,targetfiles):
    cover_sizes = Config['cover_sizes']
    if not cover_sizes:
        return
    cover_out_filename = Config['cover_out_filename']
    if not cover_out_filename:
        return
    cover_out_filename = Expr(cover_out_filename)
    cover_sizes = cover_sizes.split(',')
    covers_loaded = {}
    covers_written = {}
    outdirs = set()
    cover_filenames = Config['cover_filenames']
    if cover_filenames:
        cover_filenames = cover_filenames.split(',')
    else:
        cover_filenames = ()
    for (infile,targetfile) in zip(fileset,targetfiles):
        if infile.meta['dir'] in outdirs: continue
        i = None
        for filename in (os.path.join(infile.meta['dir'],f) for f in cover_filenames):
            try:
                d = open(filename).read()
                i = Image.open(StringIO(d))
                i.load()
            except Exception:
                continue
        if not i:
            tags = [(value.type,value) for key,value in infile.tags.items() if key.startswith('APIC') and \
            hasattr(value,'type') and value.type in (0,3)]
            tags.sort(None,None,True)
            for t,value in tags:
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
            sc = 1.0*s/max(w,h)
            w = int(w*sc+0.5)
            h = int(h*sc+0.5)
            iw = i.resize((w,h),Image.ADAPTIVE)
            filename = os.path.join(os.path.split(targetfile)[0],cover_out_filename.evaluate({'size':s}).encode(Config['fs_encoding'],Config['fs_encoding_err'] or 'replace'))
            iw.save(filename)
        outdirs.add(infile.meta['dir'])

def transcode_set(targetcodec,fileset,targetfiles,alsem,trsem,workdirs,workdirs_l):
    try:
        if not fileset:
            workdirs_l = None
            return
        workdirs_l.acquire()
        workdir, pipefiles = workdirs.pop()
        workdirs_l.release()
        outfiles = map(targetcodec._conv_out_filename,pipefiles[:len(fileset)])
        if hasattr(targetcodec,'_from_wav_pipe_cmd'):
            for i,p,o in zip(fileset,pipefiles,outfiles):
                bgprocs = set()
                dtask = get_codec(i).to_wav_pipe(i.meta['path'],p)
                etask = targetcodec.from_wav_pipe(p,o)
                ttask = FuncTask(background=True,target=transcode_track,args=(dtask,etask,trsem))
                if trsem:
                    trsem.acquire()
                    bgprocs.add(ttask.run())
                else:
                    ttask.runfg()
            for task in bgprocs:
                task.wait()
        elif hasattr(targetcodec,'_from_wav_multi_cmd'):
            etask = targetcodec.from_wav_multi(workdir,pipefiles[:len(fileset),outfiles])
            etask.run()
            for i,o in zip(fileset,pipefiles):
                task = get_codec(i).to_wav_pipe(i.meta['path'])
                task.run()
            etask.wait()
        dirs = set()
        for i,o,t in zip(fileset,outfiles,targetfiles):
            o = File(o)
            o.meta = i.meta
            o.save()
            targetdir = os.path.split(t)[0]
            if targetdir not in dirs:
                dirs.add(targetdir)
                if not os.path.isdir(targetdir):
                    os.makedirs(targetdir)
            print "%s -> %s" %(i.filename,t)
            util.move(o.filename,t)
        if hasattr(targetcodec,'_replaygain_cmd'):
            targetcodec.add_replaygain(outfiles).run()
        check_and_copy_cover(fileset,targetfiles)
    finally:
        if workdirs_l:
            workdirs_l.acquire()
            workdirs.add((workdir,pipefiles))
            workdirs_l.release()
        if alsem:
            alsem.release()

def sync_sets(sets=[]):
    try:
        semct = int(Config['jobs'])
    except (ValueError,TypeError):
        semct = 1
    bgtasks = set()
    targetcodec = Config['type']
    if ',' in targetcodec:
        allowedcodecs = targetcodec.split(',')
        targetcodec = allowedcodecs[0]
        allowedcodecs = set(allowedcodecs)
    else:
        allowedcodecs = set((targetcodec,))
    targetcodec = get_codec(targetcodec)
    workdir = Config['workdir'] or Config['base']
    workdir = mkdtemp(dir=workdir,prefix='audiomangler_work_')
    if hasattr(targetcodec,'_from_wav_pipe_cmd'):
        if len(sets) > semct * 2:
            alsem = BoundedSemaphore(semct)
            trsem = None
        else:
            trsem = BoundedSemaphore(semct)
            alsem = None
    elif hasattr(targetcodec,'_from_wav_multi_cmd'):
        trsem = None
        alsem = BoundedSemaphore(semct)
    numpipes = max(len(s) for s in sets)
    workdirs = set()
    workdirs_l = RLock()
    for n in range(semct):
        w = os.path.join(workdir,"%02d" % n)
        os.mkdir(w)
        pipes = []
        for m in range(numpipes):
            pipes.append(os.path.join(w,"%02d.wav"%m))
            os.mkfifo(pipes[-1])
        pipes = tuple(pipes)
        workdirs.add((w,pipes))
    for fileset in sets:
        targetfiles = [f.format(postadd={'type':targetcodec.type_,'ext':targetcodec.ext}) for f in fileset]
        if reduce(lambda x,y: x and os.path.isfile(y), targetfiles, True):
            check_and_copy_cover(fileset,targetfiles)
            continue
        if reduce(lambda x,y: x and y.type_ in allowedcodecs, fileset, True):
            targetfiles = [f.format() for f in fileset]
            if not reduce(lambda x,y: x and os.path.isfile(y), targetfiles, True):
                dirs = set()
                for i in fileset:
                    t = i.format()
                    targetdir = os.path.split(t)[0]
                    if targetdir not in dirs:
                        dirs.add(targetdir)
                        if not os.path.isdir(targetdir):
                            os.makedirs(targetdir)
                    print "%s -> %s" % (i.filename,t)
                    util.copy(i.filename,t)
            check_and_copy_cover(fileset,targetfiles)
            continue
        if alsem:
            alsem.acquire()
            for task in list(bgtasks):
                if task.poll():
                    bgtasks.remove(task)
        task = FuncTask(background=True,target=transcode_set,args=(targetcodec,fileset,targetfiles,alsem,trsem,workdirs,workdirs_l))
        if alsem:
            bgtasks.add(task.run())
        else:
            task.runfg()
    for task in bgtasks:
        task.wait()
    for w,ps in workdirs:
        for p in ps:
            os.unlink(p)
        os.rmdir(w)
    os.rmdir(workdir)

def get_codec(item):
    if isinstance(item, FileType):
        item = getattr(item,'type_')
    return codec_map[item]

__all__ = ['sync_sets']