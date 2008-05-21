###########################################################################
#    Copyright (C) 2008 by Andrew Mahone                                      
#    <andrew.mahone@gmail.com>                                                             
#
# Copyright: See COPYING file that comes with this distribution
#
###########################################################################
import os
import os.path
from audiomangler import from_config, NormMetaData, Expr
from mutagen import File

def scan(items, groupby = None, sortby = None):
    groupby, sortby = from_config('groupby', 'sortby')
    groupby = Expr(groupby)
    sortby = Expr(sortby)
    if isinstance(items,basestring):
        items = (items,)
    tracks = []
    scanned = set()
    for item in items:
        item = os.path.abspath(item)
        if item in scanned:
            continue
        t = None
        try:
            t = File(item)
        except Exception: pass
        if t is not None:
            t.sortkey = t.meta.evaluate(sortby)
            tracks.append(t)
            scanned.add(item)
        else:
            for path, dirnames, filenames in os.walk(item):
                filenames = (os.path.join(path,n) for n in filenames)
                for filename in filenames:
                    if filename in scanned:
                        continue
                    try:
                        t = File(filename)
                    except Exception:
                        continue
                    if t is not None:
                        t.sortkey = t.meta.evaluate(sortby)
                        tracks.append(t)
                        scanned.add(item)
    albums = {}
    dirs = {}
    for t in tracks:
        albums.setdefault(t.meta.evaluate(groupby),[]).append(t)
        dirs.setdefault(t.meta['dir'],[]).append(t)
    #trying not to evaluate sort expressions for every comparison. don't modify
    #metadata during sort. ;)
    for v in albums.itervalues():
        v.sort(lambda x,y: cmp(x.sortkey,y.sortkey))
    for v in dirs.itervalues():
        v.sort(lambda x,y: cmp(x.sortkey,y.sortkey))
    return albums, dirs

__all__ = ['scan']