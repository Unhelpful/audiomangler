###########################################################################
#    Copyright (C) 2008 by Andrew Mahone                                      
#    <andrew.mahone@gmail.com>                                                             
#
# Copyright: See COPYING file that comes with this distribution
#
###########################################################################
from mutagen.id3 import ID3, USLT
from mutagen._vorbis import VCommentDict
from mutagen.apev2 import APEv2
from mutagen import id3
import re
from operator import and_
from audiomangler import evaluate

def splitnumber(num, label):
    if isinstance(num, (list,tuple)):
        num = num[0]
    if not num:
        num = ''
    num = re.search(r'^(\d*)(?:/(\d*))?',num)
    num = num and num.groups() or [0,0]
    try:
        index = int(num[0])
    except:
        index = 0
    try:
        total = int(num[1])
    except:
        total = 0
    ret = []
    if index:
        ret.append((label+'number', index))
        if total:
            ret.append(('total'+label+'s', total))
    return ret

def joinnumber(input, label, outlabel = None):
    try:
        index = input.get(label+'number',0)
        if isinstance(index,(list,tuple)):
            index = index[0]
        index = int(index)
    except ValueError:
        index = 0
    try:
        total = input.get('total'+label+'s',0)
        if isinstance(total,(list,tuple)):
            total = total[0]
        total = int(total)
    except ValueError:
        total = 0
    ret = []
    if index:
        index = str(index)
        if total:
            index = index + '/' + str(total)
        if outlabel is None:
            outlabel = label
        ret.append((outlabel,index))
    return ret

def id3tiplin(i, o, k, v):
    pmap = {
        'arranger':'arranger',
        'engineer':'engineer',
        'producer':'producer',
        'DJ-mix':'djmixer',
        'mix':'mixer'
    }
    for key, value in v.people:
        if key in pmap:
            o.setdefault(pmap[key],[]).append(value)

def id3usltin(i, o, k, v):
    text = u'\n'.join(v.text.splitlines())
    return [('lyrics',[text])]

def id3ufidin(i, o, k, v):
    return (('musicbrainz_trackid',[v.data]),)

def id3tiplout(i, o, k, v):
    pmap = {
        'arranger':'arranger',
        'engineer':'engineer',
        'producer':'producer',
        'djmixer':'DJ-mix',
        'mixer':'mix'
    }
    if k not in pmap:
        return
    k = pmap[k]
    t = o.setdefault('TIPL',[])
    t.extend(zip([k]*len(v),v))

def id3rva2in(i, o, k, v):
    if v.channel != 1:
        return
    if not v.desc:
        if 'replaygain_track_gain' in self:
            return
        else:
            target = 'track'
    elif v.desc.lower() == 'track':
        target = 'track'
    elif v.desc.lower() == 'album':
        target = 'album'
    o['_'.join(('replaygain',target,'gain'))] = "%.3f dB" % v.gain
    o['_'.join(('replaygain',target,'peak'))] = "%.8f" % v.peak

def id3rva2out(i, o, k, v):
    if 'track' in k:
        target = 'track'
    elif 'album' in k:
        target = 'album'
    try:
        gain = float(re.search('[+-]?[0-9]*(\.[0-9]*)?([^0-9]|$)', i.get('_'.join(('replaygain',target,'gain')),'0.0')).group(0))
    except Exception:
        gain = 0.0
    try:
        peak = float(re.search('[+-]?[0-9]*(\.[0-9]*)?([^0-9]|$)', i.get('_'.join(('replaygain',target,'peak')),'0.0')).group(0))
        peak = abs(peak)
    except Exception:
        peak = 0.0
    o[':'.join(('RVA2',target))] = id3.RVA2(desc=target,peak=peak,gain=gain,channel=1)

id3_encodings=(
    'iso-8859-1',
    'utf-16',
    'utf-16be',
    'utf-8'
)

def best_encoding(txt):
    r = []
    for n in range(4):
        try:
            r.append((len(txt.encode(id3_encodings[n])),n))
        except UnicodeError:
            pass
    r.sort()
    return r[0][1]

def id3itemout(k,v):
    if isinstance(v, id3.Frame):
        return k,v
    fid = k[:4]
    if fid.startswith('T'):
        if isinstance(v,basestring):
            v = [v]
        if fid == 'TIPL':
            enc = best_encoding(u'\0'.join(reduce(lambda x,y: x+y, v)))
        else:
            enc = best_encoding(u'\0'.join(v))
        if fid == 'TXXX':
            return k,id3.TXXX(encoding=enc,desc=k.split(':',1)[1],text=v)
        else:
            return k,getattr(id3,fid)(encoding=enc,text=v)
    elif fid == 'USLT':
        if isinstance(v, (list,tuple)):
            v = v[0]
        enc = best_encoding(v)
        return "USLT::'und'",id3.USLT(encoding=enc,text=v,lang='und')
    elif k == 'UFID:http://musicbrainz.org':
        if isinstance(v, (list,tuple)):
            v = v[0]
        return k,id3.UFID(owner='http://musicbrainz.org',data=v)
