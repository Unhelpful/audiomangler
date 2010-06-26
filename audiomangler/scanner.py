# -*- coding: utf-8 -*-
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
    import shelve
except ImportError:
    shelve = None
from audiomangler import from_config, NormMetaData, Expr
from mutagen import File
from mutagen import version as mutagen_version
import time

db_version = (mutagen_version, (0,0))

def scan_track(path, from_dir = ''):
    t = None
    try:
        t = File(path)
    except Exception: pass
    if t is not None:
        if from_dir:
            t.relpath = t.filename.replace(from_dir,'',1).lstrip('/')
            t.reldir = t.relpath.rsplit('/',1)
            if len(t.reldir) > 1:
                t.reldir = t.reldir[0]
            else:
                t.reldir = ''
    return t

def scan(items, groupby = None, sortby = None, trackid = None):
    groupbytxt, sortbytxt, trackidtxt = from_config('groupby', 'sortby', 'trackid')
    groupby = Expr(groupby or groupbytxt)
    sortby = Expr(sortby or sortbytxt)
    trackid = Expr(trackid or trackidtxt)
    homedir = os.getenv('HOME')
    if homedir is not None:
        cachefile = os.path.join(homedir,'.audiomangler')
        try:
            os.mkdir(cachefile)
        except OSError:
            pass
        cachefile = os.path.join(cachefile,'cache')
    else:
        cachefile = 'audiomangler.cache'
    dircache = {}
    if shelve:
        try:
            dircache = shelve.open(cachefile)
        except Exception:
            pass
    if dircache.get('//version',None) != db_version:
        dircache.clear()
        dircache['//version'] = db_version
    if isinstance(items,basestring):
        items = (items,)
    tracks = []
    scanned = set()
    newdircache = {}
    items = map(os.path.abspath, items)
    for item in items:
        if item in scanned:
            continue
        t = scan_track(item)
        if t is not None:
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
                    continue
                cached = dircache.get(path,None)
                if cached and cached['key'] == (dst.st_ino, dst.st_mtime):
                    newcached = cached
                    newtracks = []
                    newfiles = []
                    for track in cached['tracks']:
                        try:
                            fst = os.stat(track['path'])
                        except Exception:
                            continue
                        if track['key'] == (fst.st_ino, fst.st_size, fst.st_mtime):
                            newtracks.append(track)
                            t = track['obj']
                            t._meta_cache = (False,False)
                            t.relpath = t.filename.replace(item,'',1).lstrip('/')
                            t.reldir = t.relpath.rsplit('/',1)
                            if len(t.reldir) > 1:
                                t.reldir = t.reldir[0]
                            else:
                                t.reldir = ''
                            tracks.append(t)
                        else:
                            t = scan_track(track['path'])
                            if t is not None:
                                tracks.append(t)
                                newtracks.append({'path':track['path'],'obj':t,'key':(fst.st_ino,fst.st_size,fst.st_mtime)})
                    for file_ in cached['files']:
                        try:
                            fst = os.stat(file_['path'])
                        except Exception:
                            continue
                        if file_['key'] == (fst.st_ino, fst.st_size, fst.st_mtime):
                            newfiles.append(file_)
                        else:
                            t = scan_track(file_['path'])
                            if t is not None:
                                tracks.append(t)
                                newtracks.append({'path':file_['path'],'obj':t,'key':(fst.st_ino,fst.st_size,fst.st_mtime)})
                            else:
                                newfiles.append({'path':file_['path'],'key':(fst.st_ino,fst.st_size,fst.st_mtime)})
                    newcached['tracks'] = newtracks
                    newcached['files'] = newfiles
                else:
                    newcached = {'tracks':[],'dirs':[],'files':[]}
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
                            try:
                                fst = os.stat(filename)
                            except Exception:
                                continue
                            t = scan_track(filename)
                            if t is not None:
                                tracks.append(t)
                                newcached['tracks'].append({'path':filename,'obj':t,'key':(fst.st_ino,fst.st_size,fst.st_mtime)})
                            else:
                                newcached['files'].append({'path':filename,'key':(fst.st_ino,fst.st_size,fst.st_mtime)})
                        else:
                            continue
                dirs.extend(newcached['dirs'])
                newdircache[path] = newcached
    for item in items:
        for key in dircache.keys():
            if key.startswith(item):
                del dircache[key]
    dircache.update(newdircache)
    if hasattr(dircache,'close'):
        dircache.close()
    albums = {}
    dirs = {}
    trackids = {}
    for t in tracks:
        t.sortkey = t.meta.evaluate(sortby)
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