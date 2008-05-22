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
from audiomangler import scan, Config, util, transcode_sets

def parse_options(args = None, options = []):
    if args is None and len(sys.argv) == 1:
        print_usage(transcode_opts)
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
    (opts, args) = getopt.getopt(args,s_opts,l_opts)
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
    ('f:','filename=','filename','format for target filenames'),
    ('p:','profile=','profile','profile to load settings from'),
)

rename_opts = common_opts
def rename(args = None):
    args = parse_options(args, rename_opts)
    (album_list, dir_list) = scan(args)
    for (dir_,files) in dir_list.items():
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
                shutil.move(src,dst)
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
    (album_list, dir_list) = scan(args)
    sync_sets(album_list.values())

__all__ = ['rename']