tagmap = {
    APEv2:{
        'keysasis':(
            'album',
            'title',
            'artist',
            'composer',
            'lyricist',
            'conductor',
            'arranger',
            'engineer',
            'producer',
            'djmixer',
            'mixer',
            'grouping',
            'subtitle',
            'discsubtitle',
            'compilation',
            'comment',
            'genre',
            'bpm',
            'mood',
            'isrc',
            'copyright',
            'lyrics',
            'media',
            'label',
            'catalognumber',
            'barcode',
            'encodedby',
            'albumsort',
            'albumartistsort',
            'artistsort',
            'titlesort',
            'musicbrainz_trackid',
            'musicbrainz_albumid',
            'musicbrainz_artistid',
            'musicbrainz_albumartistid',
            'musicbrainz_trmid',
            'musicbrainz_discid',
            'musicip_puid',
            'replaygain_album_gain',
            'replaygain_album_peak',
            'replaygain_track_gain',
            'replaygain_track_peak',
            'releasecountry',
            'asin',
        ),
        'in':{
            'keytrans': lambda k: k.lower(),
            'valuetrans': lambda v: list(v),
            'keymap': {
                'album artist':'albumartist',
                'year':'date',
                'mixartist':'remixer',
                'musicbrainz_albumstatus':'releasestatus',
                'musicbrainz_albumtype':'releasetype',
                'track': lambda i,o,k,v: splitnumber(v.value,'track'),
                'disc': lambda i,o,k,v: splitnumber(v.value,'disc'),
            }
        },
        'out':{
            'keytrans': lambda k: {
                'mixartist':'MixArtist',
                'djmixer':'DJMixer',
                'discsubtitle':'DiscSubtitle',
                'bpm':'BPM',
                'isrc':'ISRC',
                'catalognumber':'CatalogNumber',
                'encodedby':'EncodedBy',
                'albumsort':'ALBUMSORT',
                'albumartistsort':'ALBUMARTISTSORT',
                'artistsort':'ARTISTSORT',
                'titlesort':'TITLESORT',
                'musicbrainz_trackid':'MUSICBRAINZ_TRACKID',
                'musicbrainz_albumid':'MUSICBRAINZ_ALBUMID',
                'musicbrainz_artistid':'MUSICBRAINZ_ARTISTID',
                'musicbrainz_albumartistid':'MUSICBRAINZ_ALBUMARTISTID',
                'musicbrainz_trmid':'MUSICBRAINZ_TRMID',
                'musicbrainz_discid':'MUSICBRAINZ_DISCID',
                'musicip_puid':'MUSICIP_PUID',
                'releasecountry':'RELEASECOUNTRY',
                'asin':'ASIN',
                'MUSICBRAINZ_ALBUMSTATUS':'MUSICBRAINZ_ALBUMSTATUS',
                'MUSICBRAINZ_ALBUMTYPE':'MUSICBRAINZ_ALBUMTYPE',
                'replaygain_album_gain':'replaygain_album_gain',
                'replaygain_album_peak':'replaygain_album_peak',
                'replaygain_track_gain':'replaygain_track_gain',
                'replaygain_track_peak':'replaygain_track_peak',
            }.get(k,None) or k.title(),
            'valuetrans': lambda v: isinstance(v,(tuple,list)) and u'\0'.join(v) or v,
            'keymap': {
                'albumartist':'album artist',
                'releasestatus':'MUSICBRAINZ_ALBUMSTATUS',
                'releasetype':'MUSICBRAINZ_ALBUMTYPE',
                'date':'Year',
                'remixer':'mixartist',
                'tracknumber': lambda i,o,k,v: joinnumber(i,'track'),
                'discnumber': lambda i,o,k,v: joinnumber(i,'disc'),
            }
        }

    },
    VCommentDict:{
        'keysasis':(
            'album',
            'title',
            'artist',
            'albumartist',
            'date',
            'composer',
            'lyricist',
            'conductor',
            'remixer',
            'arranger',
            'engineer',
            'producer',
            'djmixer',
            'mixer',
            'grouping',
            'subtitle',
            'discsubtitle',
            'compilation',
            'comment',
            'genre',
            'bpm',
            'mood',
            'isrc',
            'copyright',
            'lyrics',
            'media',
            'label',
            'catalognumber',
            'barcode',
            'encodedby',
            'albumsort',
            'albumartistsort',
            'artistsort',
            'titlesort',
            'musicbrainz_trackid',
            'musicbrainz_albumid',
            'musicbrainz_artistid',
            'musicbrainz_albumartistid',
            'musicbrainz_trmid',
            'musicbrainz_discid',
            'musicip_puid',
            'replaygain_album_gain',
            'replaygain_album_peak',
            'replaygain_track_gain',
            'replaygain_track_peak',
            'releasecountry',
            'asin',
        ),
        'in':{
            'keytrans': lambda k: k.lower(),
            'keymap': {
                'musicbrainz_albumstatus':'releasestatus',
                'musicbrainz_albumtype':'releasetype',
                'tracknumber': lambda i,o,k,v: splitnumber(v,'track'),
                'discnumber': lambda i,o,k,v: splitnumber(v,'disc'),
            }
        },
        'out':{
            'keytrans': lambda k: k.upper(),
            'valuetrans': lambda v: isinstance(v,basestring) and [v] or v,
            'keymap': {
                'releasestatus':'MUSICBRAINZ_ALBUMSTATUS',
                'releasetype':'MUSICBRAINZ_ALBUMTYPE',
                'tracknumber': lambda i,o,k,v: joinnumber(i,'track','tracknumber'),
                'discnumber': lambda i,o,k,v: joinnumber(i,'disc','discnumber'),
            }
        }
    },
    ID3:{
        'in':{
            'keytrans': lambda k: (k.startswith('TXXX') or k.startswith('UFID')) and k or k.split(':',1)[0],
            'valuetrans': lambda v: [unicode(i) for i in v.text],
            'keymap': {
                'TALB':'album',
                'TIT2':'title',
                'TPE1':'artist',
                'TPE2':'albumartist',
                'TDRC':'date',
                'TCOM':'composer',
                'TEXT':'lyricist',
                'TPE3':'conductor',
                'TPE4':'remixer',
                'TIPL':id3tiplin,
                'TIT1':'grouping',
                'TIT3':'subtitle',
                'TSST':'discsubtitle',
                'TRCK': lambda i,o,k,v: splitnumber(v.text,'track'),
                'TPOS': lambda i,o,k,v: splitnumber(v.text,'disc'),
                'TCMP':'compilation',
                'TCON':'genre',
                'TBPM':'bpm',
                'TMOO':'mood',
                'TSRC':'isrc',
                'TCOP':'copyright',
                'USLT':id3usltin,
                'TMED':'media',
                'TPUB':'label',
                'TXXX:CATALOGNUMBER':'catalognumber',
                'TXXX:BARCODE':'barcode',
                'TENC':'encodedby',
                'TSOA':'albumsort',
                'TXXX:ALBUMARTISTSORT':'albumartistsort',
                'TSOP':'artistsort',
                'TSOT':'titlesort',
                'UFID:http://musicbrainz.org':id3ufidin,
                'TXXX:MusicBrainz Album Id':'musicbrainz_albumid',
                'TXXX:MusicBrainz Artist Id':'musicbrainz_artistid',
                'TXXX:MusicBrainz Album Artist Id':'musicbrainz_albumartistid',
                'TXXX:MusicBrainz TRM Id':'musicbrainz_trmid',
                'TXXX:MusicBrainz Disc Id':'musicbrainz_discid',
                'TXXX:MusicIP PUID':'musicip_puid',
                'TXXX:MusicBrainz Album Status':'releasestatus',
                'TXXX:MusicBrainz Album Type':'releasetype',
                'TXXX:MusicBrainz Album Release Country':'releasecountry',
                'TXXX:ASIN':'asin',
                'RVA2': id3rva2in
            },
        },
        'out':{
            'itemtrans':id3itemout,
            'keymap': {
                'album':'TALB',
                'title':'TIT2',
                'artist':'TPE1',
		'albumartist':'TPE2',
                'date':'TDRC',
                'composer':'TCOM',
                'lyricist':'TEXT',
                'conductor':'TPE3',
                'remixer':'TPE4',
                'arranger':id3tiplout,
                'engineer':id3tiplout,
                'producer':id3tiplout,
                'djmixer':id3tiplout,
                'mixer':id3tiplout,
                'grouping':'TIT1',
                'subtitle':'TIT3',
                'discsubtitle':'TSST',
                'tracknumber': lambda i,o,k,v: joinnumber(i,'track','TRCK'),
                'discnumber': lambda i,o,k,v: joinnumber(i,'disc','TPOS'),
                'compilation':'TCMP',
                'genre':'TCON',
                'bmp':'TBPM',
                'mood':'TMOO',
                'isrc':'TSRC',
                'copyright':'TCOP',
                'lyrics':'USLT',
                'media':'TMED',
                'label':'TPUB',
                'catalognumber':'TXXX:CATALOGNUMBER',
                'barcode':'TXXX:BARCODE',
                'encodedby':'TENC',
                'albumsort':'TSOA',
                'albumartistsort':'TXXX:ALBUMARTISTSORT',
                'artistsort':'TSOP',
                'titlesort':'TSOT',
                'musicbrainz_trackid':'UFID:http://musicbrainz.org',
                'musicbrainz_albumid':'TXXX:MusicBrainz Album Id',
                'musicbrainz_artistid':'TXXX:MusicBrainz Artist Id',
                'musicbrainz_albumartistid':'TXXX:MusicBrainz Album Artist Id',
                'musicbrainz_trmid':'TXXX:MusicBrainz TRM Id',
                'musicbrainz_discid':'TXXX:MusicBrainz Disc Id',
                'musicip_puid':'TXXX:MusicIP PUID',
                'releasestatus':'TXXX:MusicBrainz Album Status',
                'releasetype':'TXXX:MusicBrainz Album Type',
                'releasecountry':'TXXX:MusicBrainz Album Release Country',
                'replaygain_track_gain':id3rva2out,
                'replaygain_album_gain':id3rva2out,
                'asin':'TXXX:ASIN',
            }
        }

    }

}
for value in tagmap.values():
    if 'keysasis' in value:
        value['keysasis'] = frozenset(value['keysasis'])

