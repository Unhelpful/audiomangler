###########################################################################
#    Copyright (C) 2008 by Andrew Mahone                                      
#    <andrew.mahone@gmail.com>                                                             
#
# Copyright: See COPYING file that comes with this distribution
#
###########################################################################
import os
import os.path
try:
    import cPickle as pickle
except ImportError:
    import pickle
from audiomangler import from_config, NormMetaData, Expr
from mutagen import File
import time

def scan(items, groupby = None, sortby = None):
    groupbytxt, sortbytxt, trackidtxt = from_config('groupby', 'sortby', 'trackid')
    groupby = Expr(groupbytxt)
    sortby = Expr(sortbytxt)
    trackid = Expr(trackidtxt)
    homedir = os.getenv('HOME')
    if homedir is not None:
        cachefile = os.path.join(homedir,'.audiomangler','cache')
    else:
        cachefile = 'audiomangler.cache'
    try:
        dircache = pickle.load(open(cachefile,'rb'))
    except Exception:
        dircache = {}
    if isinstance(items,basestring):
        items = (items,)
    tracks = []
    scanned = set()
    removed = set()
    newdircache = {}
    items = map(os.path.abspath, items)
    for item in items:
        if item in scanned:
            continue
        t = None
        try:
            t = File(item)
        except Exception: pass
        if t is not None:
            t.relpath = t.filename.replace(item,'',1).lstrip('/')
            t.sortkey = t.meta.evaluate(sortby)
            tracks.append(t)
            scanned.add(item)
        else:
            dirs = [item]
            while dirs:
                path = dirs.pop(0)
                try:
                    dst = os.stat(path)
                except OSError:
                    print "unable to stat dir %s" % path
                    removed.add(path)
                    continue
                cached = dircache.get(path,None)
                if cached and cached['key'] == (dst.st_ino, dst.st_mtime):
                    newcached = cached.copy()
                    newcached['tracks'] = []
                    for track in cached['tracks']:
                        fst = os.stat(track['path'])
                        if track['key'] == (fst.st_ino, fst.st_mtime):
                            newcached['tracks'].append(track)
                            t = track['obj']
                            t._meta_cache = (False,False)
                            t.relpath = t.filename.replace(item,'',1).lstrip('/')
                            t.sortkey = t.meta.evaluate(sortby)
                            tracks.append(t)
                        else:
                            t = None
                            try:
                                t = File(item)
                            except Exception: pass
                            if t is not None:
                                t.relpath = t.filename.replace(item,'',1).lstrip('/')
                                t.sortkey = t.meta.evaluate(sortby)
                                tracks.append(t)
                                newcached['tracks'].append({'path':track['path'],'obj':t,'key':(fst.st_ino,fst.st_mtime)})
                else:
                    if cached:
                        removed.add(path)
                    newcached = {'tracks':[],'dirs':[]}
                    newcached['key'] = (dst.st_ino, dst.st_mtime)
                    paths = (os.path.join(path,f) for f in sorted(os.listdir(path)))
                    for filename in paths:
                        if filename in scanned:
                            continue
                        else:
                            scanned.add(filename)
                        if os.path.isdir(filename):
                            newcached['dirs'].append(filename)
                        elif os.path.isfile(filename):
                            t = None
                            try:
                                t = File(filename)
                            except Exception: raise
                            if t is not None:
                                fst = os.stat(filename)
                                t.relpath = os.path.split(t.filename.replace(item,'',1).lstrip('/'))[0]
                                t.sortkey = t.meta.evaluate(sortby)
                                tracks.append(t)
                                newcached['tracks'].append({'path':filename,'obj':t,'key':(fst.st_ino,fst.st_mtime)})
                dirs.extend(newcached['dirs'])
                newdircache[path] = newcached
    for item in items:
        for key in dircache.keys():
            if key.startswith(item):
                del dircache[key]
    dircache.update(newdircache)
    try:
        pickle.dump(dircache,open(cachefile,'wb'),-1)
    except Exception:
        pass
    albums = {}
    dirs = {}
    trackids = {}
    for t in tracks:
        albums.setdefault(t.meta.evaluate(groupby),[]).append(t)
        dirs.setdefault(t.meta['dir'],[]).append(t)
        t.tid = t.meta.evaluate(trackid)
        if t.tid in trackids:
            print "trackid collision"
            print t.filename
            print trackids[t.tid].filename
        trackids[t.tid] = t
    #trying not to evaluate sort expressions for every comparison. don't modify
    #metadata during sort. ;)
    for v in albums.itervalues():
        v.sort(lambda x,y: cmp(x.sortkey,y.sortkey))
    for v in dirs.itervalues():
        v.sort(lambda x,y: cmp(x.sortkey,y.sortkey))
    return albums, dirs, trackids

__all__ = ['scan']