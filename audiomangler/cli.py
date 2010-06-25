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
from audiomangler import scan, Config, util, sync_sets, get_codec

def parse_options(args = None, options = []):
    if args is None and len(sys.argv) == 1:
        print_usage(options)
        sys.exit(0)
    if args == None:
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
        (opts, args) = getopt.getopt(args,s_opts,l_opts)
    except getopt.GetoptError:
        print_usage(options)
        sys.exit(0)
    for k,v in opts:
        k = name_map[k]
        Config[k] = v
    return args

def print_usage(opts):
    print """usage:
    %s [options] [files or directories to process]

options:""" % sys.argv[0]
    for short,long_,name,desc in opts:
        print "    -%s, --%-10s  %s" %(short.rstrip(':'),long_.rstrip('='),desc)

common_opts = (
    ('b:','base=','base','base directory for target files'),
    ('p:','profile=','profile','profile to load settings from'),
    ('f:','filename=','filename','format for target filenames'),
)

rename_opts = common_opts
def rename(args = None):
    args = parse_options(args, rename_opts)
    dir_list = scan(args)[1]
    for (dir_,files) in dir_list.items():
        dir_ = dir_.encode(Config['fs_encoding'],Config['fs_encoding_error'] or 'replace')
        print "from dir %s:" % dir_
        dstdirs = set()
        moves = []
        for file_ in files:
            src = file_.filename
            dst = file_.format()
            if src == dst:
                print "  skipping %s, already named correctly" % src
                continue
            print "  %s -> %s" % (src, dst)
            dstdir = os.path.split(dst)[0]
            if dstdir not in dstdirs and dstdir != dir_:
                try:
                    os.makedirs(dstdir)
                except OSError, e:
                    if e.errno != errno.EEXIST or not os.path.isdir(dstdir):
                        raise
                dstdirs.add(dstdir)
            util.move(src,dst)
        if len(dstdirs) == 1:
            dstdir = dstdirs.pop()
            for file_ in os.listdir(dir_):
                src = os.path.join(dir_,file_)
                dst = os.path.join(dstdir,file_)
                print "  %s -> %s" % (src,dst)
                util.move(src,dst)
            while len(os.listdir(dir_)) == 0:
                print "  removing empty directory: %s" % dir_
                try:
                    os.rmdir(dir_)
                except Exception:
                    break
                newdir = os.path.split(dir_)[0]
                if newdir != dir_:
                    dir_ = newdir
                else:
                    break

sync_opts = common_opts + (
   ('t:','type=','type','type of audio to encode to'),
   ('s:','preset=','preset','codec preset to use'),
   ('e:','encopts=','encopts','encoder options to use'),
   ('j:','jobs=','jobs','number of jobs to run'),
)
def sync(args = None):
    args = parse_options(args, sync_opts)
    (album_list, dir_list) = scan(args)[:2]
    targettids = scan(Config['base'])[2]
    sync_sets(album_list.values(),targettids)

replaygain_opts = common_opts[:2]
def replaygain(args = None):
    args = parse_options(args, sync_opts)
    if not args:
        args = (Config['base'],)
    (album_list) = scan(args)[0]
    for album in album_list.values():
        profiles = set()
        for track in album:
            profiles.add((
               getattr(track,'type_',None),
               getattr(getattr(track,'info',None),'sample_rate',None),
               getattr(getattr(track,'info',None),'channels',None)
            ))
        if len(profiles) != 1:
            continue
        profile = profiles.pop()
        if profile[1] not in (8000,11025,12000,16000,22050,24,32,44100,48000):
            continue
        codec = get_codec(profile[0])
        if not codec or not codec._replaygain:
            continue
        if reduce(lambda x,y: x and y.has_replaygain(), album, True):
            continue
        codec.add_replaygain([t.filename for t in album])

__all__ = ['rename']