class NormMetaData(dict):

    def copy(self):
        return self.__class__(self)

    @classmethod
    def tagmapfor(cls, meta):
        global tagmap
        for c in (type(meta),) + type(meta).__bases__:
            if c in tagmap:
                return tagmap[c]
        raise TypeError("No mapping specified for tag type %s"%type(meta))

    @classmethod
    def converted(cls, meta):
        if hasattr(meta,'tags'):
            meta = meta.tags
        if isinstance(meta, cls):
            return cls(meta)
        else:
            tagmap = cls.tagmapfor(meta)
            newmeta = {}
            for key, value in meta.items():
                if 'keytrans' in tagmap['in']:
                    key = tagmap['in']['keytrans'](key)
                if 'keysasis' in tagmap and key in tagmap['keysasis']:
                    if 'valuetrans' in tagmap['in']:
                            value = tagmap['in']['valuetrans'](value)
                    newmeta[key] = value
                elif 'keymap' in tagmap['in'] and key in tagmap['in']['keymap']:
                    keymap = tagmap['in']['keymap'][key]
                    if isinstance(keymap, basestring):
                        if 'valuetrans' in tagmap['in']:
                            value = tagmap['in']['valuetrans'](value)
                        newmeta[keymap] = value
                    else:
                        l = keymap(meta,newmeta,key,value)
                        if l is not None:
                            newmeta.update(l)
            for k in newmeta.keys():
                if isinstance(newmeta[k],(list,tuple)):
                    newmeta[k] = [i for i in newmeta[k] if i]
                if not newmeta[k]:
                    del newmeta[k]
            return cls(newmeta)

    def flat(self, newmeta = None):
        if newmeta is None:
            newmeta = self.__class__()
        #we assume here that all items are numeric, a string, a list of
        #strings, or a list of associations.
        for key, value in self.iteritems():
            if isinstance(value,(list,tuple)):
                if not reduce(and_,(isinstance(i,basestring) for i in value)):
                    value = (': '.join(i) for i in value)
                value = u'; '.join(value)
            newmeta[key] = value
        #make sure the numeric members *always* have numeric values
        for k in ('tracknumber','totaltracks','discnumber','totaldiscs'):
            newmeta.setdefault(k,0)
        return newmeta

    def evaluate(self, expr,d = None):
        return evaluate(expr,self.flat(d))

    def apply(self, target, clear=False):
        if target.tags is None:
            target.add_tags()
        if clear:
            target.tags.clear
        tagmap = self.tagmapfor(target.tags)
        newmeta = {}
        for key, value in self.items():
            if 'keysasis' in tagmap and key in tagmap['keysasis']:
                newmeta[key] = value
            elif 'keymap' in tagmap['out'] and key in tagmap['out']['keymap']:
                keymap = tagmap['out']['keymap'][key]
                if isinstance(keymap, basestring):
                    newmeta[keymap] = value
                else:
                    l = keymap(self,newmeta,key,value)
                    if l is not None:
                        newmeta.update(l)
        itemtrans = None
        if 'itemtrans' in tagmap['out']:
            itemtrans = tagmap['out']['itemtrans']
        elif 'keytrans' in tagmap['out'] or 'valuetrans' in tagmap['out']:
            keytrans = 'keytrans' in tagmap['out'] and tagmap['out']['keytrans'] or (lambda x: x)
            valuetrans = 'valuetrans' in tagmap['out'] and tagmap['out']['valuetrans'] or (lambda x: x)
            itemtrans = lambda k,v: (keytrans(k),valuetrans(v))
        if itemtrans:
            target.tags.update(itemtrans(k,v) for k,v in newmeta.items())
        else:
            target.tags.update(newmeta)

__all__ = ['NormMetaData']