###########################################################################
#    Copyright (C) 2008 by Andrew Mahone                                      
#    <andrew.mahone@gmail.com>                                                             
#
# Copyright: See COPYING file that comes with this distribution
#
###########################################################################
from pyparsing import *
import re
ParserElement.enablePackrat()

class Value(object):
    def __new__(cls,*args,**kw):
        ret = object.__new__(cls,*args,**kw)
        return ret
    pass

def evaluate(item,cdict):
    if isinstance(item,Value):
        return item.evaluate(cdict)
    else:
        return item

#this is necessary because Formats need to know if items are substitutions,
#even if the items are literals.
class SubsValue(Value):
    def __new__(cls,data):
        if isinstance(data,Value):
            return data
        else:
            return Value.__new__(cls,data)
    def __init__(self,data):
        self.data = data

    def evaluate(self,cdict):
        return self.data

class LookupValue(Value):
    def __init__(self,key):
        self.key = key
    def evaluate(self, cdict):
        return cdict.get(self.key,u'')

class FuncValue(Value):
    def __init__(self,args):
        self.funcname = args[0]
        self.args = tuple(args[1:])

    def evaluate(self, cdict):
        return getattr(self,self.funcname)(cdict,*self.args)

    def firstof(self,cdict,*args):
        for arg in args:
            arg = evaluate(arg,cdict)
            if arg:
                return arg
        return u''

    def format(self,cdict,*args):
        return evaluate(args[0],cdict) % (evaluate(arg,cdict) for arg in args[1:])

    def iftrue(self,cdict,*args):
        cond = evaluate(args[0],cdict)
        if len(args) == 1:
            if cond: return cond
        elif len(args) == 2:
            if cond: return evaluate(args[1],cdict)
        else:
            if cond:
                return evaluate(args[1],cdict)
            else:
                return evaluate(args[2],cdict)
        return ''
    locals()['if'] = iftrue

    def joinpath(self, cdict, *args):
        return os.path.join(evaluate(arg,cdict) for arg in args)

class TupleValue(Value):
    def __new__(cls,items):
        if not [item for item in items if isinstance(item,Value)]:
            return tuple(items)
        else:
            return Value.__new__(cls,items)
    def __init__(self,items):
        self.items = items
    def evaluate(self,cdict):
        return tuple(evaluate(item,cdict) for item in self.items)

class ReductionValue(Value):
    opstbl = {
        '%': lambda x,y: x % y,
        '/': lambda x,y: x / y,
        '*': lambda x,y: x * y,
        '+': lambda x,y: x + y,
        '-': lambda x,y: x - y,
        '<': lambda x,y: x < y,
        '>': lambda x,y: x > y,
        '<=': lambda x,y: x <= y,
        '>=': lambda x,y: x >= y,
        '!=': lambda x,y: x != y,
        '==': lambda x,y: x == y,
    }
    def __new__(cls,args):
        if len(args) == 1:
            return args[0]
        else:
            if [args[i] for i in range(0,len(args),2) if isinstance(args[i],Value)]:
                return Value.__new__(cls,args)
            else:
                first = args[0]
                rest = tuple(tuple(args[n:n+2]) for n in range(1,len(args)-1,2))
                return reduce(lambda x,y: cls.opstbl[y[0]](x,y[1]), rest, first)

    def __init__(self,args):
        #because of single-term reduction bubbling up through parse levels, 
        #we might get init'ed again.
        if hasattr(self,'first') and hasattr(self,'rest'):
            return
        self.first = args[0]
        if len(args) % 2 != 1:
            raise ValueError('wrong number of arguments')
        self.rest = tuple((self.opstbl[args[n]],args[n+1]) for n in range(1,len(args)-1,2))

    def evaluate(self,cdict):
        return reduce(lambda x,y: y[0](x,evaluate(y[1],cdict)), self.rest, evaluate(self.first,cdict))

class BooleanReductionValue(ReductionValue):
    #values need to be wrapped in a lambda, then called, to prevent their
    #evaluation in the short-circuit case
    opstbl = {
        'and': lambda x,y: x and y(),
        'or': lambda x,y: x or y(),
    }

    def evaluate(self,cdict):
        return reduce(lambda x,y: y[0](x,lambda:evaluate(y[1],cdict)), self.rest, evaluate(self.first,cdict))

    #this means we also need to change the formula for constant reduction
    def __new__(cls,args):
        if len(args) == 1:
            return args[0]
        else:
            if [args[i] for i in range(0,len(args),2) if isinstance(args[i],Value)]:
                return Value.__new__(cls,args)
            else:
                first = args[0]
                rest = tuple(tuple(args[n:n+2]) for n in range(1,len(args)-1,2))
                return reduce(lambda x,y: cls.opstbl[y[0]](x,lambda:y[1]), rest, first)

class UnaryOperatorValue(Value):
    opstbl = {
        '-': lambda x: -x,
        '+': lambda x: +x,
        'not': lambda x: not x,
    }
    def __new__(cls, args):
        if len(args) == 1:
            return args[0]
        else:
            if isinstance(args[1],Value):
                return Value.__new__(value,args)
            else:
                return cls.opstbl[args[0]](args[1])
    def __init__(self,args):
        self.op = self.opstbl(args[0])
        self.value = args[1]
    def evaluate(self,cdict):
        return self.op(evaluate(self.value,cdict))

