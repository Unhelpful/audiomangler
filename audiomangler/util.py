# -*- coding: utf-8 -*-
###########################################################################
#    Copyright (C) 2008 by Andrew Mahone                                      
#    <andrew.mahone@gmail.com>                                                             
#
# Copyright: See COPYING file that comes with this distribution
#
###########################################################################
import os, stat
from audiomangler import Config, msg, err, fatal, WARNING, ERROR

def copy(src,dst):
    fsrc = None
    fdst = None
    try:
        fsrc = open(src,'rb')
        fdst = open(dst,'wb')
        while 1:
            buf = fsrc.read(16384)
            if not buf:
                break
            fdst.write(buf)
    finally:
        if fsrc:
            fsrc.close()
        if fdst:
            fdst.close()
    st = os.stat(src)
    mode = stat.S_IMODE(st.st_mode)
    if hasattr(os, 'utime'):
        try:
            os.utime(dst, (st.st_atime, st.st_mtime))
        except OSError:
            pass

def move(src,dst):
    try:
        os.rename(src,dst)
    except OSError:
        copy(src,dst)
        os.unlink(src)

def test_splits(dir_list,transcode=False):
    from audiomangler import get_codec
    if transcode and Config['type']:
        targetcodec = Config['type']
        if ',' in targetcodec:
            allowedcodecs = targetcodec.split(',')
            targetcodec = allowedcodecs[0]
            allowedcodecs = frozenset(allowedcodecs)
        else:
            allowedcodecs = frozenset((targetcodec,))
        targetcodec = get_codec(targetcodec)
        postadd = lambda type_: {} if type_ in allowedcodecs else {'type':targetcodec.type_,'ext':targetcodec.ext}
    else:
        postadd = lambda type_: {}
    for (dir_, files) in dir_list.items():
        dstdirs = set()
        for file_ in files:
            src = file_.filename
            dst = fsencode(file_.format(postadd=postadd(file_.type_)))
            dstdir = os.path.split(dst)[0]
            dstdirs.add(dstdir)
        if len(dstdirs) > 1:
            onsplit = Config['onsplit']
            if onsplit == 'abort':
                fatal(consoleformat=u"tracks in %(dir_p)s would be placed in different target directories, aborting\nset onsplit to 'warn' or 'ignore' to proceed anyway",
                    format="split: %(dir_)r", dir_=dir_, dir_p=fsdecode(dir_),nologerror=1)

def fsencode(string):
    return string.encode(Config['fs_encoding'],Config.get('fs_encoding_err','underscorereplace'))

def fsdecode(string):
    return string.decode(Config['fs_encoding'],Config.get('fs_encoding_err','replace'))

__all__ = ['copy','move','fsencode','fsdecode','test_splits']