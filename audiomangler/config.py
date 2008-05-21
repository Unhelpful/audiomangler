###########################################################################
#    Copyright (C) 2008 by Andrew Mahone                                      
#    <andrew.mahone@gmail.com>                                                             
#
# Copyright: See COPYING file that comes with this distribution
#
###########################################################################
import os, os.path
import sys
from ConfigParser import RawConfigParser, NoOptionError, NoSectionError

def clear_cache(func):
    def proxy(self, *args, **kw):
        self._cache.clear()
        return func(self, *args, **kw)
    val = getattr(func,'__doc__')
    if hasattr(func,'im_func'):
        func = func.im_func
    for key in ('__doc__','__name__','func_doc'):
        val = getattr(func,key)
        if val is not None:
            setattr(proxy,key, val)
    return proxy

class AMConfig(RawConfigParser):
    def __init__(self, defaults):
        self._current_values = {}
        self._cache = {}
        RawConfigParser.__init__(self)
        for section in defaults:
            items = section[1:]
            section = section[0]
            self.add_section(section)
            for key, value in items:
                self.set(section,key,value)

    @clear_cache
    def __setitem__(self, key, value):
        self._current_values[key] = value

    def __getitem__(self, key):
        if key in self._cache:
            return self._cache[key]
        if key in self._current_values:
            self._cache[key] = self._current_values[key]
            return self._current_values[key]
        trysources = {
           'preset':('type','profile','DEFAULT'),
           'type':('profile','DEFAULT'),
           'profile':('DEFAULT',)
        }.get(key, ('preset','type','profile','DEFAULT'))
        for source in trysources:
            if source == 'preset':
                source = [self['type']]
                if not source[0]:
                    continue
                source.extend(('_',self['preset']))
                if not source[2]:
                    continue
                source = ''.join(source)
            elif source != 'DEFAULT':
                source = self[source]
            if not source:
                continue
            try:
                ret = self.get(source,key)
            except (NoOptionError, NoSectionError):
                continue
            else:
                self._cache[key] = ret
                return ret
        self._cache[key] = None

    for n in ('read','readfp','remove_option','remove_section','set'):
        locals()[n] = clear_cache(getattr(RawConfigParser,n))

Config = AMConfig(
   (
      ('DEFAULT',
         ('groupby',
            "musicbrainz_albumid and ('album',musicbrainz_albumid) or "
            "musicbrainz_discid and ('disc',musicbrainz_discid) or "
            "album and (albumartist or artist) and "
            "('meta',albumartist or artist,album,catalognumber or asin or isrc)"
            " or ('dir',dir)"
         ),
         ('sortby', "(discnumber,tracknumber,filename)"),
         ('base', '.'),
         ('filename',
            "$/(ext and '%s/'%ext)$firstof(releasetype == 'soundtrack' and "
            "'Soundtrack',albumartist,artist)/$(album)/"
            "$if(discnumber > 0,'%02d.' % discnumber)$('%02d' % tracknumber)"
            " $title$if(ext,'.%s'%ext)"
         ),
         ('fs_encoding', 'utf8')
      ),
      ('mp3',
         ('preset', 'standard')
      ),
      ('mp3_medium',
         ('encopts', '--preset medium')
      ),
      ('mp3_standard',
         ('encopts', '--preset standard')
      ),
      ('mp3_extreme',
         ('encopts', '--preset extreme')
      ),
      ('mp3_insane',
         ('encopts', '--preset insane')
      ),
      ('wavpack',
         ('preset', 'standard')
      ),
      ('wavpack_fast',
         ('encopts', '-f')
      ),
      ('wavpack_standard',
         ('encopts', '')
      ),
      ('wavpack_high',
         ('encopts', '-h')
      ),
      ('wavpack_higher',
         ('encopts', '-hh')
      ),
      ('oggvorbis',
         ('preset', 'q3')
      ),
      ('oggvorbis_q1',
         ('encopts', '-q1')
      ),
      ('oggvorbis_q3',
         ('encopts', '-q3')
      ),
      ('oggvorbis_q5',
         ('encopts', '-q5')
      ),
      ('oggvorbis_q7',
         ('encopts', '-q7')
      ),
      ('oggvorbis_q9',
         ('encopts', '-q9')
      ),
      ('flac',
         ('preset', 'standard')
      ),
      ('flac_standard',
         ('encopts', '')
      ),
      ('flac_fast',
         ('encopts', '--fast')
      ),
      ('flac_best',
         ('encopts', '--best')
      ),
   )
)

homedir = os.getenv('HOME')
if homedir is not None:
    configfile = os.path.join(homedir, '.audiomangler', 'config')
else:
    configfile = 'audiomangler.cfg'
Config.read(configfile)

def from_config(*names):
    locals_ = getattr(getattr(sys._getframe(),'f_back',None),'f_locals',None)
    if locals_ is None:
        return
    ret = []
    for key in names:
        val = locals_.get(key)
        if val is None:
            val = Config[key]
        ret.append(val)
    return(ret)
__all__ = ['Config', 'from_config']