class AsIs(Value):
    def __init__(self,items):
        self.subvalue = items[0]

    def evaluate(self,cdict):
        return evaluate(self.subvalue,cdict)

class Format(Value):
    def __init__(self,items):
        if isinstance(items, basestring):
            items = formatexpr.parseString(items)
        elif isinstance(items,Format):
            items = items.parsedformat
        self.parsedformat = items
    def sanitize(self,instring):
        return re.sub(r'[]?[/\\=+<>:;",*|]','_',instring)
    def evaluate(self, cdict):
        reslist = []
        for item in self.parsedformat:
            if isinstance(item,Value):
                if isinstance(item,AsIs):
                    item = re.sub(r'[]?[\\=+<>:;",*|]','_',item.evaluate(cdict))
                else:
                    item = re.sub(r'[]?[/\\=+<>:;",*|]','_',item.evaluate(cdict))
            reslist.append(item)
        return ''.join(reslist)

class Expr(Value):
    def __init__(self,items):
        if isinstance(items,basestring):
            items = expr.parseString(items)
        elif isinstance(items,Expr):
            items = items.parsedformat
        self.parsedformat = items
    def evaluate(self, cdict):
        return evaluate(self.parsedformat[0],cdict)

def NumericValue(string):
    if '.' in string:
        return float(string)
    else:
        return int(string)

doubquot = QuotedString('"','\\','\\')
singquot = QuotedString("'",'\\','\\')
quot = doubquot | singquot
quot.setParseAction(lambda s,loc,toks: unicode(u''.join(toks)))
spaces = Optional(Word(' \t\n').suppress())
expr = Forward()
number = Regex('([0-9]+(\.[0-9]*)?|(\.[0-9]+))')
number.setParseAction(lambda s,loc,toks: NumericValue(toks[0]))
truth = Keyword('True') | Keyword('False')
truth.setParseAction(lambda s,loc,toks: toks[0] == 'True')
validname = Word(alphas,alphanums+'_')
lookup = validname.copy()
lookup.setParseAction(lambda s,loc,toks: LookupValue(u''.join(toks)))
lparen = Literal('(').suppress()
rparen = Literal(')').suppress()
arglist = delimitedList(expr)
funccall = validname + lparen + spaces + arglist + spaces + rparen
funccall.setParseAction(lambda s,loc,toks: FuncValue(toks))
parenexpr = lparen + spaces + expr + spaces + rparen
tupleelem = expr + Literal(',').suppress()
tupleexpr = lparen + tupleelem + ZeroOrMore(tupleelem) + Optional(expr) + rparen
tupleexpr.setParseAction(lambda s,loc,toks: TupleValue(toks))
sumop = Literal('+') | Literal('-')
atom =  Optional(sumop + spaces) + (truth | funccall | quot | lookup | number | parenexpr | tupleexpr) + spaces
atom.setParseAction(lambda s,loc,toks:UnaryOperatorValue(toks))
productop = Literal('*') | Literal('/') | Literal('%')
product = atom + ZeroOrMore(spaces + productop + spaces + atom)
product.setParseAction(lambda s,loc,toks: ReductionValue(toks))
sumop = Literal('+') | Literal('-')
sum = product + ZeroOrMore(spaces + sumop + spaces + product)
sum.setParseAction(lambda s,loc,toks: ReductionValue(toks))
compareop = Literal('<=') | Literal('>=') | Literal('<') | Literal('>') | Literal('==') | Literal('!=')
comparison = sum + ZeroOrMore(spaces + compareop + spaces + sum)
comparison.setParseAction(lambda s,loc,toks: ReductionValue(toks))
notexpr = Optional(Keyword('not') + spaces) + comparison
notexpr.setParseAction(lambda s,loc,toks: UnaryOperatorValue(toks))
andexpr = notexpr + ZeroOrMore(spaces + Keyword('and') + spaces + notexpr)
andexpr.setParseAction(lambda s,loc,toks: BooleanReductionValue(toks))
orexpr = andexpr + ZeroOrMore(spaces + Keyword('or') + spaces + andexpr)
orexpr.setParseAction(lambda s,loc,toks: BooleanReductionValue(toks))
expr << orexpr
expr.leaveWhitespace()
subsint = Literal('$').suppress()
funcsubs = subsint + funccall
asissubs = subsint + Literal('/').suppress() + lparen + spaces + expr + spaces + rparen
asissubs.setParseAction(lambda s,loc,toks: AsIs(toks))
looksubs = subsint + lookup + WordEnd(alphanums + '_')
exprsubs = subsint + parenexpr
subs = exprsubs | asissubs | funcsubs | looksubs
subs.setParseAction(lambda s,loc,toks: SubsValue(toks[0]))
literal = Combine(OneOrMore(CharsNotIn('$')|(subsint+Literal('$'))))
formatexpr = OneOrMore(subs|literal)
formatexpr.leaveWhitespace()
__all__ = ['Format','Expr','evaluate']
