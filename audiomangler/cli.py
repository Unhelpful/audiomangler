# -*- coding: utf-8 -*-
###########################################################################
#    Copyright (C) 2008 by Andrew Mahone                                      
#    <andrew.mahone@gmail.com>                                                             
#
# Copyright: See COPYING file that comes with this distribution
#
###########################################################################
import sys
import getopt
import shutil
import os
import os.path
import errno
from functools import wraps
from audiomangler.config import Config
from audiomangler import util
from audiomangler.codecs import sync_sets, get_codec
from audiomangler.scanner import scan
from audiomangler.task import PoolTask
from audiomangler.logging import err, msg, fatal, ERROR, WARNING, INFO, DEBUG

def parse_options(options = []):
    def decorator(f):
        @wraps(f)
        def proxy(*args):
            if not args:
                if len(sys.argv) == 1:
                    print_usage(options)
                    sys.exit(0)
                else:
                    args = sys.argv[1:]
            name_map = {}
            s_opts = []
            l_opts = []
            for (s_opt, l_opt, name, desc) in options:
                if s_opt:
                    name_map['-'+s_opt.rstrip(':')] = name
                    s_opts.append(s_opt)
                if l_opt:
                    name_map['--'+l_opt.rstrip('=')] = name
                    l_opts.append(l_opt)
            s_opts = ''.join(s_opts)
            try:
                (opts, args) = getopt.getopt(args, s_opts, l_opts)
            except getopt.GetoptError:
                print_usage(options)
                sys.exit(0)
            for k, v in opts:
                k = name_map[k]
                Config[k] = v
            f(*args)
        return proxy
    return decorator

def print_usage(opts):
    print """usage:
    %s [options] [files or directories to process]

options:""" % sys.argv[0]
    for short, long_, name, desc in opts:
        print "    -%s, --%-10s  %s" %(short.rstrip(':'), long_.rstrip('='), desc)

common_opts = (
    ('b:', 'base=', 'base', 'base directory for target files'),
    ('p:', 'profile=', 'profile', 'profile to load settings from'),
    ('f:', 'filename=', 'filename', 'format for target filenames'),
)

@parse_options(common_opts)
def rename(*args):
    dir_list = scan(args)[1]
    util.test_splits(dir_list)
    onsplit = Config['onsplit']
    for (dir_, files) in dir_list.items():
        dir_p = util.fsdecode(dir_)
        msg(consoleformat=u"from dir %(dir_p)s:",
            format="enter: %(dir_)r", dir_=dir_, dir_p=dir_p, loglevel=INFO)
        dstdirs = set()
        moves = []
        for file_ in files:
            src = file_.filename
            dst = util.fsencode(file_.format())
            src_p = util.fsdecode(src)
            dst_p = util.fsdecode(dst)
            if src == dst:
                msg(consoleformat=u"  skipping %(src_p)s, already named correctly",
                    format="skip: %(src)r", src_p=srcp_p, src=src, loglevel=INFO)
                continue
            dstdir = os.path.split(dst)[0]
            if dstdir not in dstdirs and dstdir != dir_:
                try:
                    os.makedirs(dstdir)
                except OSError, e:
                    if e.errno != errno.EEXIST or not os.path.isdir(dstdir):
                        raise
                dstdirs.add(dstdir)
            msg(consoleformat=u"  %(src_p)s -> %(dst_p)s",
                format="move: %(src)r, %(dst)r", src=src, dst=dst, src_p=src_p, dst_p=dst_p, loglevel=INFO)
            util.move(src, dst)
        if len(dstdirs) == 1:
            dstdir = dstdirs.pop()
            for file_ in os.listdir(dir_):
                src = os.path.join(dir_, file_)
                dst = os.path.join(dstdir, file_)
                src_p = util.fsdecode(src)
                dst_p = util.fsdecode(dst)
                msg(consoleformat=u"  %(src_p)s -> %(dst_p)s",
                    format="move: %(src)r, %(dst)r", src=src, dst=dst, src_p=src_p, dst_p=dst_p, loglevel=INFO)
                util.move(src, dst)
            while len(os.listdir(dir_)) == 0:
                dir_p = util.fsdecode(dir_)
                msg(consoleformat=u"  remove empty directory: %(dir_p)s",
                    format="rmdir: %(dir_)r", dir_=dir_, dir_p=dir_p, loglevel=INFO)
                try:
                    os.rmdir(dir_)
                except Exception:
                    break
                newdir = os.path.split(dir_)[0]
                if newdir != dir_:
                    dir_ = newdir
                else:
                    break
        else:
            if onsplit == 'warn':
                msg(consoleformat=u"WARNING: tracks in %(dir_p)s were placed in different directories, other files may be left in the source directory",
                    format="split: %(dir_)r", dir_=dir_, dir_p=dir_p, loglevel=WARNING)

@parse_options(common_opts + (
        ('t:', 'type=', 'type', 'type of audio to encode to'),
        ('s:', 'preset=', 'preset', 'codec preset to use'),
        ('e:', 'encopts=', 'encopts', 'encoder options to use'),
        ('j:', 'jobs=', 'jobs', 'number of jobs to run'),
   )
)
def sync(*args):
    (album_list, dir_list) = scan(args)[:2]
    targettids = scan(Config['base'])[2]
    sync_sets(album_list.values(), targettids)

def replaygain_task_generator(album_list):
    for key, album in album_list.items():
        profiles = set()
        for track in album:
            profiles.add((
               getattr(track, 'type_', None),
               getattr(getattr(track, 'info', None), 'sample_rate', None),
               getattr(getattr(track, 'info', None), 'channels', None)
            ))
        if len(profiles) != 1:
            continue
        profile = profiles.pop()
        if profile[1] not in (8000, 11025, 12000, 16000, 22050, 24, 32, 44100, 48000):
            continue
        codec = get_codec(profile[0])
        if not codec or not codec._replaygain:
            continue
        if reduce(lambda x, y: x and y.has_replaygain(), album, True):
            continue
        msg(consoleformat=u"Adding replaygain values to %(albumtitle)s",
            format="rg: %(tracks)r", albumtitle=album[0].meta.flat().get('album', '[unknown]'),
            tracks=tuple(t.filename for t in album))
        yield codec.add_replaygain([t.filename for t in album])

@parse_options(common_opts[:2] + (
        ('j:', 'jobs=', 'jobs', 'number of jobs to run'),
    )
)
def replaygain(*args):
    if not args:
        args = (Config['base'], )
    (album_list) = scan(args)[0]
    PoolTask(replaygain_task_generator(album_list)).run()

__all__ = []