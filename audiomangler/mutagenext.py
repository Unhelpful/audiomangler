###########################################################################
#    Copyright (C) 2008 by Andrew Mahone                                      
#    <andrew.mahone@gmail.com>                                                             
#
# Copyright: See COPYING file that comes with this distribution
#
###########################################################################
import os.path
from mutagen import FileType
from mutagen.asf import ASF
from mutagen.flac import FLAC
from mutagen.monkeysaudio import MonkeysAudio
from mutagen.mp3 import MP3
from mutagen.mp4 import MP4
from mutagen.ogg import OggFileType
from mutagen.oggvorbis import OggVorbis
from mutagen.wavpack import WavPack
from mutagen.trueaudio import TrueAudio
from mutagen.optimfrog import OptimFROG
from mutagen.musepack import Musepack
from audiomangler import NormMetaData, from_config, Format, Config

def _get_meta(self):
    metacache = getattr(self,'_meta_cache',(False,False))
    if metacache[0] is not getattr(self, 'filename', None) or metacache[1] \
       is not getattr(self, 'tags', None):
        self._meta_cache = (getattr(self, 'filename', None),
           getattr(self, 'tags', None))
        if getattr(self, 'tags', None) is None:
            meta = NormMetaData()
        else:
            meta = NormMetaData.converted(self)
        path = getattr(self,'filename',None)
        if isinstance(path, basestring):
            (meta['dir'], meta['name']) = os.path.split(path)
            meta['path'] = path
            meta['basename'] = os.path.splitext(meta['name'])[0]
        relpath = getattr(self,'relpath',None)
        if isinstance(relpath,basestring):
            meta['relpath'] = relpath
        ext = getattr(self, 'ext', None)
        if ext is not None:
            meta['ext'] = ext
        type_ = getattr(self, 'type_', None)
        if type_ is not None:
            meta['type'] = type_
        self._meta = meta
    return self._meta

def _set_meta(self,value):
    NormMetaData.converted(value).apply(self,True)

def format(self, filename=None, base=None, preadd={}, postadd={}):
    filename, base = from_config('filename', 'base')
    meta = NormMetaData(preadd)
    meta.update(self.meta.flat())
    meta.update(postadd)
    filename = Format(filename)
    return os.path.join(base,filename.evaluate(meta))

FileType.format = format
FileType.meta = property(_get_meta,_set_meta)
FileType.lossless = False

ASF.ext = 'asf'
ASF.type_ = 'asf'
FLAC.ext = 'flac'
FLAC.type_ = 'flac'
FLAC.lossless = True
MonkeysAudio.ext = 'ape'
MonkeysAudio.type_ = 'monkeys'
MonkeysAudio.lossless = True
MP3.ext = 'mp3'
MP3.type_ = 'mp3'
MP4.ext = 'mp4'
MP4.type_ = 'mp4'
OggFileType.ext = 'ogg'
OggVorbis.type_ = 'oggvorbis'
WavPack.ext = 'wv'
WavPack.type_ = 'wavpack'
WavPack.lossless = True
TrueAudio.ext = 'tta'
TrueAudio.lossless = True
OptimFROG.ext = 'ofr'
OptimFROG.lossless = True
Musepack.ext = 'mpc'
Musepack.type_ = 'musepack'