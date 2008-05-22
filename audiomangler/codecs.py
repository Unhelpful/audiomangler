###########################################################################
#    Copyright (C) 2008 by Andrew Mahone                                      
#    <andrew.mahone@gmail.com>                                                             
#
# Copyright: See COPYING file that comes with this distribution
#
###########################################################################
import os, os.path
import sys
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

def transcode_track(dtask, etask, sem):
    etask.run()
    dtask.run()
    etask.wait()
    if sem:
        sem.release()

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
    workdir = mkdtemp(dir='/mnt/share',prefix='audiomangler_work_')
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
        if reduce(lambda x,y: x and os.path.isfile(y), targetfiles, True) or \
           reduce(lambda x,y: x and os.path.isfile(y.format()) and y.type_ in allowedcodecs, fileset, True):
            continue
        if reduce(lambda x,y: x and y.type_ in allowedcodecs, fileset, True):
            dirs = set()
            for i,t in zip(fileset,targetfiles):
                targetdir = os.path.split(t)[0]
                if targetdir not in dirs:
                    dirs.add(targetdir)
                    if not os.path.isdir(targetdir):
                        os.makedirs(targetdir)
                print "%s -> %s" % (i.filename,t)
                util.copy(i.filename,t)
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

__all__ = ['transcode_sets']