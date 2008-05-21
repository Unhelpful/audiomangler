###########################################################################
#    Copyright (C) 2008 by Andrew Mahone                                      
#    <andrew.mahone@gmail.com>                                                             
#
# Copyright: See COPYING file that comes with this distribution
#
###########################################################################
import os, stat

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
    if hasattr(os, 'chmod'):
        try:
            os.chmod(dst, mode)
        except OSError:
            pass

def move(src,dst):
    try:
        os.rename(src,dst)
    except OSError:
        copy(src,dst)
        os.unlink(src)

__all__ = ['copy','move']